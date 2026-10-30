#!/usr/bin/env python3
"""Reversible service cutover. All mutations are confined to recognized paths."""
import argparse
import base64
import contextlib
import datetime
import fcntl
import grp
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from deployment_state import (CONFIGS, SERVICES, MODE_PATH, safe_path, inspect_installation,
                              validate_listeners, validate_unit)
from render_config import render_configs, validate_values
from runtime_install import prepare_runtime

ALL_SERVICES = list(dict.fromkeys(s for names in SERVICES.values() for s in names))
ALL_CONFIGS = list(dict.fromkeys(p for names in CONFIGS.values() for p in names))
ACCOUNTS = {'xray.service': 'xray', 'caddy.service': 'caddy', 'hysteria-server.service': 'hysteria'}
COMMANDS = {'xray.service': '/usr/local/bin/xray run -config /usr/local/etc/xray/config.json',
            'caddy.service': '/usr/bin/caddy run --environ --config /etc/caddy/Caddyfile',
            'hysteria-server.service': '/usr/local/bin/hysteria server --config /etc/hysteria/config.yaml'}


def atomic_write(path, data, mode=0o600, gid=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.raystack-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data if isinstance(data, bytes) else data.encode())
            f.flush()
            os.fsync(f.fileno())
            os.fchmod(f.fileno(), mode)
            if gid is not None:
                os.fchown(f.fileno(), 0, gid)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def snapshot_installation(root: Path, state: dict, backup_dir: Path, service_states: dict, target_mode=None) -> None:
    backup_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    backup_dir.chmod(0o700)
    from subscription_deployment import PATHS
    paths = list(dict.fromkeys(state['managed_paths'] + (CONFIGS[target_mode] if target_mode else ALL_CONFIGS) + [MODE_PATH] + PATHS))
    for service in (service_states if target_mode else ALL_SERVICES):
        paths.append('etc/systemd/system/' + service)
        directory = safe_path(root, 'etc/systemd/system/' + service + '.d')
        if directory.exists():
            paths += [str(p.relative_to(root)) for p in directory.iterdir()]
    files = {}
    for name in paths:
        path = safe_path(root, name)
        if path.exists():
            if not path.is_file():
                raise ValueError(f'Unsupported deployment resource: {name}')
            stat = path.stat()
            files[name] = {'data': base64.b64encode(path.read_bytes()).decode(),
                           'mode': stat.st_mode & 0o777, 'uid': stat.st_uid, 'gid': stat.st_gid}
        else:
            files[name] = None
    atomic_write(backup_dir / 'snapshot.json', json.dumps({'files': files, 'services': service_states, 'state': state}))


def restore_installation(root: Path, backup_dir: Path) -> dict:
    snapshot = json.loads((backup_dir / 'snapshot.json').read_text())
    for name, record in snapshot['files'].items():
        path = safe_path(root, name)
        if record is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, base64.b64decode(record['data']), record['mode'])
            if os.geteuid() == 0:
                os.chown(path, record['uid'], record['gid'])
    return snapshot['services']


class SystemServices:
    def state(self, service):
        enabled = subprocess.run(['systemctl', 'is-enabled', service], capture_output=True, text=True).stdout.strip()
        active = subprocess.run(['systemctl', 'is-active', '--quiet', service]).returncode == 0
        if enabled not in ('enabled', 'disabled', 'static', 'indirect', 'not-found', ''):
            raise RuntimeError(f'Unsupported service state for {service}: {enabled}')
        return {'enabled': enabled or 'not-found', 'active': active}

    def action(self, verb, service=None):
        subprocess.run(['systemctl', verb] + ([service] if service else []), check=True)

    def sockets(self, services):
        pids = {}
        for service in services:
            result = subprocess.run(['systemctl', 'show', service, '-p', 'MainPID', '--value'], capture_output=True, text=True)
            pid = result.stdout.strip()
            if pid.isdigit() and pid != '0':
                pids[pid] = service
        output = subprocess.check_output(['ss', '-H', '-lnptu'], text=True)
        sockets = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 6:
                continue
            port = parts[4].rsplit(':', 1)[-1]
            if not port.isdigit():
                continue
            owners = set(re.findall(r'pid=(\d+)', line))
            service = pids.get(next(iter(owners))) if len(owners) == 1 else None
            sockets.append({'transport': parts[0], 'port': int(port), 'service': service})
        return sockets

    def validate(self, mode, stage):
        if mode != 'hy2':
            subprocess.run(['/usr/local/bin/xray', 'run', '-test', '-config', str(stage / 'usr/local/etc/xray/config.json')], check=True)
        if mode == 'ws':
            subprocess.run(['/usr/bin/caddy', 'validate', '--config', str(stage / 'etc/caddy/Caddyfile'), '--adapter', 'caddyfile'], check=True)

    def wait(self, mode):
        required = {'ws': {('tcp', 443, 'caddy.service'), ('tcp', 10000, 'xray.service')},
                    'reality': {('tcp', 443, 'xray.service')},
                    'hy2': {('udp', 443, 'hysteria-server.service')}}[mode]
        deadline = time.monotonic() + (120 if mode == 'hy2' else 30)
        while time.monotonic() < deadline:
            for service in SERVICES[mode]:
                result = subprocess.run(['systemctl', 'is-failed', '--quiet', service])
                if result.returncode == 0:
                    raise RuntimeError(f'{service} failed; inspect journalctl -u {service}')
            active = all(self.state(s)['active'] for s in SERVICES[mode])
            sockets = {(x['transport'], x['port'], x['service']) for x in self.sockets(SERVICES[mode])}
            if active and required <= sockets:
                return
            time.sleep(1)
        raise RuntimeError(f'{mode} readiness timeout (including certificate issuance); inspect journalctl -u {SERVICES[mode][-1]}')


class Deployment:
    def __init__(self, root: Path, services=None):
        self.root = root.absolute()
        if services is None and self.root != Path('/'):
            raise ValueError('Real service operations require the live root; tests must provide a service adapter')
        self.services = services if services is not None else SystemServices()
        self.live = services is None

    @contextlib.contextmanager
    def lock(self):
        path = safe_path(self.root, 'run/lock/raystack.lock')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError('Another raystack installation is running') from exc
            yield

    def credentials(self, mode, values):
        values = dict(values)
        pairs = {'uuid': 'uuid'} if mode != 'hy2' else {'hy2_password': 'hy2-password'}
        if mode == 'reality':
            pairs.update(reality_private_key='reality-private-key', reality_public_key='reality-public-key', reality_short_id='reality-short-id')
        for field, name in pairs.items():
            p = safe_path(self.root, 'etc/raystack/' + name)
            if p.exists():
                values[field] = p.read_text().strip()
        return values, pairs

    def write_credentials(self, values, pairs):
        directory = safe_path(self.root, 'etc/raystack')
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        for field, name in pairs.items():
            if values.get(field):
                atomic_write(safe_path(self.root, 'etc/raystack/' + name), values[field] + '\n')

    def write_units(self, mode, services=None):
        for service in (services if services is not None else SERVICES[mode]):
            user = ACCOUNTS[service]
            text = f'''# Managed by raystack
[Unit]
Description=raystack {service}
After=network-online.target
Wants=network-online.target
[Service]
User={user}
Group={user}
ExecStart={COMMANDS[service]}
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE
LimitNOFILE=1048576
UMask=0077
StateDirectory={user}
[Install]
WantedBy=multi-user.target
'''
            if service == 'caddy.service':
                text = text.replace('UMask=0077', 'Environment=XDG_DATA_HOME=/var/lib/caddy/.local/share\nEnvironment=XDG_CONFIG_HOME=/var/lib/caddy/.config\nUMask=0077')
            atomic_write(safe_path(self.root, 'etc/systemd/system/' + service), text, 0o644)
        if mode == 'hy2':
            for relative in ('var/lib/hysteria', 'var/lib/hysteria/acme'):
                path = safe_path(self.root, relative)
                path.mkdir(parents=True, exist_ok=True, mode=0o700)
                path.chmod(0o700)
                if self.live:
                    import pwd
                    user = pwd.getpwnam('hysteria')
                    os.chown(path, user.pw_uid, user.pw_gid)

    def remove_mode_resources(self, state, mode):
        target_services = getattr(self, 'target_services', SERVICES[mode])
        for name in state['managed_paths']:
            if name not in CONFIGS[mode] and not (name == 'etc/caddy/Caddyfile' and 'caddy.service' in target_services):
                safe_path(self.root, name).unlink(missing_ok=True)
        for service in set(state['services']) | set(target_services):
            directory = safe_path(self.root, 'etc/systemd/system/' + service + '.d')
            if directory.exists():
                for path in directory.iterdir():
                    path.unlink()
            if service not in target_services:
                safe_path(self.root, 'etc/systemd/system/' + service).unlink(missing_ok=True)

    def rollback(self, backup, target):
        errors = []
        # Attempt every restoration even if one service operation fails.
        for service in getattr(self, 'target_services', SERVICES[target]):
            for verb in ('stop', 'disable'):
                try:
                    self.services.action(verb, service)
                except Exception as exc:
                    errors.append(str(exc))
        states = restore_installation(self.root, backup)
        self.services.action('daemon-reload')
        for service, previous in states.items():
            try:
                # New services without a prior unit need no restoration command.
                if previous['enabled'] == 'not-found' and not previous['active']:
                    continue
                if previous['enabled'] == 'enabled':
                    self.services.action('enable', service)
                elif previous['enabled'] in ('disabled', 'indirect'):
                    self.services.action('disable', service)
                self.services.action('start' if previous['active'] else 'stop', service)
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError('; '.join(errors))

    def install(self, mode, values, prepare=prepare_runtime, subscription=None):
        with self.lock():
            return self._install(mode, values, prepare, subscription)

    def _install(self, mode, values, prepare, subscription):
        state = inspect_installation(self.root, replace_xray=True, selected_mode=mode)
        from subscription_deployment import SERVICES as SUB_SERVICES, resources, caddy_config, initialize, prepare_dependencies
        old_subscription = safe_path(self.root, 'etc/raystack/traffic.json').exists()
        self.target_services = list(SERVICES[mode]) + (['caddy.service'] if subscription and mode != 'ws' else []) + (SUB_SERVICES if subscription else [])
        affected = list(dict.fromkeys(state['services'] + self.target_services + (SUB_SERVICES if old_subscription else [])))
        previous_states = {s: self.services.state(s) for s in affected}
        for service in affected:
            if service not in SUB_SERVICES:
                validate_unit(self.root, service)
            if service in SUB_SERVICES:
                for prefix in ('etc/systemd/system', 'run/systemd/system', 'usr/lib/systemd/system', 'lib/systemd/system'):
                    dropins = safe_path(self.root, prefix + '/' + service + '.d')
                    if dropins.exists() and any(dropins.iterdir()):
                        raise ValueError(f'{service} has custom systemd overrides')
                    if prefix != 'etc/systemd/system' and safe_path(self.root, prefix + '/' + service).exists():
                        raise ValueError(f'{service} has an unmanaged systemd unit')
                existing = safe_path(self.root, 'etc/systemd/system/' + service)
                if existing.exists() and not existing.read_text().startswith('# Managed by raystack\n'):
                    raise ValueError(f'{service} is not owned by the subscription installer')
                if old_subscription:
                    continue
            if service not in state['services'] and (previous_states[service]['active'] or previous_states[service]['enabled'] == 'enabled'):
                raise ValueError(f'{service} is enabled without a recognized configuration; refusing to replace it')
        validate_listeners(state, mode, self.services.sockets(state['services']))
        values, pairs = self.credentials(mode, values)
        files = render_configs(mode, values)
        values = validate_values(mode, values)
        if subscription:
            caddy_path = safe_path(self.root, 'etc/caddy/Caddyfile')
            if caddy_path.exists() and 'etc/caddy/Caddyfile' not in state['managed_paths']:
                raise ValueError('Subscription HTTPS requires Caddy; existing unrelated Caddy configuration will not be replaced')
            sockets = self.services.sockets(affected)
            for sock in sockets:
                if sock['transport'] == 'tcp' and sock['port'] in (80, 8443, 8765):
                    allowed = set(state['services']) | (set(SUB_SERVICES) if old_subscription else set())
                    if sock.get('service') not in allowed:
                        raise ValueError(f"Subscription port {sock['port']}/tcp is occupied by an unrelated service")
        subscription_config = None
        if subscription:
            subscription_config, extra = resources(self.root, mode, values, subscription)
            files.update(extra)
            base = files.get('etc/caddy/Caddyfile')
            files['etc/caddy/Caddyfile'] = caddy_config(mode, subscription_config['subscription_domain'], base)
            if mode == 'hy2':
                hy2 = json.loads(files['etc/hysteria/config.yaml'])
                hy2['acme']['http'] = {'altPort': 8888}
                files['etc/hysteria/config.yaml'] = json.dumps(hy2)
            # Include extra target configs in the snapshot even on fresh installations.
            state['managed_paths'] = list(dict.fromkeys(state['managed_paths'] + ['etc/caddy/Caddyfile']))
        print(f"[raystack] Mode: {', '.join(state['modes']) or 'none'} -> {mode}", flush=True)
        prepare(mode)
        if subscription and self.live:
            prepare_dependencies()
            from runtime_install import ensure_account
            ensure_account('raystack')
            if mode != 'ws':
                from runtime_install import ensure_binary, ensure_account
                ensure_binary('ws')
                ensure_account('caddy')
        with tempfile.TemporaryDirectory(prefix='raystack-stage-') as temp:
            stage = Path(temp)
            for name, text in files.items():
                atomic_write(stage / name, text)
            self.services.validate(mode, stage)
            if subscription and self.live and mode != 'ws':
                subprocess.run(['/usr/bin/caddy', 'validate', '--config', str(stage / 'etc/caddy/Caddyfile'), '--adapter', 'caddyfile'], check=True)
            # Recheck ports after downloads before making the old mode unavailable.
            validate_listeners(state, mode, self.services.sockets(state['services']))
            backup_root = safe_path(self.root, 'etc/raystack/backups')
            backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            backup_root.chmod(0o700)
            backup = backup_root / (datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + os.urandom(4).hex())
            snapshot_installation(self.root, state, backup, previous_states, mode)
            print(f'[raystack] Backup: {backup}', flush=True)
            self.write_credentials(values, pairs)
            print('[raystack] Applying selected mode; existing connections may briefly disconnect.', flush=True)
            try:
                for service in list(dict.fromkeys(state['services'] + (SUB_SERVICES if old_subscription else []))):
                    self.services.action('stop', service)
                    self.services.action('disable', service)
                self.remove_mode_resources(state, mode)
                for name in files:
                    if name.startswith('etc/raystack/') or name.startswith('etc/systemd/'):
                        atomic_write(safe_path(self.root, name), (stage / name).read_bytes(), 0o644 if name.endswith('.service') else 0o600)
                        continue
                    service = 'hysteria-server.service' if name.startswith('etc/hysteria') else ('caddy.service' if name.startswith('etc/caddy') else 'xray.service')
                    gid = grp.getgrnam(ACCOUNTS[service]).gr_gid if self.live else None
                    atomic_write(safe_path(self.root, name), (stage / name).read_bytes(), 0o640, gid)
                self.write_units(mode)
                if subscription and mode != 'ws':
                    self.write_units('ws', ['caddy.service'])
                if subscription and self.live:
                    initialize(subscription_config)
                if not subscription and old_subscription:
                    retained = json.loads(safe_path(self.root, 'etc/raystack/traffic.json').read_text())
                    retained['enabled'] = False
                    atomic_write(safe_path(self.root, 'etc/raystack/traffic.json'), json.dumps(retained))
                self.services.action('daemon-reload')
                for service in self.target_services:
                    self.services.action('enable', service)
                    self.services.action('start', service)
                self.services.wait(mode)
                if subscription and self.live:
                    for service in self.target_services:
                        if not self.services.state(service)['active']:
                            raise RuntimeError(f'{service} failed to start')
                    from subscription_deployment import wait_https
                    wait_https(subscription_config)
                atomic_write(safe_path(self.root, MODE_PATH), mode + '\n')
            except BaseException as exc:
                print('[raystack] Installation failed; restoring previous mode.', file=sys.stderr, flush=True)
                try:
                    self.rollback(backup, mode)
                except BaseException as rollback_error:
                    raise RuntimeError(f'{exc}; rollback also failed: {rollback_error}; backup: {backup}') from exc
                raise
        if subscription_config:
            from subscription_deployment import url
            print('[raystack] Subscription URL: ' + url(subscription_config), flush=True)
            print('[raystack] Usage may need a minute to initialize. Allow TCP 80 and ' + ('443' if mode == 'ws' else '8443') + ' for HTTPS subscriptions.', flush=True)
        return values


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--subscription-options', type=Path)
    parser.add_argument('--mode', choices=['ws', 'reality', 'hy2'], required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(1, 'Run the installer with sudo/root\n')
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'Interrupted by signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    try:
        options = json.loads(args.subscription_options.read_text()) if args.subscription_options else None
        result = Deployment(Path('/')).install(args.mode, json.load(sys.stdin), subscription=options)
        from print_client_config import print_client_config
        print('[raystack] Installation complete; selected service is running and listening.')
        if args.mode == 'hy2':
            print('[raystack] Required firewall access: UDP 443 and TCP 80 (ACME renewal).')
        print('[raystack] Public client reachability has not been tested.')
        print(print_client_config(args.mode, result))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        parser.exit(1, f'Installation failed: {exc}\n')

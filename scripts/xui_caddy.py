#!/usr/bin/env python3
"""Configure a local SQLite 3x-ui installation behind Caddy HTTPS."""
import datetime
import contextlib
import fcntl
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

from deployment import atomic_write, Deployment, SystemServices
from deployment_state import safe_path
from render_config import hostname
from runtime_install import ensure_binary, ensure_account

IMPORT = 'import /etc/caddy/raystack-3x-ui.caddy'
MARKER = '# Managed by raystack: 3x-ui HTTPS\n'
FILES = ('etc/caddy/Caddyfile', 'etc/caddy/raystack-3x-ui.caddy',
         'etc/systemd/system/caddy.service')


@contextlib.contextmanager
def database(path):
    conn = sqlite3.connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{args[0]} {args[1]} failed: {result.stderr[-2000:]}')
    return result.stdout


def unit_property(service, name):
    # systemctl may return nonzero for an as-yet-uninstalled service.
    return subprocess.run(['systemctl', 'show', service, '-p', name, '--value'],
                          capture_output=True, text=True).stdout.strip()


def ask_domain(label):
    while True:
        try:
            return hostname(input(label).strip())
        except ValueError as exc:
            print(exc, file=sys.stderr)


def port(value, label):
    if not re.fullmatch(r'[0-9]+', str(value)) or not 1 <= int(value) <= 65535:
        raise ValueError(f'Invalid {label} port')
    return int(value)


def settings_patch(settings, panel, subscription):
    panel, subscription = hostname(panel), hostname(subscription)
    if panel == subscription:
        raise ValueError('Use different domains for the panel and subscription')
    # Keep a valid existing panel port, except public HTTP/HTTPS ports.
    panel_port = port(settings.get('webPort', '2053'), 'panel')
    if panel_port in (80, 443):
        panel_port = 38023
    sub_port = port(settings.get('subPort', '2096'), 'subscription')
    if sub_port in (80, 443, panel_port):
        sub_port = 2096 if panel_port != 2096 else 2097
    patch = {'webPort': str(panel_port), 'webListen': '127.0.0.1', 'webDomain': panel,
             'webCertFile': '', 'webKeyFile': '', 'subPort': str(sub_port),
             'subListen': '127.0.0.1', 'subCertFile': '', 'subKeyFile': '',
             'subDomain': subscription, 'subEnable': 'true',
             'subClashEnable': 'true', 'subClashAutoDetect': 'true',
             'subClashUserAgentRegex': '(?i)(clash|mihomo)'}
    for key, pathkey, default in [('subURI', 'subPath', '/sub/'),
                                 ('subJsonURI', 'subJsonPath', '/json/'),
                                 ('subClashURI', 'subClashPath', '/clash/')]:
        path = settings.get(pathkey, default)
        if not re.fullmatch(r'/[a-zA-Z0-9_/-]+/', path):
            raise ValueError(f'Unsupported {pathkey}; expected an absolute URL path with a trailing slash')
        patch[key] = f'https://{subscription}{path}'
    return patch


def site_config(panel, subscription, patch, base_path):
    if not re.fullmatch(r'/[a-zA-Z0-9_/-]*/', base_path) and base_path != '/':
        raise ValueError('Unsupported panel base path')
    redirect = f'    redir / {base_path} 302\n' if base_path != '/' else ''
    return (MARKER + f'https://{hostname(panel)}:443 {{\n' + redirect +
            f'    reverse_proxy 127.0.0.1:{patch["webPort"]}\n}}\n\n' +
            f'https://{hostname(subscription)}:443 {{\n'
            f'    reverse_proxy 127.0.0.1:{patch["subPort"]}\n}}\n')


def check_hosts(config, domains):
    """Inspect adapted JSON, including imported sites, rather than parse Caddyfile."""
    if isinstance(config, dict):
        for key, value in config.items():
            if key == 'host' and isinstance(value, list):
                for existing in value:
                    if any(existing == d or (existing.startswith('*.') and
                           d.endswith(existing[1:])) for d in domains):
                        raise ValueError(f'Caddy already has a site for {existing}; merge it manually or choose another domain')
            check_hosts(value, domains)
    elif isinstance(config, list):
        for value in config:
            check_hosts(value, domains)


def backup_files(root, backup):
    records = {}
    for name in FILES:
        p = safe_path(root, name)
        if p.exists():
            st = p.stat()
            records[name] = (p.read_bytes(), st.st_mode & 0o777, st.st_uid, st.st_gid)
            target = backup / name
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(target, records[name][0])
        else:
            records[name] = None
    return records


def restore_files(root, records):
    for name, record in records.items():
        p = safe_path(root, name)
        if record is None:
            p.unlink(missing_ok=True)
        else:
            data, mode, uid, gid = record
            atomic_write(p, data, mode)
            os.chown(p, uid, gid)


def wait_local(panel_port, sub_port, base_path, panel, subscription):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            panel_req = urllib.request.Request(f'http://127.0.0.1:{panel_port}{base_path}',
                                               headers={'Host': panel})
            with opener.open(panel_req, timeout=2) as r:
                if r.status != 200:
                    raise RuntimeError('Panel not ready')
            # A nonexistent subscriber should return an HTTP response, not TLS bytes.
            req = urllib.request.Request(f'http://127.0.0.1:{sub_port}/',
                                         headers={'Host': subscription})
            try:
                with opener.open(req, timeout=2):
                    pass
            except urllib.error.HTTPError:
                pass
            return
        except (OSError, ValueError, RuntimeError):
            time.sleep(1)
    raise RuntimeError('3x-ui HTTP readiness failed; inspect journalctl -u x-ui')


def certificates(domains, data_dir, timeout=30):
    """Return actual Caddy storage paths only after both files exist."""
    deadline = time.monotonic() + timeout
    found = {}
    while True:
        for domain in domains:
            pairs = [(p, p.with_suffix('.key'))
                     for p in (data_dir / 'certificates').glob(f'*/{domain}/{domain}.crt')]
            pair = next(((c, k) for c, k in pairs if c.is_file() and k.is_file()), None)
            if pair:
                found[domain] = pair
        if len(found) == len(domains) or time.monotonic() >= deadline:
            return found
        time.sleep(1)


def caddy_data_dir():
    pid = run(['systemctl', 'show', 'caddy', '-p', 'MainPID', '--value']).strip()
    env = dict(entry.split('=', 1) for entry in
               Path(f'/proc/{pid}/environ').read_bytes().decode().split('\0') if '=' in entry)
    if env.get('XDG_DATA_HOME'):
        return Path(env['XDG_DATA_HOME']) / 'caddy'
    if env.get('HOME'):
        return Path(env['HOME']) / '.local/share/caddy'
    raise RuntimeError('Cannot determine the running Caddy certificate storage directory')


def existing_caddy(root, panel, subscription):
    main = safe_path(root, FILES[0])
    snippet = safe_path(root, FILES[1])
    original = main.read_text() if main.exists() else ''
    if snippet.exists() and not snippet.read_text().startswith(MARKER):
        raise ValueError('The 3x-ui Caddy snippet already exists and is not managed by raystack')
    # Remove only our exact import when checking for unrelated domain ownership.
    base = '\n'.join(line for line in original.splitlines() if line.strip() != IMPORT) + '\n'
    if base.strip():
        main.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=main.parent, suffix='.caddyfile', mode='w') as f:
            f.write(base); f.flush()
            adapted = json.loads(run(['/usr/bin/caddy', 'adapt', '--config', f.name, '--adapter', 'caddyfile']))
        check_hosts(adapted, (panel, subscription))
    return base


def configure(root, panel, subscription):
    db = safe_path(root, 'etc/x-ui/x-ui.db')
    if not db.is_file():
        raise RuntimeError('Automatic setup requires the default SQLite database /etc/x-ui/x-ui.db')
    main = safe_path(root, FILES[0])
    snippet = safe_path(root, FILES[1])
    base = existing_caddy(root, panel, subscription)
    services = SystemServices()
    states = {name: services.state(name) for name in ('caddy.service', 'x-ui.service')}
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = root / 'etc/raystack/backups' / f'{stamp}-3x-ui-{os.urandom(3).hex()}'
    backup.mkdir(parents=True, mode=0o700)
    backup.chmod(0o700)
    records = backup_files(root, backup)
    atomic_write(backup / 'services.json', json.dumps(states))
    print(f'[raystack] HTTPS configuration backup: {backup}', flush=True)
    stopped = False
    try:
        services.action('stop', 'x-ui.service')
        stopped = True
        with database(db) as conn:
            with database(backup / 'x-ui.db') as target:
                conn.backup(target)
            (backup / 'x-ui.db').chmod(0o600)
            settings = dict(conn.execute('SELECT key,value FROM settings'))
            patch = settings_patch(settings, panel, subscription)
            base_path = settings.get('webBasePath', '/')
            text = site_config(panel, subscription, patch, base_path)
            for key, value in patch.items():
                cur = conn.execute('UPDATE settings SET value=? WHERE key=?', (value, key))
                if not cur.rowcount:
                    conn.execute('INSERT INTO settings(key,value) VALUES (?,?)', (key, value))
        atomic_write(snippet, text, 0o644)
        atomic_write(main, base.rstrip() + '\n\n' + IMPORT + '\n',
                     records[FILES[0]][1] if records[FILES[0]] else 0o644)
        if records[FILES[0]]:
            os.chown(main, records[FILES[0]][2], records[FILES[0]][3])
        if states['caddy.service']['enabled'] == 'not-found':
            ensure_account('caddy')
            Deployment(root, services=services).write_units('ws', ['caddy.service'])
        run(['/usr/bin/caddy', 'validate', '--config', str(main), '--adapter', 'caddyfile'])
        services.action('daemon-reload')
        services.action('reset-failed', 'x-ui.service')
        services.action('start', 'x-ui.service')
        wait_local(int(patch['webPort']), int(patch['subPort']), base_path, panel, subscription)
        if states['caddy.service']['active']:
            run(['/usr/bin/caddy', 'reload', '--config', str(main), '--adapter', 'caddyfile'])
        else:
            services.action('start', 'caddy.service')
        services.action('enable', 'caddy.service')
    except Exception:
        if stopped:
            errors = []
            if not states['caddy.service']['active'] and (root / FILES[2]).exists():
                try:
                    services.action('stop', 'caddy.service')
                except Exception as exc:
                    errors.append(str(exc))
            for action in (lambda: services.action('stop', 'x-ui.service'),
                           lambda: restore_database(db, backup / 'x-ui.db'),
                           lambda: restore_files(root, records),
                           lambda: services.action('daemon-reload')):
                try:
                    action()
                except Exception as exc:
                    errors.append(str(exc))
            for name, state in states.items():
                try:
                    if state['enabled'] == 'not-found':
                        (root / 'etc/systemd/system/multi-user.target.wants' / name).unlink(missing_ok=True)
                        continue
                    if name == 'caddy.service' and state['active']:
                        run(['/usr/bin/caddy', 'reload', '--config', str(main), '--adapter', 'caddyfile'])
                    else:
                        services.action('start' if state['active'] else 'stop', name)
                    if state['enabled'] in ('enabled', 'disabled'):
                        services.action('enable' if state['enabled'] == 'enabled' else 'disable', name)
                except Exception as exc:
                    errors.append(str(exc))
            if errors:
                print(f'[raystack] Rollback needs attention: {errors}; backup: {backup}', file=sys.stderr)
        raise
    print(f'\nPanel: https://{panel}{base_path}')
    print(f'Standard subscription base: {patch["subURI"]}<client-subscription-ID>')
    print(f'Clash subscription base: {patch["subClashURI"]}<client-subscription-ID>')
    print('Copy the standard subscription from a client in the panel; Clash/Mihomo format is detected automatically.')
    print('Panel and subscription listen on localhost HTTP; Caddy owns public HTTPS 443.')
    try:
        data_dir = caddy_data_dir()
        found = certificates((panel, subscription), data_dir)
        for domain in (panel, subscription):
            if domain in found:
                cert, key = found[domain]
                print(f'{domain}\n  Certificate: {cert}\n  Private key: {key}')
            else:
                print(f'{domain}: certificate not found yet. Check DNS, TCP 80/443 and journalctl -u caddy.')
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'Certificate paths not yet available: {exc}. Inspect journalctl -u caddy.')
    print('Caddy renews certificates automatically. Hysteria2 needs read access and certificate reload after renewal; paths alone do not configure it.')


def restore_database(db, backup):
    if backup.exists():
        with database(backup) as src, database(db) as dest:
            src.backup(dest)


def main(installer):
    panel = ask_domain('Panel domain (DNS-only, pointed at this VPS): ')
    subscription = ask_domain('Subscription domain (different from panel domain): ')
    if panel == subscription:
        raise ValueError('Panel and subscription domains must differ')
    # PostgreSQL and custom service/database paths need a dedicated adapter.
    environment = dict(os.environ)
    environment.update(entry.split('=', 1) for entry in shlex.split(
        unit_property('x-ui.service', 'Environment')) if '=' in entry)
    for name in ('/etc/default/x-ui', '/etc/sysconfig/x-ui', '/etc/conf.d/x-ui'):
        if Path(name).exists():
            for line in Path(name).read_text().splitlines():
                if re.match(r'\s*(?:export\s+)?XUI_DB_', line):
                    fields = shlex.split(line.removeprefix('export '), comments=True)
                    environment.update(entry.split('=', 1) for entry in fields if '=' in entry)
    if environment.get('XUI_DB_TYPE', 'sqlite') not in ('sqlite', '') or \
            environment.get('XUI_DB_FOLDER', '/etc/x-ui') != '/etc/x-ui' or \
            environment.get('XUI_DB_NAME', 'x-ui.db') != 'x-ui.db':
        raise ValueError('Automatic Caddy setup requires the default SQLite database; choose no for upstream setup')
    lock = Path('/run/lock/raystack.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ensure_binary('ws')
        unit = unit_property('caddy.service', 'ExecStart')
        if unit.strip() and not re.search(r'--config\s+/etc/caddy/Caddyfile(?:\s|;|$)', unit):
            raise ValueError('Existing Caddy uses a custom configuration location; automatic setup supports /etc/caddy/Caddyfile only')
        existing_caddy(Path('/'), panel, subscription)
        print('[raystack] DNS must point directly to this VPS; allow inbound TCP 80 and 443.')
        print('[raystack] Installing 3x-ui with SQLite and no internal TLS; upstream prints generated credentials.')
        env = dict(os.environ, XUI_NONINTERACTIVE='1', XUI_SSL_MODE='none', XUI_DB_TYPE='sqlite')
        subprocess.run(['bash', installer], env=env, check=True)
        configure(Path('/'), panel, subscription)


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except (EOFError, OSError, ValueError, RuntimeError, subprocess.SubprocessError, sqlite3.Error) as exc:
        sys.exit(f'3x-ui HTTPS setup failed: {exc}')

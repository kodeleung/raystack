#!/usr/bin/env python3
"""Read-only recognition of raystack configurations, including pre-marker installs."""

import argparse
import json
import re
from pathlib import Path

XRAY_CONFIG = 'usr/local/etc/xray/config.json'
CADDY_CONFIG = 'etc/caddy/Caddyfile'
HY2_CONFIG = 'etc/hysteria/config.yaml'
SERVICES = {'ws': ['xray.service', 'caddy.service'],
            'reality': ['xray.service'], 'hy2': ['hysteria-server.service']}
CONFIGS = {'ws': [XRAY_CONFIG, CADDY_CONFIG], 'reality': [XRAY_CONFIG], 'hy2': [HY2_CONFIG]}
MODE_PATH = 'etc/raystack/mode'


def safe_path(root, relative):
    path = root / relative
    for item in [path, *path.parents]:
        if item == root:
            break
        if item.is_symlink():
            raise ValueError(f'Refusing symlink in managed path: {relative}')
    return path


def read(root, relative):
    p = safe_path(root, relative)
    return p.read_text().strip() if p.exists() else None


def load_json(root, relative):
    text = read(root, relative)
    if text is None:
        return None
    try:
        cfg = json.loads(text)
        if not isinstance(cfg, dict):
            raise ValueError()
        return cfg
    except (ValueError, TypeError) as exc:
        raise ValueError(f'Unrecognized configuration: {relative}') from exc


def recognize_xray(root, cfg):
    uuid = read(root, 'etc/raystack/uuid')
    if not uuid or set(cfg) != {'log', 'inbounds', 'outbounds'}:
        raise ValueError('Xray configuration is not a recognized raystack installation')
    outbound = cfg['outbounds']
    if outbound not in ([{'protocol': 'freedom'}],
                         [{'protocol': 'freedom', 'settings': {}}],
                         [{'protocol': 'freedom', 'settings': {'domainStrategy': 'ForceIPv4'}}]):
        raise ValueError('Xray has unmanaged outbounds')
    modes = []
    template_dir = Path(__file__).resolve().parent.parent / 'config'
    for inbound in cfg['inbounds']:
        matched = None
        for mode in ('ws', 'reality'):
            text = (template_dir / f'xray-{mode}.json').read_text()
            expected = json.loads(text)['inbounds'][0]
            expected['settings']['clients'][0]['id'] = uuid
            if mode == 'reality':
                r = inbound.get('streamSettings', {}).get('realitySettings', {})
                er = expected['streamSettings']['realitySettings']
                if r.get('show') is not False:
                    continue
                for name in ('target', 'dest'):
                    if name in r:
                        er.pop('target', None)
                        er[name] = r[name]
                er['serverNames'] = r.get('serverNames')
                er['privateKey'] = read(root, 'etc/raystack/reality-private-key')
                sid = read(root, 'etc/raystack/reality-short-id')
                er['shortIds'] = [sid] if sid else []
                if not er['privateKey'] or not sid or not er['serverNames']:
                    continue
            if inbound == expected:
                matched = mode
                break
        if matched is None or matched in modes:
            raise ValueError('Xray has unmanaged or duplicate inbounds')
        modes.append(matched)
    if not modes:
        raise ValueError('Xray has no recognized inbounds')
    return [m for m in ('ws', 'reality') if m in modes]


def recognize_caddy(text, combined):
    # Older installers used a site address with an explicit port and retained
    # the distribution's comment header instead of a global https_port block.
    text = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
    legacy = re.fullmatch(r'\s*([a-zA-Z0-9.-]+):(443|8443)\s*\{(.*)\}\s*', text, re.S)
    if legacy:
        expected_port = '8443' if combined else '443'
        body = re.sub(r'\s+', '', legacy[3])
        allowed = 'handle/ray*{reverse_proxy127.0.0.1:10000}handle{respond"OK"}'
        return legacy[2] == expected_port and body in (allowed, 'encodezstdgzip' + allowed)
    match = re.search(r'\}\s*([a-zA-Z0-9.-]+)\s*\{', text)
    if not match:
        return False
    template = (Path(__file__).resolve().parent.parent / 'config/Caddyfile').read_text()
    expected = template.replace('__DOMAIN__', match[1]).replace('__HTTPS_PORT__', '8443' if combined else '443')
    subscription = '  handle /subscription/* {\n    reverse_proxy 127.0.0.1:8765\n  }\n\n'
    variants = [expected, expected.replace('  handle /ray* {', subscription + '  handle /ray* {')]
    if combined:
        variants.append('{\n  https_port 8443\n}\n%s {\n  handle /subscription/* {\n    reverse_proxy 127.0.0.1:8765\n  }\n  handle {\n    respond "OK"\n  }\n}\n' % match[1])
    normalized = re.sub(r'\s+', '', text)
    return any(normalized == re.sub(r'\s+', '', candidate) for candidate in variants)


def validate_unit(root, service):
    from service_units import validate_service
    validate_service(root, service, safe_path)


def inspect_installation(root: Path, replace_xray=False, selected_mode=None) -> dict:
    root = root.absolute()
    try:
        caddy = read(root, CADDY_CONFIG)
    except (ValueError, OSError):
        if selected_mode not in ('reality', 'hy2'):
            raise
        caddy = None
    subscription_caddy = False
    saved_subscription = load_json(root, 'etc/raystack/traffic.json')
    if saved_subscription and saved_subscription.get('enabled', True) and caddy is not None:
        from subscription_deployment import caddy_config
        node = saved_subscription.get('nodes', {})
        mode = node.get('mode')
        if mode in ('ws', 'reality', 'hy2'):
            base = (Path(__file__).resolve().parent.parent / 'config/Caddyfile').read_text().replace('__DOMAIN__', node.get('domain', '')).replace('__HTTPS_PORT__', '443')
            expected = caddy_config(mode, saved_subscription.get('subscription_domain', node.get('domain', '')), base)
            subscription_caddy = re.sub(r'\s+', '', caddy) == re.sub(r'\s+', '', expected)
    caddy_known = caddy is not None and (recognize_caddy(caddy, False) or recognize_caddy(caddy, True))
    replacing_unknown_xray = False
    try:
        cfg = load_json(root, XRAY_CONFIG)
        modes = recognize_xray(root, cfg) if cfg is not None else []
    except ValueError:
        if not replace_xray or not safe_path(root, XRAY_CONFIG).is_file():
            raise
        replacing_unknown_xray = True
        # Only explicitly replace the Xray config; do not adopt arbitrary Caddy sites.
        if caddy_known:
            modes = ['ws', 'reality'] if recognize_caddy(caddy, True) else ['ws']
        else:
            modes = ['reality']
    if caddy_known and not modes and replace_xray:
        modes = ['ws']
        replacing_unknown_xray = True
    if caddy is not None:
        if not (subscription_caddy or caddy_known):
            if selected_mode not in ('reality', 'hy2') or 'ws' in modes:
                raise ValueError('Caddy configuration contains unmanaged sites; refusing to replace it')
            caddy = None
    elif 'ws' in modes:
        raise ValueError('Incomplete WS installation: missing Caddy configuration')
    hy2 = load_json(root, HY2_CONFIG)
    if hy2 is not None:
        password = read(root, 'etc/raystack/hy2-password')
        if not password or hy2.get('auth') != {'type': 'password', 'password': password} or hy2.get('listen') != ':443':
            raise ValueError('Hysteria configuration is not owned by raystack')
        # A raystack generated file has a fixed schema, not arbitrary hooks/outbounds.
        if set(hy2) != {'listen', 'acme', 'auth'} or hy2.get('acme', {}).get('dir') != '/var/lib/hysteria/acme':
            raise ValueError('Hysteria configuration contains unmanaged settings')
        modes.append('hy2')
    marker = read(root, MODE_PATH)
    if marker is not None and (marker not in modes or len(modes) != 1) and not replacing_unknown_xray:
        raise ValueError('Mode marker disagrees with configurations; inspect interrupted installation')
    services = list(dict.fromkeys(s for m in modes for s in SERVICES[m]))
    if caddy is not None and 'caddy.service' not in services:
        services.append('caddy.service')
    for service in services:
        validate_unit(root, service)
    paths = list(dict.fromkeys(p for m in modes for p in CONFIGS[m]))
    if caddy is not None and CADDY_CONFIG not in paths:
        paths.append(CADDY_CONFIG)
    return {'modes': modes, 'services': services, 'managed_paths': paths, 'marker': marker}


def validate_listeners(state: dict, selected_mode: str, sockets: list[dict]) -> None:
    required = {'ws': {('tcp', 80), ('tcp', 443), ('udp', 443), ('tcp', 10000)},
                'reality': {('tcp', 443)}, 'hy2': {('tcp', 80), ('udp', 443)}}[selected_mode]
    for item in sockets:
        if (item['transport'], item['port']) in required and item.get('service') not in state['services']:
            raise ValueError(f"Port {item['port']}/{item['transport']} belongs to an unrelated service")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['inspect'])
    parser.add_argument('--root', type=Path, default=Path('/'))
    args = parser.parse_args()
    try:
        print(json.dumps(inspect_installation(args.root)))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'{exc}\n')

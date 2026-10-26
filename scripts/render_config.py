#!/usr/bin/env python3
"""Serialize staged configurations without shell/YAML interpolation."""
import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path


def hostname(value):
    value = value.strip().lower().rstrip('.')
    if len(value) > 253 or '.' not in value or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in value.split('.')):
        raise ValueError('Enter a DNS hostname, not a URL or wildcard')
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError('A DNS hostname is required for certificate issuance')


def validate_values(mode: str, values: dict) -> dict:
    if mode not in ('ws', 'reality', 'hy2'):
        raise ValueError(f'Unsupported installation mode: {mode}')
    v = dict(values)
    for value in v.values():
        if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Configuration values must be strings without control characters')
    if mode in ('ws', 'hy2'):
        v['domain'] = hostname(v.get('domain', ''))
    if mode == 'hy2':
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', v.get('email', '')):
            raise ValueError('A valid ACME email is required')
        if not re.fullmatch(r'[a-fA-F0-9]{64}', v.get('hy2_password', '')):
            raise ValueError('HY2 password must be 32 random bytes encoded as hex')
    else:
        if not v.get('uuid'):
            raise ValueError('UUID is required')
        if mode == 'reality':
            v['reality_sni'] = hostname(v.get('reality_sni', ''))
            dest = v.get('reality_dest', '')
            host, sep, port = dest.rpartition(':')
            if not sep or not port.isdigit() or not 1 <= int(port) <= 65535:
                raise ValueError('REALITY destination must be hostname:port')
            hostname(host)
            if not v.get('reality_private_key') or not re.fullmatch(r'[a-fA-F0-9]{2,16}', v.get('reality_short_id', '')) or len(v['reality_short_id']) % 2:
                raise ValueError('REALITY private key and an even-length hex short ID are required')
    return v


def render_configs(mode: str, values: dict) -> dict[str, str]:
    v = validate_values(mode, values)
    base = Path(__file__).resolve().parent.parent / 'config'
    if mode == 'hy2':
        cfg = json.loads((base / 'hysteria.json').read_text())
        cfg['acme']['domains'] = [v['domain']]
        cfg['acme']['email'] = v['email']
        cfg['auth']['password'] = v['hy2_password']
        return {'etc/hysteria/config.yaml': json.dumps(cfg, indent=2) + '\n'}
    cfg = json.loads((base / f'xray-{mode}.json').read_text())
    cfg['inbounds'][0]['settings']['clients'][0]['id'] = v['uuid']
    if mode == 'reality':
        r = cfg['inbounds'][0]['streamSettings']['realitySettings']
        r.update(target=v['reality_dest'], serverNames=[v['reality_sni']],
                 privateKey=v['reality_private_key'], shortIds=[v['reality_short_id']])
    files = {'usr/local/etc/xray/config.json': json.dumps(cfg, indent=2) + '\n'}
    if mode == 'ws':
        files['etc/caddy/Caddyfile'] = (base / 'Caddyfile').read_text().replace('__DOMAIN__', v['domain']).replace('__HTTPS_PORT__', '443')
    return files


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--mode', required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    try:
        for name, text in render_configs(args.mode, json.load(sys.stdin)).items():
            path = args.output_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            path.chmod(0o600)
    except (OSError, ValueError) as exc:
        p.exit(1, f'{exc}\n')

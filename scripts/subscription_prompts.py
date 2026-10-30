#!/usr/bin/env python3
"""Collect subscription options while writing only JSON to stdout."""
import json
import re
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo
from render_config import hostname
from traffic import quota_bytes, saved_quota_gb


def ask(prompt, default=''):
    print(prompt, end='', file=sys.stderr, flush=True)
    line = sys.stdin.readline()
    if not line:
        raise EOFError('Input canceled')
    return line.strip() or default


def collect(mode, node_domain, root=Path('/')):
    previous = {}
    file = root / 'etc/raystack/traffic.json'
    if file.exists():
        previous = json.loads(file.read_text())
    old = previous.get('traffic', {})
    if ask('Enable traffic subscription? [Y/n]: ', 'y').lower() in ('n', 'no'):
        return None
    domain = node_domain or previous.get('subscription_domain', previous.get('nodes', {}).get('domain', ''))
    while mode == 'reality':
        try:
            domain = hostname(ask(f'Subscription domain pointed to this VPS [{domain}]: ', domain))
            break
        except ValueError as exc:
            print(exc, file=sys.stderr)
    while True:
        default_quota = str(saved_quota_gb(old)) if old else ''
        quota = ask(f'Monthly quota (GB, 1024-based) [{default_quota}]: ', default_quota)
        try:
            quota_bytes(quota)
            break
        except ValueError:
            print('Enter a positive decimal number of GB.', file=sys.stderr)
    while True:
        default_day = str(old.get('reset_day', 1))
        day = ask(f'Monthly reset day [{default_day}]: ', default_day)
        if re.fullmatch(r'[1-9]|[12][0-9]|3[01]', day): break
        print('Enter a day from 1 to 31.', file=sys.stderr)
    while True:
        previous_zone = old.get('timezone', 'Asia/Shanghai')
        default_choice = {'Asia/Shanghai': '1', 'UTC': '2'}.get(previous_zone, '3')
        choice = ask(f'Timezone: 1) Beijing  2) UTC  3) Custom [{default_choice}]: ', default_choice)
        if choice not in ('1', '2', '3'): continue
        zone = {'1': 'Asia/Shanghai', '2': 'UTC'}.get(choice)
        if choice == '3': zone = ask(f'IANA timezone [{previous_zone}]: ', previous_zone)
        try:
            ZoneInfo(zone)
            break
        except (ValueError, KeyError):
            print('Unknown timezone.', file=sys.stderr)
    try:
        route = subprocess.check_output(['ip', '-4', 'route', 'show', 'default'], text=True, timeout=5)
        default = next((m.group(1) for line in route.splitlines() if (m := re.search(r'\bdev\s+(\S+)', line))), '')
    except (OSError, subprocess.SubprocessError): default = ''
    default = old.get('interface', default)
    while True:
        iface = ask(f'Public interface [{default}]: ', default)
        if re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', iface) and iface != 'lo': break
        print('Enter a valid interface name.', file=sys.stderr)
    while True:
        default_accounting = '2' if old.get('accounting') == 'both' else '1'
        choice = ask(f'Traffic: 1) outbound  2) inbound + outbound [{default_accounting}]: ', default_accounting)
        if choice in ('1', '2'): break
    return {'quota': quota, 'reset_day': day, 'timezone': zone, 'interface': iface,
            'accounting': 'outbound' if choice == '1' else 'both', 'subscription_domain': domain}


if __name__ == '__main__':
    try:
        print(json.dumps(collect(sys.argv[1], sys.argv[2])))
    except (EOFError, OSError, ValueError) as exc:
        print(f'Subscription input failed: {exc}', file=sys.stderr)
        sys.exit(1)

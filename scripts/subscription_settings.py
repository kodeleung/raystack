"""Validate and assemble private subscription settings."""
import ipaddress
import re
import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from render_config import hostname
from traffic import quota_bytes


def build_settings(mode, values, quota, reset_day, timezone, interface, accounting,
                   subscription_domain, previous=None):
    if mode not in ('ws', 'reality', 'hy2'):
        raise ValueError('unsupported proxy mode')
    if not re.fullmatch(r'[1-9]|[12][0-9]|3[01]', str(reset_day)):
        raise ValueError('reset day must be from 1 to 31')
    try:
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError('invalid timezone') from exc
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', interface) or interface == 'lo':
        raise ValueError('invalid network interface')
    if accounting not in ('outbound', 'both'):
        raise ValueError('invalid accounting mode')
    domain = hostname(subscription_domain)
    previous = previous or {}
    old = previous.get('traffic', {})
    if old and (old.get('timezone') != timezone or old.get('interface') != interface):
        raise ValueError('changing interface or timezone requires a new accounting database')
    node_address = values.get('domain') if mode != 'reality' else domain
    nodes = {'mode': mode, 'domain': values.get('domain') or domain,
             'node_address': node_address, 'https_port': 443}
    for name in ('uuid', 'reality_sni', 'reality_public_key', 'reality_short_id', 'hy2_password'):
        if name in values:
            nodes[name] = values[name]
    token = previous.get('token') or secrets.token_hex(32)
    if not re.fullmatch(r'[a-f0-9]{64}', token):
        raise ValueError('invalid stored subscription token')
    return {'token': token, 'traffic': {'quota_bytes': quota_bytes(quota),
             'reset_day': int(reset_day), 'timezone': timezone, 'interface': interface,
             'accounting': accounting}, 'nodes': nodes, 'subscription_domain': domain}

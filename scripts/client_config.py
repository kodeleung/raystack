"""Render a Clash subscription using JSON scalars, which are valid YAML."""
import json


def render_nodes(s):
    q = lambda x: json.dumps(x, ensure_ascii=True)
    lines = ['proxies:']
    if s['mode'] == 'hy2':
        lines += ['  - name: raystack-hy2', '    type: hysteria2', '    server: ' + q(s['domain']), '    port: 8443', '    password: ' + q(s['hy2_password']), '    sni: ' + q(s['domain']), '    skip-cert-verify: false']
    if s['mode'] in ('ws', 'both'):
        lines += ['  - name: raystack-ws', '    type: vless', '    server: ' + q(s['domain']), '    port: ' + str(s['https_port']), '    uuid: ' + q(s['uuid']), '    udp: true', '    tls: true', '    servername: ' + q(s['domain']), '    network: ws', '    ws-opts:', '      path: /ray', '    encryption: ""']
    if s['mode'] in ('reality', 'both'):
        lines += ['  - name: raystack-reality', '    type: vless', '    server: ' + q(s['node_address']), '    port: 8443', '    uuid: ' + q(s['uuid']), '    udp: true', '    flow: xtls-rprx-vision', '    tls: true', '    servername: ' + q(s['reality_sni']), '    client-fingerprint: chrome', '    network: tcp', '    reality-opts:', '      support-x25519mlkem768: true', '      public-key: ' + q(s['reality_public_key']), '      short-id: ' + q(s['reality_short_id']), '    encryption: ""']
    return '\n'.join(lines) + '\n'


# Routing policy follows the user's existing Clash Party profile.
ROUTING = (
    ('private', 'DIRECT'), ('reject', 'REJECT'), ('icloud', 'DIRECT'),
    ('apple', 'DIRECT'), ('google', 'PROXY'), ('gfw', 'PROXY'),
    ('greatfire', 'PROXY'), ('tld-not-cn', 'PROXY'), ('telegramcidr', 'PROXY'),
    ('direct', 'DIRECT'), ('cncidr', 'DIRECT'), ('lancidr', 'DIRECT'),
)


def render_profile(s, next_reset, timezone):
    names = []
    if s['mode'] == 'hy2': names.append('raystack-hy2')
    if s['mode'] in ('ws', 'both'): names.append('raystack-ws')
    if s['mode'] in ('reality', 'both'): names.append('raystack-reality')
    if not names:
        raise ValueError('Unsupported subscription mode')
    profile = '# Next reset (Unix timestamp): %d; timezone: %s\n' % (next_reset, json.dumps(timezone))
    profile += 'mode: rule\n' + render_nodes(s)
    profile += 'proxy-groups:\n  - name: PROXY\n    type: select\n    proxies:\n'
    profile += ''.join('      - ' + name + '\n' for name in names)
    profile += '  - name: FINAL\n    type: select\n    proxies:\n      - PROXY\n      - DIRECT\n'
    profile += 'rule-providers:\n'
    for name, _ in ROUTING:
        behavior = 'ipcidr' if name in ('telegramcidr', 'cncidr', 'lancidr') else 'domain'
        provider = {'type': 'http', 'behavior': behavior,
                    'url': 'https://cdn.jsdelivr.net/gh/Loyalsoldier/clash-rules@release/' + name + '.txt',
                    'path': './ruleset/' + name + '.yaml', 'interval': 86400}
        profile += '  ' + name + ':\n'
        profile += ''.join('    ' + key + ': ' + json.dumps(value) + '\n' for key, value in provider.items())
    profile += 'rules:\n'
    profile += ''.join('  - RULE-SET,' + name + ',' + target + '\n' for name, target in ROUTING)
    return profile + '  - MATCH,FINAL\n'

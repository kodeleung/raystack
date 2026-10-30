"""Render a Clash subscription using JSON scalars, which are valid YAML."""
import json


def render_nodes(s):
    q = lambda x: json.dumps(x, ensure_ascii=True)
    lines = ['proxies:']
    if s['mode'] in ('ws', 'both'):
        lines += ['  - name: raystack-ws', '    type: vless', '    server: ' + q(s['domain']), '    port: ' + str(s['https_port']), '    uuid: ' + q(s['uuid']), '    udp: true', '    tls: true', '    servername: ' + q(s['domain']), '    network: ws', '    ws-opts:', '      path: /ray', '    encryption: ""']
    if s['mode'] in ('reality', 'both'):
        lines += ['  - name: raystack-reality', '    type: vless', '    server: ' + q(s['node_address']), '    port: 443', '    uuid: ' + q(s['uuid']), '    udp: true', '    flow: xtls-rprx-vision', '    tls: true', '    servername: ' + q(s['reality_sni']), '    client-fingerprint: chrome', '    network: tcp', '    reality-opts:', '      support-x25519mlkem768: true', '      public-key: ' + q(s['reality_public_key']), '      short-id: ' + q(s['reality_short_id']), '    encryption: ""']
    return '\n'.join(lines) + '\n'


def render_profile(s, next_reset, timezone):
    names = []
    if s['mode'] in ('ws', 'both'): names.append('raystack-ws')
    if s['mode'] in ('reality', 'both'): names.append('raystack-reality')
    return ('# Next reset (Unix timestamp): %d; timezone: %s\n' % (next_reset, json.dumps(timezone)) + render_nodes(s) + 'proxy-groups:\n  - name: Proxy\n    type: select\n    proxies:\n' + ''.join('      - ' + n + '\n' for n in names) + '      - DIRECT\nrules:\n  - MATCH,Proxy\n')

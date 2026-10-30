#!/usr/bin/env python3
"""One securely configured Mihomo proxy, with quoted user-provided scalars."""
import json
import os


def print_client_config(mode: str, values: dict) -> str:
    v = values
    quote = json.dumps
    lines = ['----- BEGIN MIHOMO / CLASH META PROXIES -----',
             '# Paste this block into your Mihomo / Clash Meta configuration.', 'proxies:']
    if mode == 'hy2':
        lines += ['  - name: "raystack-hy2"', '    type: hysteria2',
                  '    server: ' + quote(v['domain']), '    port: 8443',
                  '    password: ' + quote(v['hy2_password']),
                  '    sni: ' + quote(v['domain']), '    skip-cert-verify: false']
    elif mode in ('ws', 'reality'):
        lines += ['  - name: ' + quote('raystack-' + mode), '    type: vless',
                  '    server: ' + quote(v['domain'] if mode == 'ws' else 'YOUR_SERVER_ADDRESS'),
                  '    port: ' + ('8443' if mode == 'reality' else '443'), '    uuid: ' + quote(v['uuid']), '    udp: true', '    tls: true']
        if mode == 'ws':
            lines += ['    servername: ' + quote(v['domain']), '    network: ws',
                      '    ws-opts:', '      path: "/ray"']
        else:
            lines += ['    flow: xtls-rprx-vision', '    servername: ' + quote(v['reality_sni']),
                      '    client-fingerprint: chrome', '    network: tcp', '    reality-opts:',
                      '      support-x25519mlkem768: true',
                      '      public-key: ' + quote(v['reality_public_key']),
                      '      short-id: ' + quote(v['reality_short_id'])]
    else:
        raise ValueError('Unsupported client mode: ' + mode)
    lines.append('----- END MIHOMO / CLASH META PROXIES -----')
    return '\n'.join(lines)


if __name__ == '__main__':
    names = {'domain': 'DOMAIN', 'uuid': 'UUID', 'reality_sni': 'REALITY_SNI',
             'reality_public_key': 'REALITY_PUBLIC_KEY', 'reality_short_id': 'REALITY_SHORT_ID',
             'hy2_password': 'HY2_PASSWORD'}
    print(print_client_config(os.environ['MODE'], {k: os.environ.get(v, '') for k, v in names.items()}))

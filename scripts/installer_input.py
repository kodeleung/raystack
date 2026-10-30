#!/usr/bin/env python3
"""Build installation values on stdout; no secret is placed in argv or logs."""
import base64
import json
import subprocess
import sys
import uuid
from pathlib import Path

from deployment_state import read, inspect_installation
from render_config import validate_values, hostname


def encode(data):
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def collect_values(mode, domain, email, reality_dest='swscan.apple.com:443', reality_sni='swscan.apple.com', root=Path('/')):
    # Reject unmanaged deployments before even preparing new credentials.
    inspect_installation(root)
    if mode in ('ws', 'hy2'):
        domain = hostname(domain)
    if mode == 'hy2':
        validate_values(mode, {'domain': domain, 'email': email, 'hy2_password': 'a' * 64})
    v = {'domain': domain, 'email': email, 'reality_dest': reality_dest, 'reality_sni': reality_sni}
    if mode == 'hy2':
        v['hy2_password'] = read(root, 'etc/raystack/hy2-password') or subprocess.check_output(['openssl', 'rand', '-hex', '32'], text=True).strip()
    else:
        v['uuid'] = read(root, 'etc/raystack/uuid') or str(uuid.uuid4())
        if mode == 'reality':
            private = read(root, 'etc/raystack/reality-private-key')
            if private:
                try:
                    raw = base64.urlsafe_b64decode(private + '=')
                except ValueError as exc:
                    raise ValueError('Stored REALITY private key is invalid') from exc
                if len(raw) != 32:
                    raise ValueError('Stored REALITY private key is invalid')
                der = bytes.fromhex('302e020100300506032b656e04220420') + raw
            else:
                der = subprocess.check_output(['openssl', 'genpkey', '-algorithm', 'X25519', '-outform', 'DER'])
                private = encode(der[-32:])
            public = subprocess.check_output(['openssl', 'pkey', '-inform', 'DER', '-pubout', '-outform', 'DER'], input=der)
            derived = encode(public[-32:])
            saved = read(root, 'etc/raystack/reality-public-key')
            if saved and saved != derived:
                raise ValueError('Stored REALITY public key does not match private key')
            v.update(reality_private_key=private, reality_public_key=derived,
                     reality_short_id=read(root, 'etc/raystack/reality-short-id') or subprocess.check_output(['openssl', 'rand', '-hex', '8'], text=True).strip())
    return validate_values(mode, v)


if __name__ == '__main__':
    try:
        print(json.dumps(collect_values(*sys.argv[1:])))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f'Input preparation failed: {exc}', file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""Prepare official release binaries without package hooks starting services."""
import argparse
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

BINARY = {'reality': '/usr/local/bin/xray', 'ws': '/usr/bin/caddy', 'hy2': '/usr/local/bin/hysteria'}
REPO = {'reality': 'XTLS/Xray-core', 'ws': 'caddyserver/caddy', 'hy2': 'apernet/hysteria'}


def capture(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=180)


def verify_version(mode, path):
    output = capture([str(path), 'version'])
    patterns = {'reality': r'(?m)^Xray \d', 'ws': r'^v?2\.', 'hy2': r'(?im)(?:version:\s*v?|hysteria\s+v?|^v?)2\.'}
    if not re.search(patterns[mode], output):
        raise RuntimeError(f'Incompatible {mode} binary at {path}')


def download_asset(mode, directory):
    machine = platform.machine()
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(machine)
    if not arch:
        raise RuntimeError(f'Unsupported server architecture: {machine}')
    release = json.loads(capture(['curl', '-fsSL', '--retry', '2', '--connect-timeout', '15', '--max-time', '120',
                                  f'https://api.github.com/repos/{REPO[mode]}/releases/latest']))
    patterns = {'reality': r'Xray-linux-' + ('64' if arch == 'amd64' else 'arm64-v8a') + r'\.zip',
                'ws': r'caddy_[0-9.]+_linux_' + arch + r'\.tar\.gz',
                'hy2': 'hysteria-linux-' + arch}
    assets = [a for a in release.get('assets', []) if re.fullmatch(patterns[mode], a['name'])]
    if len(assets) != 1 or not re.fullmatch(r'sha256:[0-9a-f]{64}', assets[0].get('digest') or ''):
        raise RuntimeError(f'No unique SHA-256 verified release asset for {mode}/{arch}')
    asset = assets[0]
    url = asset['browser_download_url']
    if not url.startswith(f'https://github.com/{REPO[mode]}/releases/download/'):
        raise RuntimeError('Unexpected release download URL')
    archive = directory / asset['name']
    subprocess.run(['curl', '-fsSL', '--retry', '2', '--connect-timeout', '15', '--max-time', '180',
                    '-o', str(archive), url], check=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != asset['digest'].split(':')[1]:
        raise RuntimeError('Release checksum mismatch')
    binary = directory / 'binary'
    if mode == 'reality':
        with zipfile.ZipFile(archive) as z:
            binary.write_bytes(z.read('xray'))
    elif mode == 'ws':
        with tarfile.open(archive) as t:
            member = t.extractfile('caddy')
            if member is None:
                raise RuntimeError('Caddy binary is missing from archive')
            binary.write_bytes(member.read())
    else:
        shutil.copyfile(archive, binary)
    binary.chmod(0o755)
    verify_version(mode, binary)
    return binary


def ensure_binary(mode):
    path = Path(BINARY[mode])
    if path.is_symlink():
        raise RuntimeError(f'Refusing to overwrite binary symlink: {path}')
    if path.exists():
        verify_version(mode, path)
        return
    print(f'[raystack] Downloading official {mode} runtime', flush=True)
    with tempfile.TemporaryDirectory(prefix='raystack-runtime-') as temp:
        binary = download_asset(mode, Path(temp))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.raystack-new')
        try:
            shutil.copyfile(binary, temporary)
            temporary.chmod(0o755)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def ensure_account(name):
    import pwd
    try:
        pwd.getpwnam(name)
    except KeyError:
        subprocess.run(['useradd', '--system', '--user-group', '--home-dir', f'/var/lib/{name}',
                        '--shell', '/usr/sbin/nologin', name], check=True)


def prepare_runtime(mode):
    if mode in ('ws', 'reality'):
        ensure_binary('reality')
        ensure_account('xray')
    if mode == 'ws':
        ensure_binary('ws')
        ensure_account('caddy')
    if mode == 'hy2':
        ensure_binary('hy2')
        ensure_account('hysteria')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['ws', 'reality', 'hy2'])
    args = p.parse_args()
    try:
        prepare_runtime(args.mode)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        p.exit(1, f'Runtime preparation failed: {exc}\n')

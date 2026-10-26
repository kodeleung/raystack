"""Run inside the disposable Linux container launched by test_hy2_runtime.sh."""
import functools
import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from render_config import render_configs
from runtime_install import download_asset


def wait_port(port, process):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError('Proxy exited before accepting connections')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError('Proxy readiness timeout')


with tempfile.TemporaryDirectory() as name:
    root = Path(name)
    binary = download_asset('hy2', root)
    subprocess.run([str(binary), 'server', '--help'], check=True, stdout=subprocess.DEVNULL)
    cert, key = root / 'cert.pem', root / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
                    '-keyout', str(key), '-out', str(cert)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cfg = json.loads(render_configs('hy2', {'domain': 'localhost.example', 'email': 'test@example.com',
                                          'hy2_password': 'a' * 64})['etc/hysteria/config.yaml'])
    del cfg['acme']
    cfg.update(listen='127.0.0.1:24443', tls={'cert': str(cert), 'key': str(key)})
    # The production filename deliberately remains .yaml to verify JSON-as-YAML support.
    server_file = root / 'server.yaml'
    server_file.write_text(json.dumps(cfg))
    (root / 'payload').write_text('hy2 authenticated roundtrip\n')
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    target = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=target.serve_forever, daemon=True).start()
    processes = []
    logs = []
    try:
        server_log = open(root / 'server.log', 'w')
        logs.append(server_log)
        server = subprocess.Popen([str(binary), 'server', '--config', str(server_file)], stdout=server_log, stderr=server_log)
        processes.append(server)
        time.sleep(0.5)
        for password, port, valid in [('a' * 64, 28080, True), ('b' * 64, 28081, False)]:
            client_file = root / f'client-{port}.json'
            client_file.write_text(json.dumps({'server': '127.0.0.1:24443', 'auth': password,
                                               'tls': {'sni': 'localhost', 'ca': str(cert), 'insecure': False},
                                               'http': {'listen': f'127.0.0.1:{port}'}}))
            client_log = open(root / f'client-{port}.log', 'w')
            logs.append(client_log)
            client = subprocess.Popen([str(binary), 'client', '--config', str(client_file)], stdout=client_log, stderr=client_log)
            processes.append(client)
            if valid:
                wait_port(port, client)
                response = subprocess.check_output(['curl', '-fsS', '--max-time', '10', '--noproxy', '',
                                                    '--proxy', f'http://127.0.0.1:{port}',
                                                    f'http://127.0.0.1:{target.server_port}/payload'], text=True)
                assert response == 'hy2 authenticated roundtrip\n', response
            else:
                client.wait(timeout=15)
                assert client.returncode != 0, 'Wrong password was accepted'
                assert 'auth' in (root / f'client-{port}.log').read_text().lower()
        print('PASS: real HY2 trusted-TLS roundtrip and wrong-password rejection; JSON in .yaml accepted')
    except BaseException:
        for path in root.glob('*.log'):
            print(path.name, path.read_text()[-2500:], file=sys.stderr)
        raise
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        for log in logs:
            log.close()
        target.shutdown()

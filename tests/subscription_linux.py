"""Actual Linux vnStat initialization, Caddy parsing and Python HTTP smoke test."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from subscription_deployment import caddy_config

with tempfile.TemporaryDirectory() as temp:
    temp = Path(temp)
    base = Path('config/Caddyfile').read_text().replace('__DOMAIN__', 'test.example.com').replace('__HTTPS_PORT__', '443')
    for mode in ('ws', 'reality', 'hy2'):
        file = temp / (mode + '.Caddyfile')
        file.write_text(caddy_config(mode, 'test.example.com', base))
        subprocess.run(['caddy', 'validate', '--config', str(file), '--adapter', 'caddyfile'], check=True)
    db = temp / 'db'
    db.mkdir()
    cfg = temp / 'vnstat.conf'
    cfg.write_text(f'DatabaseDir "{db}"\nDailyDays 400\nPidFile "{temp}/vnstat.pid"\nTrafficlessEntries 1\n')
    env = dict(os.environ, TZ='Asia/Shanghai')
    subprocess.run(['vnstatd', '--config', str(cfg), '--initdb', '--noadd'], env=env, check=True)
    subprocess.run(['vnstat', '--config', str(cfg), '--add', '-i', 'eth0'], env=env, check=True)
    daemon = subprocess.Popen(['vnstatd', '--config', str(cfg), '--nodaemon'], env=env)
    try:
        import time
        time.sleep(2)
        assert daemon.poll() is None
    finally:
        daemon.terminate()
        daemon.wait(timeout=10)
    data = json.loads(subprocess.check_output(['vnstat', '--config', str(cfg), '--json', 'd', '0', '-i', 'eth0'], env=env))
    assert data['interfaces'][0]['name'] == 'eth0'
subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_subscription*.py'], check=True)
print('Linux subscription smoke test passed')

# Verify Caddy HTTPS routing and HY2 challenge forwarding with a local test CA.
import http.client
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
from subscription_server import make_server
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_render_config import values

class Challenge(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'challenge-response')
    def log_message(self, *args): pass

challenge = HTTPServer(('127.0.0.1', 8888), Challenge)
backend = make_server({'timezone': 'UTC'}, dict(values(), mode='hy2', https_port=443), 'synthetic-token')
threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (backend, challenge)]
for t in threads: t.start()
try:
    with tempfile.TemporaryDirectory() as temp, patch('subscription_server.query_usage', return_value={'upload': 1, 'download': 2, 'total': 100, 'next_reset': 1}):
        cfg = caddy_config('hy2', 'test.example.com')
        cfg = cfg.replace('  admin off', '  admin off\n  skip_install_trust')
        cfg = cfg.replace('  tls {\n    issuer acme {\n      disable_tlsalpn_challenge\n    }\n  }', '  tls internal')
        file = Path(temp) / 'Caddyfile'
        file.write_text(cfg)
        process = subprocess.Popen(['caddy', 'run', '--config', str(file), '--adapter', 'caddyfile'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            import time
            for attempt in range(50):
                try:
                    with socket.create_connection(('127.0.0.1', 9443), timeout=2) as raw:
                        with ssl._create_unverified_context().wrap_socket(raw, server_hostname='test.example.com') as tls:
                            tls.sendall(b'GET /subscription/synthetic-token HTTP/1.1\r\nHost: test.example.com\r\nConnection: close\r\n\r\n')
                            response = http.client.HTTPResponse(tls); response.begin()
                            assert response.status == 200
                            assert response.getheader('Subscription-Userinfo') == 'upload=1; download=2; total=100'
                            assert b'hysteria2' in response.read()
                    break
                except OSError:
                    time.sleep(.1)
            else: raise AssertionError('Caddy HTTPS route not ready')
            connection = http.client.HTTPConnection('127.0.0.1', 80)
            connection.request('GET', '/.well-known/acme-challenge/test', headers={'Host': 'test.example.com'})
            response = connection.getresponse()
            assert response.status == 200 and response.read() == b'challenge-response'
            connection.close()
        finally:
            process.terminate(); process.wait(timeout=10)
finally:
    for server in (backend, challenge): server.shutdown(); server.server_close()
    for thread in threads: thread.join()
print('Caddy HTTPS subscription route and HY2 ACME forwarding passed')

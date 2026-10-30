"""Local-only subscription endpoint. Caddy provides TLS."""
import hmac
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from client_config import render_profile
from traffic import query_usage, StatisticsUnavailable


def make_server(settings, nodes, token, host='127.0.0.1', port=8765):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass

        def respond(self, head=False):
            expected = '/subscription/' + token
            if not hmac.compare_digest(self.path.encode(), expected.encode()):
                self.send_error(404)
                return
            try:
                usage = query_usage(settings, datetime.now(timezone.utc))
                body = render_profile(nodes, usage['next_reset'], settings['timezone']).encode()
            except (StatisticsUnavailable, ValueError, KeyError):
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/yaml; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="raystack.yaml"')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Profile-Update-Interval', '1')
            self.send_header('Subscription-Userinfo', 'upload={upload}; download={download}; total={total}'.format(**usage))
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            if not head:
                self.wfile.write(body)
        def do_GET(self): self.respond()
        def do_HEAD(self): self.respond(True)
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server

if __name__ == '__main__':
    with open(sys.argv[1], encoding='utf-8') as file:
        config = json.load(file)
    make_server(config['traffic'], config['nodes'], config['token']).serve_forever()

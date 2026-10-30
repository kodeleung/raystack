"""Subscription resources participating in the proxy deployment transaction."""
import json
import shutil
import subprocess
from pathlib import Path
from subscription_settings import build_settings

SERVICES = ['raystack-vnstat.service', 'raystack-subscription.service']
PATHS = ['etc/raystack/traffic.json', 'etc/raystack/vnstat.conf'] + ['etc/systemd/system/' + s for s in SERVICES]
ROUTE = '  handle /subscription/* {\n    reverse_proxy 127.0.0.1:8765\n  }\n\n'


def legacy_caddy_config(mode, domain, base=None):
    if mode == 'ws':
        return base.replace('  handle /ray* {', ROUTE + '  handle /ray* {')
    return '''{
  admin off
  https_port 8443
  servers {
    protocols h1 h2
  }
}
%s {
  tls {
    issuer acme {
      disable_tlsalpn_challenge
    }
  }
%s  handle {
    respond "OK"
  }
}
''' % (domain, ROUTE) + ('\nhttp://%s {\n  handle /.well-known/acme-challenge/* {\n    reverse_proxy 127.0.0.1:8888\n  }\n}\n' % domain if mode == 'hy2' else '')


def caddy_config(mode, domain, base=None):
    global_options = '{\n  admin off\n  servers {\n    protocols h1 h2\n  }\n}\n'
    main_site = ''
    if mode == 'ws':
        # The WS site keeps standard HTTPS; only subscriptions use TCP 9443.
        import re
        main_site = re.sub(r'^\s*\{\s*https_port 443\s*\}\s*', '', base, count=1)
    tls = '' if mode == 'ws' else '  tls {\n    issuer acme {\n      disable_tlsalpn_challenge\n    }\n  }\n'
    site = '%s:9443 {\n%s%s  handle {\n    respond "OK"\n  }\n}\n' % (domain, tls, ROUTE)
    challenge = ('\nhttp://%s {\n  handle /.well-known/acme-challenge/* {\n    reverse_proxy 127.0.0.1:8888\n  }\n}\n' % domain if mode == 'hy2' else '')
    return global_options + main_site + site + challenge


def prepare_dependencies():
    if not shutil.which('vnstat'):
        if shutil.which('apt-get'):
            subprocess.run(['apt-get', 'update', '-y'], check=True)
            cmd = ['apt-get', 'install', '-y', 'vnstat', 'tzdata']
        elif shutil.which('dnf'):
            cmd = ['dnf', 'install', '-y', 'vnstat', 'tzdata']
        elif shutil.which('yum'):
            cmd = ['yum', 'install', '-y', 'vnstat', 'tzdata']
        else:
            raise RuntimeError('Install vnStat 2.x and tzdata before enabling subscriptions')
        subprocess.run(cmd, check=True)
    version = subprocess.check_output(['vnstat', '--version'], text=True, timeout=10)
    if not version.startswith('vnStat 2.'):
        raise ValueError('vnStat 2.x is required')


def resources(root, mode, values, options):
    from deployment_state import read
    previous = read(root, 'etc/raystack/traffic.json')
    config = build_settings(mode, values, previous=json.loads(previous) if previous else None, **options)
    if root == Path('/') and not Path('/sys/class/net', config['traffic']['interface']).exists():
        raise ValueError('Selected network interface does not exist')
    zone = config['traffic']['timezone']
    files = {'etc/raystack/traffic.json': json.dumps(config),
             'etc/raystack/vnstat.conf': 'DatabaseDir "/var/lib/raystack/vnstat"\nDailyDays 400\nPidFile "/run/raystack-vnstat.pid"\nTrafficlessEntries 1\nSaveInterval 1\n'}
    files['etc/systemd/system/raystack-vnstat.service'] = '''# Managed by raystack
[Unit]
Description=Raystack traffic accounting
After=network.target
[Service]
Group=raystack
UMask=0007
Environment=TZ=%s
ExecStart=%s --nodaemon --config /etc/raystack/vnstat.conf
Restart=on-failure
[Install]
WantedBy=multi-user.target
''' % (zone, shutil.which('vnstatd') or '/usr/sbin/vnstatd')
    files['etc/systemd/system/raystack-subscription.service'] = '''# Managed by raystack
[Unit]
Description=Raystack subscription endpoint
After=network.target raystack-vnstat.service
[Service]
User=raystack
Group=raystack
ExecStart=/usr/bin/python3 /usr/local/lib/raystack/subscription_server.py /etc/raystack/traffic.json
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
[Install]
WantedBy=multi-user.target
'''
    return config, files


def initialize(config):
    import os
    env = dict(os.environ, TZ=config['traffic']['timezone'])
    db = Path('/var/lib/raystack/vnstat')
    db.mkdir(parents=True, exist_ok=True, mode=0o700)
    import grp
    gid = grp.getgrnam('raystack').gr_gid
    for directory in (Path('/etc/raystack'), db):
        os.chown(directory, 0, gid)
        directory.chmod(0o2750)
    for name in ('traffic.json', 'vnstat.conf'):
        file = Path('/etc/raystack') / name
        os.chown(file, 0, gid)
        file.chmod(0o640)
    cfg = '/etc/raystack/vnstat.conf'
    if not (db / 'vnstat.db').exists():
        subprocess.run(['vnstatd', '--config', cfg, '--initdb', '--noadd'], env=env, check=True)
    interfaces = subprocess.check_output(['vnstat', '--config', cfg, '--dbiflist', '1'], env=env, text=True).splitlines()
    iface = config['traffic']['interface']
    if iface not in interfaces:
        subprocess.run(['vnstat', '--config', cfg, '--add', '-i', iface], env=env, check=True)
    for file in db.iterdir():
        if file.is_file():
            os.chown(file, 0, gid)
            file.chmod(0o640)
    dest = Path('/usr/local/lib/raystack')
    dest.mkdir(parents=True, exist_ok=True)
    for name in ('traffic.py', 'client_config.py', 'subscription_server.py'):
        shutil.copyfile(Path(__file__).parent / name, dest / name)
        (dest / name).chmod(0o644)


def url(config):
    port = ':9443'
    return 'https://' + config['subscription_domain'] + port + '/subscription/' + config['token']


def wait_https(config, timeout=120):
    """Verify the local TLS endpoint with its public hostname and trusted certificate."""
    import http.client
    import socket
    import ssl
    import time
    deadline = time.monotonic() + timeout
    host = config['subscription_domain']
    port = 9443
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=3) as raw:
                with ssl.create_default_context().wrap_socket(raw, server_hostname=host) as sock:
                    request = 'GET /subscription/%s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n' % (config['token'], host)
                    sock.sendall(request.encode('ascii'))
                    response = http.client.HTTPResponse(sock)
                    response.begin()
                    if response.status == 200 and response.getheader('Subscription-Userinfo'):
                        return
        except (OSError, ssl.SSLError, http.client.HTTPException):
            pass
        time.sleep(2)
    raise RuntimeError('Subscription HTTPS is not ready: verify DNS, TCP 80 and the HTTPS port, then inspect Caddy/subscription journals')

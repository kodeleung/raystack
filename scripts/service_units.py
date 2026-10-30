"""Fail-closed recognition of supported systemd units and inherited drop-ins."""
import os

COMMANDS = {'xray.service': '/usr/local/bin/xray run -config /usr/local/etc/xray/config.json',
            'caddy.service': '/usr/bin/caddy run --environ --config /etc/caddy/Caddyfile',
            'hysteria-server.service': '/usr/local/bin/hysteria server --config /etc/hysteria/config.yaml'}


def parse_unit(text):
    result = {}
    section = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.endswith('\\'):
            raise ValueError('Unsupported continued systemd directive')
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
            if section not in ('Unit', 'Service', 'Install'):
                raise ValueError('Unmanaged systemd section')
        elif section and '=' in line:
            key, value = (v.strip() for v in line.split('=', 1))
            result.setdefault((section, key), []).append(value)
        else:
            raise ValueError('Unrecognized systemd syntax')
    return result


def validate_fragment(text, service):
    directives = parse_unit(text)
    user = {'xray.service': 'xray', 'caddy.service': 'caddy', 'hysteria-server.service': 'hysteria'}[service]
    allowed = {
        ('Unit', 'After'): {'network.target nss-lookup.target', 'network.target network-online.target', 'network-online.target'},
        ('Unit', 'Wants'): {'network-online.target'},
        ('Unit', 'Requires'): {'network-online.target'},
        ('Service', 'Type'): {'simple', 'notify'},
        ('Service', 'User'): {user} | ({'nobody'} if user == 'xray' else set()),
        ('Service', 'Group'): {user} | ({'nogroup', 'nobody'} if user == 'xray' else set()),
        ('Service', 'ExecStart'): {COMMANDS[service]},
        ('Service', 'Restart'): {'on-failure'},
        ('Service', 'RestartSec'): {'5', '5s'},
        ('Service', 'RestartPreventExitStatus'): {'23'},
        ('Service', 'NoNewPrivileges'): {'yes', 'true'},
        ('Service', 'UMask'): {'0077'},
        ('Service', 'LimitNOFILE'): {'1048576', '1000000'},
        ('Service', 'LimitNPROC'): {'500', '512', '10000'},
        ('Service', 'RuntimeDirectory'): {user},
        ('Service', 'RuntimeDirectoryMode'): {'0755'},
        ('Service', 'StateDirectory'): {user},
        ('Service', 'WorkingDirectory'): {'/var/lib/' + user},
        ('Service', 'TimeoutStopSec'): {'5', '5s'},
        ('Service', 'PrivateTmp'): {'true', 'yes'},
        ('Service', 'ProtectSystem'): {'full', 'strict'},
        ('Service', 'ProtectHome'): {'true', 'yes'},
        ('Install', 'WantedBy'): {'multi-user.target'},
    }
    if service == 'caddy.service':
        allowed[('Service', 'ExecStart')].add(COMMANDS[service] + ' --adapter caddyfile')
        allowed[('Service', 'ExecReload')] = {
            '/usr/bin/caddy reload --config /etc/caddy/Caddyfile --force',
            '/usr/bin/caddy reload --config /etc/caddy/Caddyfile --force --adapter caddyfile'}
        allowed[('Service', 'Environment')] = {
            'XDG_DATA_HOME=/var/lib/caddy/.local/share', 'XDG_CONFIG_HOME=/var/lib/caddy/.config'}
    for key, values in directives.items():
        if key in (('Unit', 'Description'), ('Unit', 'Documentation')):
            continue  # Descriptive text has no execution or service-state effect.
        if key in (('Service', 'CapabilityBoundingSet'), ('Service', 'AmbientCapabilities')):
            if all(set(v.split()) <= {'CAP_NET_BIND_SERVICE', 'CAP_NET_ADMIN', 'CAP_NET_RAW'} for v in values):
                continue
        if key not in allowed or any(v not in allowed[key] for v in values):
            raise ValueError(f'Unmanaged systemd directive: {key[0]}.{key[1]}')
        if len(values) > 1 and key != ('Service', 'Environment'):
            raise ValueError('Ambiguous repeated systemd directive')
    if directives.get(('Service', 'ExecStart')) not in ([COMMANDS[service]],
            [COMMANDS[service] + ' --adapter caddyfile'] if service == 'caddy.service' else []):
        raise ValueError('Service has no recognized ExecStart')


def validate_service(root, service, safe_path):
    bases = ['usr/lib/systemd/system', 'lib/systemd/system', 'usr/local/lib/systemd/system',
             'run/systemd/system', 'etc/systemd/system']
    if (root / 'lib').is_symlink() and os.readlink(root / 'lib') not in ('usr/lib', '/usr/lib'):
        raise ValueError('Unrecognized /lib symlink')
    bases = [b for b in bases if not (b.startswith('lib/') and (root / 'lib').is_symlink())]
    fragment = None
    for base in bases:
        path = safe_path(root, base + '/' + service)
        if path.exists():
            fragment = path
    # Transient/property overrides cannot be safely discarded or reconstructed.
    for base in ('run/systemd/transient', 'run/systemd/system.control', 'etc/systemd/system.control',
                 'run/systemd/generator', 'run/systemd/generator.early', 'run/systemd/generator.late'):
        if safe_path(root, base + '/' + service).exists() or safe_path(root, base + '/' + service + '.d').exists():
            raise ValueError('Unmanaged transient or property-controlled service')
    directories = ['service.d', service + '.d']
    stem = service.removesuffix('.service')
    directories += [stem[:i + 1] + '.service.d' for i, ch in enumerate(stem) if ch == '-']
    for base in bases:
        for directory in directories:
            path = safe_path(root, base + '/' + directory)
            if not path.exists():
                continue
            for item in path.iterdir():
                safe_path(root, str(item.relative_to(root)))
                # Only the known Xray upstream reset drop-in is owned by this stack.
                if service == 'xray.service' and directory == service + '.d' and item.name == '10-donot_touch_single_conf.conf':
                    expected = {('Service', 'ExecStart'): ['', COMMANDS[service]]}
                    if item.is_file() and parse_unit(item.read_text()) == expected:
                        continue
                raise ValueError(f'Unmanaged inherited service override: {item.relative_to(root)}')
    if fragment is not None:
        validate_fragment(fragment.read_text(), service)

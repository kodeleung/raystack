# raystack

An interactive Linux installer for **one proxy mode at a time**:

1. **VLESS + WebSocket + TLS** — Xray behind Caddy, with automatic HTTPS.
2. **VLESS + TCP + REALITY** — Xray with Vision, without a domain or certificate requirement.
3. **Hysteria 2** — QUIC over UDP, with its own automatic certificate management.

The entry point is Bash. Python 3 handles configuration serialization, installation
recognition, backups, and service changes using only its standard library.

## Requirements

- Linux with systemd, root access (or sudo), and an amd64 or arm64 CPU.
- `python3`, `curl`, `openssl`, `systemctl`, `ss`, `flock`, and `useradd`.
- Outbound HTTPS access to GitHub releases and its API. Official release downloads
  are checked against the SHA-256 digest published in GitHub release metadata.
- For WS/HY2: a domain pointed directly at the server. Use Cloudflare **DNS only**
  (grey cloud). Publish an AAAA record only if server IPv6 works.
- For HY2: an email for ACME certificate management.

On a minimal Debian/Ubuntu installation, install missing prerequisites with:

```bash
sudo apt-get update
sudo apt-get install -y python3 curl openssl ca-certificates iproute2 util-linux passwd
```

## Install

```bash
sudo bash ./install.sh
```

Choose exactly one mode. HY2 prompts for your domain and email, generates a random
password, and obtains/renews a Let's Encrypt certificate itself; Caddy is only
used by WS. Required public inbound access:

| Mode | Ports |
| --- | --- |
| WS + TLS | TCP 80 and TCP 443 |
| REALITY | TCP 443 |
| HY2 | UDP 443 and TCP 80 |

For HY2, TCP 80 must remain available for certificate renewal. Open these ports
both on the server firewall and in your provider's security group. The installer
checks local conflicts but does not change either firewall.

## Reinstall and switch modes

Reinstalling the same mode reuses its saved UUID, REALITY keys, or HY2 password.
Selecting a different mode **automatically removes the old raystack mode and
installs the new one**, without an additional confirmation. This briefly
interrupts existing connections. Previous combined WS + REALITY installations
are recognized and can be replaced with one selected mode.

Before switching, raystack checks ownership and ports, prepares the new runtime,
and validates staged configuration. It saves the old configurations, service
units/drop-ins, and service enabled/running states under:

```text
/etc/raystack/backups/<UTC timestamp>-<random suffix>/snapshot.json
```

Backups are root-only and contain secrets. If activation fails or times out,
raystack attempts to restore the old files and service states. A rollback failure
is reported with the backup location. Keep backups private; they are not
compressed archives and should not be shared.

Only recognized raystack deployments are automatically replaced. Custom Xray
inbounds, unrelated Caddy sites, unknown service overrides, inconsistent mode
markers, and unrelated processes occupying required ports cause a diagnostic
instead of being overwritten. If an earlier run was forcibly killed, resolve
any reported inconsistent state before retrying. There is no standalone
uninstaller in this version.

Old services are stopped and disabled and their recognized active configuration
and local units are removed. Shared packages/binaries, credentials, Caddy
certificate storage, and HY2 ACME state are retained; they do not create another
active proxy mode. The installer does not purge unrelated packages or sites.

A successful installation means the selected service is running and owns the
expected listening socket. It does not prove that a provider firewall permits
public traffic. Real ACME issuance depends on DNS and inbound reachability.

## Clash / Mihomo configuration

The installer prints one `MIHOMO / CLASH META PROXIES` block. Copy its `proxies:`
section into your client configuration. REALITY includes
`support-x25519mlkem768: true`; replace `YOUR_SERVER_ADDRESS` with the VPS address.
HY2 uses the supplied domain as its server/SNI and keeps certificate verification
on (`skip-cert-verify: false`). No optional HY2 obfuscation, port hopping, or
bandwidth tuning is enabled.

## Runtime files and defaults

| Purpose | Path / value |
| --- | --- |
| Successful selected mode | `/etc/raystack/mode` |
| UUID | `/etc/raystack/uuid` |
| REALITY keys / short ID | `/etc/raystack/reality-{private-key,public-key,short-id}` |
| HY2 password (0600) | `/etc/raystack/hy2-password` |
| Xray configuration | `/usr/local/etc/xray/config.json` |
| Caddy configuration | `/etc/caddy/Caddyfile` |
| HY2 configuration (JSON, valid YAML) | `/etc/hysteria/config.yaml` |
| HY2 certificate/ACME state | `/var/lib/hysteria/acme` |
| WS internal listener/path | `127.0.0.1:10000`, `/ray` |
| REALITY destination / SNI | `swscan.apple.com:443` / `swscan.apple.com` |

Selected services: `xray.service` for REALITY, `xray.service` and `caddy.service`
for WS, or `hysteria-server.service` for HY2. To inspect HY2 failures:

```bash
systemctl status hysteria-server.service
journalctl -u hysteria-server.service -n 80 --no-pager
```

HY2 configuration has JSON syntax so no YAML parsing package is needed. Xray
outbounds continue to use `ForceIPv4`; HY2 uses its default address selection.
The installer does not change system DNS.

## Development

- `install.sh`: interactive selection and input; credentials flow through stdin.
- `scripts/installer_input.py`: validation and credential generation/reuse.
- `scripts/render_config.py`: staged configuration generation.
- `scripts/deployment_state.py`: legacy and current installation recognition.
- `scripts/runtime_install.py`: official binary preparation without starting services.
- `scripts/deployment.py`: locking, backups, mode replacement, readiness, rollback.
- `scripts/print_client_config.py`: one client proxy per selected mode.
- `config/`: single-mode templates only.

`generate_config.sh --mode <ws|reality|hy2> --output-dir DIR` now renders staged
files from JSON on stdin. It no longer writes live `/etc` configurations directly;
use the interactive installer for activation and rollback protection.

Run safe local tests (temporary roots and fake services; no host service changes):

```bash
bash tests/run.sh
```

Opt in to a real HY2 server/client smoke test in a disposable Linux container:

```bash
RAYSTACK_RUNTIME_TEST=1 bash tests/test_hy2_runtime.sh
```

The container publishes no host ports, mounts this repository read-only, and
checks trusted test-certificate traffic and wrong-password rejection. It does
not test public ACME issuance, cloud firewalls, or production domain connectivity.

## Experimental traffic subscription

The earlier traffic subscription prototype is retained in `scripts/traffic.py`,
`scripts/client_config.py`, `scripts/subscription_server.py`, and
`scripts/install_traffic.sh`. It is not integrated with the exclusive-mode
installer and should not be deployed. The prototype needs integration with mode
switching and rollback, HY2 support, and Linux runtime validation before use.
Existing installations using its modified Caddy configuration may be rejected by
the installer's ownership checks; inspect the deployment before changing modes.

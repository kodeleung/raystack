# raystack

An interactive Linux installer with three managed proxy modes and a 3x-ui installation option:

1. **VLESS + WebSocket + TLS** — Xray behind Caddy, with automatic HTTPS.
2. **VLESS + TCP + REALITY** — Xray with Vision, without a domain or certificate requirement.
3. **Hysteria 2** — QUIC over UDP, with its own automatic certificate management.
4. **3x-ui panel** — runs the upstream official installer; manage protocols, users,
   traffic limits, and subscriptions in its web panel afterward.

The entry point is Bash. Python 3 handles configuration serialization, installation
recognition, backups, and service changes using only its standard library.

## Requirements

The requirements below apply to managed modes 1–3. Option 4 requires Linux with
systemd, root access (or sudo), and `curl`; the official 3x-ui installer handles
its own supported platforms and dependencies.

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

Choose an option. **Option 4** downloads and runs the
[official 3x-ui installer](https://github.com/MHSanaei/3x-ui), preserving its
interactive setup. It skips raystack's node and traffic-subscription setup.
Existing raystack services and configurations remain in place: avoid occupied
ports when creating nodes in the panel. This option does not migrate existing
nodes or participate in raystack's backup/rollback and mode-switching mechanism.
For subsequent panel management, use the upstream `x-ui` command.

For modes 1–3, raystack manages one proxy mode at a time. HY2 prompts for your domain and email, generates a random
password, and obtains/renews a Let's Encrypt certificate itself; Caddy is only
used by WS. Required public inbound access:

| Mode | Ports |
| --- | --- |
| WS + TLS | TCP 80 and TCP 443 |
| REALITY | TCP 8443 |
| HY2 | UDP 8443 and TCP 80 |

For HY2, TCP 80 must remain available for certificate renewal. Open these ports
both on the server firewall and in your provider's security group. The installer
checks local conflicts but does not change either firewall.

## Reinstall and switch modes

This section applies to managed modes 1–3.

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
| REALITY destination / SNI | `www.bing.com:443` / `www.bing.com` |

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

## Traffic subscription

The installer asks whether to enable the subscription (default yes), then asks
for monthly quota in **GB**, reset day (1–31), billing timezone (Beijing, UTC,
or a custom IANA name), public network interface, and outbound-only or
bidirectional accounting. One displayed GB is 1,073,741,824 bytes (1024³, technically GiB), matching
Clash Party. Legacy decimal quotas retain the original entered amount when
converted; usage counters are never multiplied or reset. Python 3.9 or newer and
system timezone data are required. vnStat 2.x is installed when needed.

For REALITY, enter a subscription domain pointing directly to the VPS; it is
also used as the node address. WS and HY2 reuse their node domain. Installation
prints a private **Subscription URL** for import as a remote configuration in
Clash Party. It contains credentials; keep it secret. Refresh the subscription
to refresh usage; the suggested refresh interval is one hour. Fresh statistics
may take about a minute to become available; retry import after initialization.

- All subscription modes: `https://your-domain:9443/subscription/<token>` (TCP 9443).
- REALITY data uses TCP 8443; WS data uses TCP 443; HY2 data uses UDP 8443.
- Caddy keeps its standard HTTPS default; the subscription site explicitly uses 9443.
- When upgrading older installs, open the new ports first, reinstall, then replace the saved
  client subscription URL with the newly printed 9443 URL. Older REALITY data used 443 and subscriptions used 443/8443.
- Enable inbound TCP 80 for automatic certificates, plus the subscription port.
  DNS must point directly to this server with no broken AAAA record.
- Enabling subscriptions uses a raystack-managed Caddy service in every mode.
  It refuses to take over unrelated services or occupied subscription ports.
  With subscriptions disabled, REALITY/HY2 do not require a Caddy configuration.
- HY2 HTTP-01 validation is forwarded by Caddy to its local ACME listener on
  port 8888, including certificate renewal. UDP 8443 remains the HY2 data port.

The new cycle starts at midnight in the selected billing timezone without
changing the VPS system timezone or deleting statistics. Missing days 29–31
are clamped to the end of that month. Quota is informational: exceeding it does
not stop the proxy. Accounting counts the whole selected network interface,
including other VPS services. Provider totals can differ. Only traffic observed
since activation is counted; earlier monthly usage is not reconstructed.

Quota, accounting and reset-day changes reuse retained statistics. Reinstalling
or switching proxy modes preserves the token and database and updates the
subscription nodes. Changing the interface/timezone is rejected to avoid mixing
incompatible historical records. Disabling the feature stops its services and
retains private settings and statistics for later re-enabling.

Runtime settings are private in `/etc/raystack/traffic.json`; statistics live in
`/var/lib/raystack/vnstat`. Services are `raystack-vnstat.service` and
`raystack-subscription.service`, alongside the applicable proxy/Caddy services.
Configuration and service changes participate in the installer backup/rollback.
Database samples and downloaded binaries are retained across rollback.

Run the disposable Linux subscription smoke test (no published host ports or
production certificate requests):

```bash
RAYSTACK_SUBSCRIPTION_RUNTIME_TEST=1 bash tests/test_subscription_linux.sh
```

Containers are removed automatically. Public DNS, ACME issuance and a real
Clash Party import still require verification on the target VPS.

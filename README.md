# raystack

`raystack` is a simple bash-based CLI project for deploying a VPS proxy stack with:

- Xray (`VLESS + WebSocket + TLS` and `VLESS + TCP + REALITY`)
- Caddy (automatic HTTPS, when WebSocket mode is selected)
- systemd service management

## Features

- Bash only
- Simple project structure
- Idempotent install flow
- Interactive mode selection
- Generate or reuse UUID and REALITY credentials
- Generate mode-specific Xray and Caddy config files
- Enable and start services with `systemd`

## Project Structure

```text
raystack/
├── install.sh
├── config/
│   ├── xray-ws.json
│   ├── xray-reality.json
│   ├── xray-both.json
│   └── Caddyfile
└── scripts/
    ├── install_xray.sh
    ├── install_caddy.sh
    └── generate_config.sh
```

## Requirements

- A Linux VPS with `systemd`
- Root access or `sudo`
- A domain name already pointed to the VPS

## Usage

Run the installer:

```bash
./install.sh
```

Choose one of the prompts:

1. `VLESS + WebSocket + TLS` — enter the domain to use.
2. `VLESS + TCP + REALITY` — confirm or override the displayed REALITY destination and SNI.
3. Both modes — enter a WebSocket domain and confirm or override the REALITY defaults.

## What The Installer Does

1. Installs system dependencies
2. Installs Xray
3. Installs Caddy only when WebSocket mode is selected
4. Generates or reuses a UUID and, for REALITY, key material and a short ID
5. Writes the selected Xray configuration and, when needed, a Caddy config
6. Validates the generated configurations
7. Enables and starts the applicable services
8. Prints Mihomo / Clash Meta proxy YAML for the selected mode or modes

## Generated Runtime Files

The installer writes files to these system paths:

- `/usr/local/etc/xray/config.json`
- `/etc/caddy/Caddyfile`
- `/etc/systemd/system/xray.service`
- `/etc/raystack/uuid`
- `/etc/raystack/reality-private-key` (REALITY only)
- `/etc/raystack/reality-public-key` (REALITY only)
- `/etc/raystack/reality-short-id` (REALITY only)

## Default Configuration

### VLESS + WebSocket + TLS

- Protocol: `VLESS`
- Transport: `WebSocket`
- Path: `/ray`
- Local listen address: `127.0.0.1`
- Local port: `10000`
- Public port: `443`, or `8443` when both modes are installed

### VLESS + TCP + REALITY

- Protocol: `VLESS`
- Transport: `TCP`
- Flow: `xtls-rprx-vision`
- Public port: `443`
- Default destination and SNI: `swscan.apple.com:443` and `swscan.apple.com`
- The installer prints the required public key and short ID after installation.

### Caddy (WebSocket mode)

- Automatic HTTPS for your domain
- Reverse proxy for `/ray*` to `127.0.0.1:10000`
- Default response for other requests: `OK`

## Notes

- The install flow is designed to be safe to run more than once.
- Existing UUID is reused from `/etc/raystack/uuid`.
- Existing REALITY keys and short ID are reused from `/etc/raystack`.
- Caddy handles TLS automatically after DNS is set correctly. In combined mode,
  it listens on `8443` because REALITY owns `443`.
- After a successful install, copy the displayed `MIHOMO / CLASH META PROXIES`
  block into a Mihomo / Clash Meta configuration. For a REALITY node, replace
  `YOUR_SERVER_ADDRESS` with the VPS IP address or domain before importing.

## Traffic subscription (experimental)

The interactive installer can set a monthly quota in decimal GB (1 GB =
1,000,000,000 bytes), reset day, billing timezone, network interface, and
outbound-only or bidirectional accounting. The cycle changes at midnight in
the chosen timezone; days 29–31 are clamped to the last day of shorter months.
The installer prints a private HTTPS subscription URL for Clash Party. Update the
subscription to refresh its displayed usage; keep the URL secret.

The count covers all traffic on the chosen VPS interface, not individual proxy
clients. Outbound-only reports VPS transmit bytes as download and zero upload;
bidirectional reports receive as upload and transmit as download. Statistics
start when installed and can lag vnStat's save interval; they do not reconstruct
prior usage. Provider billing may differ. Exhausting the quota does not block
traffic. REALITY subscription hosting needs a domain and TCP ports 80 and 8443;
other modes use the existing HTTPS port and port 80 for certificate issuance.

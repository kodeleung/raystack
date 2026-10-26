# Hysteria 2 and mutually exclusive installation modes

## Intent and agreed scope

Extend raystack with Hysteria 2 (HY2). The user has a domain and email and
selected automatic certificate management by Hysteria itself. The user explicitly
requires one installation method per server: remove simultaneous installation,
including the existing WebSocket/REALITY combination.

The installer offers exactly:

1. VLESS + WebSocket + TLS (`ws`).
2. VLESS + TCP + REALITY (`reality`).
3. Hysteria 2 (`hy2`).

Reinstalling the same mode reuses credentials. Selecting another installed mode
stops before changing packages, credentials, configurations, or services. Existing
mixed-mode installations also stop with a manual cleanup explanation. Switching
or uninstalling modes automatically is outside scope.

## Architecture and files

Keep the Bash installer and existing Xray/Caddy helpers. Branch by selected mode
instead of always installing Xray. Add a focused Hysteria installer helper and
configuration template; extend the configuration generator, service checks, and
client output. Remove `config/xray-both.json`, reject `--mode both`, and remove
combined-mode branches and the WebSocket port-8443 special case.

Use Hysteria's official installation script to install the v2 binary and its
`hysteria-server.service` with the dedicated `hysteria` user. Download the script
to a temporary file with checked curl status before execution. Reuse a working
v2 installation; reject an incompatible binary or service configuration instead
of claiming success. HY2 mode does not install or start Xray or Caddy.

Use Python 3 for structural configuration inspection and safe serialization,
alongside Bash orchestration. Make its requirement explicit in the README and
preflight rather than silently relying on it after changing the server. Avoid
an additional YAML package dependency: render Hysteria's configuration as JSON,
which is also valid YAML, into the official `/etc/hysteria/config.yaml` path.
Unrecognized preexisting configurations are treated as unmanaged, not overwritten.

## Installation detection and conflict prevention

Run detection after selecting a mode and before installation side effects.

- Persist a successful mode in `/etc/raystack/mode`, written atomically only
  after service startup checks pass. It is a hint, not the sole source of truth.
- Inspect existing Xray inbound settings. A WebSocket VLESS inbound identifies
  `ws`; a REALITY VLESS inbound identifies `reality`; both identify legacy mixed
  mode. Recognize previous raystack installations that predate the marker.
- Inspect Hysteria configuration and service presence as well as Xray. A valid
  HY2 configuration together with Xray configuration is a mixed installation.
- Credential files and an unused binary alone do not prove a mode is installed.
- A conflicting marker, malformed configuration, or unrecognized managed-path
  configuration produces a diagnostic and stops without overwriting it.
- Preserve unrelated services. Check required listening sockets and identify
  their owners. Occupied ports owned by the recognized same-mode services allow
  reinstallation; unrelated owners stop the install. An unmanaged active Caddy
  must not have its configuration overwritten by WebSocket installation.
- Use an installer lock so two runs cannot pass preflight and write concurrently.

Only a clean server or a recognized installation of the selected single mode can
proceed. Do not silently disable services, remove configurations, or migrate a
legacy mixed deployment.

## HY2 configuration and certificates

Prompt for a hostname and ACME contact email. Normalize and validate inputs,
rejecting URLs, wildcards, control characters, and invalid hostname syntax. Warn
that DNS must point directly to this server and Cloudflare proxying must be off.
Do not require the user to give domain/email to the development chat.

HY2 listens on UDP 443. Hysteria manages certificates using ACME HTTP-01 on
TCP 80, explicitly selecting Let's Encrypt. Store ACME state in a persistent
directory owned by the Hysteria service account, such as
`/var/lib/hysteria/acme`, and preserve it across reinstalls. The service needs
permission to bind both privileged ports and write its ACME state.

Generate a cryptographically random password with `openssl rand -hex 32` and
store it in `/etc/raystack/hy2-password` with mode 0600. Reuse a valid existing
password. Restrict the server configuration to root and the service account,
and never pass credentials through logged command arguments. Output the client
password intentionally in the final client configuration, as with existing UUIDs.

Use normal HY2 QUIC behavior without optional obfuscation, port hopping, custom
bandwidth claims, custom congestion tuning, or DNS changes. These are outside
the requested first version. Do not enable certificate-verification bypass.
Outbound address selection remains Hysteria's default; existing Xray ForceIPv4
behavior remains covered by tests.

Print the required firewall rules (UDP 443 and TCP 80 for HY2). Detect local
conflicts but do not alter the server firewall or cloud security groups. Public
reachability and certificate issuance must not be inferred from local sockets.

## Service lifecycle and failures

Validate inputs and render staged configurations before replacing runtime files.
Use Xray/Caddy's existing validation commands for their modes. Check the actual
Hysteria CLI before choosing a validation path; do not invent a `--test` flag.
For HY2, perform structural validation, followed by bounded startup and readiness
checks, accounting for initial ACME issuance. Treat service exit, ACME errors, or
readiness timeout as failure and show the relevant journal command.

Back up replaced same-mode configurations. On startup failure, restore the old
configuration and attempt to restore the previously running same-mode service.
Preserve credentials and ACME state for retry. Never print installation success
or write a successful mode marker after a failed startup. If rollback fails,
report that explicitly.

A successful local install means the selected service is running and listening
on its expected socket(s). Certificate issuance and an authenticated external
client connection are separate checks; report only checks actually completed.
This development task changes the repository, not the existing Hong Kong server.

## Client output

Each successful installation outputs exactly one Mihomo/Clash Meta proxy:

- WS: the current VLESS WebSocket settings, public TCP 443.
- REALITY: the current VLESS Vision settings, including
  `support-x25519mlkem768: true` under `reality-opts`.
- HY2: `type: hysteria2`, domain as `server` and `sni`, port 443, generated
  `password`, and `skip-cert-verify: false`.

Do not print a UUID in the HY2 summary or private keys in any client output.
Serialize user-provided values safely rather than interpolating unescaped YAML.

## Verification and documentation

Update README installation options, architecture, runtime files, certificate
requirements, required ports, conflict behavior, and removal of combined mode.
Preserve historical design documents as history.

Run shell syntax checks, existing credential parsing tests, and updated template
and client-output tests. Add meaningful regression coverage for legacy mixed
mode detection, cross-mode rejection before side effects, same-mode reinstall,
unmanaged/occupied resources, HY2-only service selection, password persistence
and permissions, ACME configuration, safe rendering, and startup failure/rollback.
Use temporary roots and command stubs so local tests cannot install packages,
rewrite real `/etc` files, or restart services. Validate the generated client
configuration with an available Mihomo binary. Where feasible, validate real
Hysteria startup and authenticated traffic in an isolated disposable Linux
environment using test certificates; distinguish that from live ACME validation.

Live server installation, public ACME issuance, and real HY2 connectivity remain
unverified unless separately exercised with an available domain and environment.

## References

- Official install and service names:
  https://v2.hysteria.network/docs/getting-started/Server-Installation-Script/
- ACME, authentication, and listener configuration:
  https://v2.hysteria.network/docs/advanced/Full-Server-Config/
- Mihomo HY2 fields:
  https://wiki.metacubex.one/config/proxies/hysteria2/

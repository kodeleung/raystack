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
automatically uninstalls the old raystack mode and installs the selected mode.
Existing recognizable raystack mixed-mode installations are also consolidated
into the selected single mode. The user's selection authorizes this switch;
do not require another confirmation during installation. Preserve backups,
credentials, and certificate state so failed switches can recover and later
reinstalls can reuse them. A standalone uninstall command is outside scope.

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

## Installation detection and mode switching

Run detection after selecting a mode and before installation side effects.

- Persist a successful mode in `/etc/raystack/mode`, written atomically only
  after service startup checks pass. It is a hint, not the sole source of truth.
- Inspect existing Xray inbound settings and raystack-specific structure. A WebSocket VLESS inbound identifies
  `ws`; a REALITY VLESS inbound identifies `reality`; both identify legacy mixed
  mode. Recognize previous raystack installations that predate the marker.
- Inspect Hysteria configuration and service presence as well as Xray. A valid
  HY2 configuration together with Xray configuration is a mixed installation.
- Credential files and an unused binary alone do not prove a mode is installed.
- A marker/configuration inconsistency, malformed configuration, or unrecognized
  managed-path configuration produces a diagnostic and stops without overwriting
  it. A marker that correctly identifies a different mode triggers switching,
  not a conflict error. An inbound protocol alone is insufficient proof of ownership.
- Preserve unrelated services. Check required listening sockets and identify
  their owners. Occupied ports owned by recognized raystack services allow
  reinstalling or switching; unrelated owners stop the install. An unmanaged active Caddy
  must not have its configuration overwritten by WebSocket installation.
- Use an installer lock so two runs cannot pass preflight and write concurrently.

A clean server or recognized raystack installation can proceed. Print the
detected old mode(s) and selected new mode before switching. Never uninstall,
stop, or overwrite unrelated services, even if their names or ports overlap.

Switching uses a staged transaction:

1. Collect and validate new inputs, check unrelated port conflicts, download or
   install the new runtime without starting its service, render and validate the
   new configuration, and back up the old configuration, unit/drop-ins, mode
   marker, and service enabled/active state. If an upstream installer starts
   services automatically, suppress that behavior or use a controlled binary
   installation path instead. Do not disrupt the old mode during preparation.
2. Stop and disable old mode services. For WS/REALITY changes, reuse Xray as a
   shared runtime and replace its configuration; remove the old WS Caddy setup
   when leaving WS. When moving between Xray modes and HY2, stop and disable all
   old mode services and remove their recognized active configuration and
   raystack-owned service definitions/drop-ins so they cannot restart later.
3. Install the staged configuration and start only the selected mode. After
   successful readiness checks, atomically record the new mode. Remove obsolete
   dedicated raystack-owned runtime files only after the new mode succeeds.
   Preserve shared packages and anything without proven raystack ownership;
   an unused shared binary does not count as an installed proxy mode.
4. Preserve root-only backups under `/etc/raystack/backups/`, plus credential
   files and ACME state. Do not run broad package purges or delete unrelated
   Caddy sites. Refuse an unsafe ambiguous deployment before stopping services.

Legacy mixed-mode cleanup follows the same transaction and leaves exactly the
selected mode enabled. A short outage during the actual switch is expected and
must be mentioned in the README and install output.

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

Back up replaced configurations for both reinstalls and mode switches. On
startup failure, stop/disable the failed new mode, restore the old configurations,
service definitions/drop-ins, marker, and enabled/active states, and attempt to
restore the previously running old service(s). If there was no prior mode,
remove the failed new mode's active configuration while preserving diagnostic
backups and reusable credentials. Preserve credentials and ACME state for retry.
Never print installation success or write a successful mode marker after a
failed startup. If rollback fails, report that explicitly.

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
requirements, required ports, automatic mode switching and its brief outage,
backup locations, unrelated-service conflict behavior, and removal of combined mode.
Preserve historical design documents as history.

Run shell syntax checks, existing credential parsing tests, and updated template
and client-output tests. Add meaningful regression coverage for legacy mixed
mode detection, each directed switch among the three modes, legacy mixed-mode
consolidation, preparation failure leaving the old mode running, same-mode reinstall,
unmanaged/occupied resources, HY2-only service selection, password persistence
and permissions, ACME configuration, safe rendering, removal of obsolete active
mode resources, and startup failure/rollback restoring old service states.
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

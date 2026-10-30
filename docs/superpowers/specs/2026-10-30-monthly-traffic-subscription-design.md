# Monthly VPS traffic and Clash Party subscription

## Intent and approved scope

Extend the existing interactive Linux installer so a self-hosted VPS can show
its monthly usage and quota on its Clash Party subscription card. The user
approved GB-only quota input, a monthly reset day, and billing timezone choices
of Asia/Shanghai (default), UTC, or a custom IANA timezone. The VPS system
timezone must remain unchanged. Usage is informational; exceeding the quota
does not stop the proxy.

## Installer interaction

Keep the current ws, reality, and both installation modes. Ask whether to enable
traffic subscriptions, defaulting to enabled for a new installation. When enabled:

- Accept a positive decimal quota in GB; 1 GB is exactly 1,000,000,000 bytes.
- Accept an integer reset day from 1 through 31, default 1.
- Offer Beijing time, UTC, and a validated custom IANA timezone.
- Offer outbound-only (default) or inbound plus outbound accounting.
- Detect the public network interface using the default route and allow an
  explicit override; show what will be counted. Exclude loopback and avoid
  summing bridge, container, tunnel, and physical interface counters together.
- Require a public domain for HTTPS subscription delivery. Reuse the WebSocket
  domain when available. For REALITY, obtain the domain and use HTTPS port
  8443 because Xray occupies TCP 443. HTTP port 80 must reach Caddy for ACME.
- Obtain a concrete REALITY node address, defaulting to the subscription domain,
  so the subscription contains no YOUR_SERVER_ADDRESS placeholder.

Repeat installations load the saved settings as defaults and reuse the
subscription token and statistics. Changing timezone or interface requires an
explicit warning that a new statistics series starts and cannot reconstruct
earlier usage. Changing quota, accounting direction, or reset day reuses retained
data and recalculates the visible total.

## Statistics and cycle semantics

Use vnStat 2.x for persistent interface statistics instead of sampling counters
in the HTTP request handler. Install a dedicated vnstatd systemd service with a
raystack-owned configuration and database under /var/lib/raystack/vnstat. Set TZ
only in this service's environment to the chosen billing timezone, aligning its
daily buckets with local midnight without changing global vnStat configuration.
Retain at least 400 daily records. Verify daemon configuration, daily bucket
timestamps, and timezone behavior during implementation; unsupported versions
fail clearly rather than silently returning incorrect figures.

The subscription service queries vnStat JSON daily records for the selected
interface and aggregates the current cycle. The cycle begins at local midnight
on the configured day. Clamp the day separately in each month: day 31 means
February 28/29, then March 31. A cycle is [start, next_start), with timezone-aware
timestamps, including across daylight-saving transitions. Compare daily record
dates in the billing timezone. Missing database data or a failed query returns
an error, never fabricated zero usage.

No destructive monthly database reset is needed: on the boundary, requests
automatically select the new cycle. vnstatd collects continuously even with no
subscription requests and persists across reboots. Fresh installations count
only traffic observed after activation; the installer explains that historical
provider usage is unavailable. vnStat's collection and save intervals mean
displayed statistics can lag and can lose a small unsaved interval on a crash.

This is VPS interface usage, including other services, and is not per-node or
per-device accounting. Provider billing may differ because of direction,
overhead, GB/GiB conventions, or provider-specific exclusions.

## Subscription delivery

Add a small Python standard-library HTTP service bound to loopback, managed by
systemd. Caddy exposes only the token-protected subscription route over HTTPS,
alongside its existing /ray WebSocket route where applicable. Generate at least
256 bits of random token material, store with restrictive permissions, and reuse
it on repeat installs. Do not log the token through generic command logging.
Use constant-time token comparison, bounded requests and subprocess timeouts,
and no public statistics or management API. Give the HTTP service only the
permissions needed to read its configuration and query its statistics.

Return a complete Clash-compatible YAML profile containing the installed nodes,
a selectable proxy group, and explicit routing. Serialize user input safely.
Use the same node rendering for terminal output and subscription output to
avoid divergence. REALITY private keys are never included.

Return these headers on successful authenticated requests:

- Subscription-Userinfo: upload=<bytes>; download=<bytes>; total=<quota bytes>
- Profile-Update-Interval: 1
- Cache-Control: no-store
- An appropriate YAML content type and profile filename.

For bidirectional accounting, upload is VPS ingress (client uploads) and download
is VPS egress (client downloads). For outbound-only accounting, upload is zero
and download is VPS egress, making the client's displayed sum equal the chosen
billing quantity. Document this display convention. Do not send the monthly
reset date as expire: the subscription itself does not expire. The next reset
time is included in YAML comments and the installation summary instead.

An invalid token returns 404. Statistics unavailability returns 503, preserving
the client's last valid subscription rather than replacing it with false data.
Support GET and HEAD consistently. The installer prints the final subscription
URL intentionally for the operator and explains importing and refreshing it in
Clash Party. The URL contains proxy credentials and must be treated as secret.

## Installation and compatibility

Add Python 3, timezone data, iproute, and vnStat dependencies for the existing
apt/dnf/yum paths. Check the required Python and vnStat capabilities before
activating changes. Preserve existing node credentials. Render and validate
service configuration and Caddy routing before restarting services; install
runtime configuration atomically. Avoid overwriting unrelated vnStat settings.
Disabling the feature on repeat installation removes its public route and
stops its services while retaining private configuration and historical data.
Existing installations opting out continue to work as before.

The current checkout has no HY2 implementation; do not incorporate changes from
another worktree or expand into that installation mode in this change.

## Planned change locations

- install.sh: prompts, dependency and lifecycle integration, saved defaults,
  real node addresses, and final subscription instructions.
- scripts/: focused statistics/subscription implementation, shared node renderer,
  and runtime service installation helpers.
- config/: systemd templates and conditional Caddy subscription routing.
- tests/: cycle/accounting tests and isolated installer/HTTP integration checks.
- README.md: setup, units, reset semantics, interface accounting, permissions,
  update interval, fresh-install limitation, and provider billing differences.

## Validation and completion criteria

Test decimal GB validation, invalid dates/timezones/interfaces, each accounting
mode, all existing proxy modes, and subscription-disabled installation. Test
cycle boundaries immediately before and at reset, day 29/30/31 clamping,
leap years, December/January, Asia/Shanghai, UTC, and a DST-observing zone.
Use captured vnStat JSON fixtures for correct aggregation and failed/malformed
query handling. Exercise an authenticated local HTTP server for valid YAML,
headers, GET/HEAD, rejected tokens, subprocess timeout, and 503 behavior.
Verify repeat installations preserve tokens, credentials, and the database.
Run existing shell regression tests and syntax checks. Where available, validate
Caddy and Mihomo output and test vnstatd collection in an isolated Linux runtime.
Clearly distinguish local fixture checks from live VPS, ACME, and Clash Party
verification; do not claim production deployment without actually doing it.

## Reference

- Clash Party subscription response headers:
  https://clashparty.org/docs/guide/urlscheme
- vnStat query/JSON documentation:
  https://www.humdi.net/vnstat/man/vnstat.html
- vnStat configuration and retention options:
  https://github.com/vergoh/vnstat/blob/master/cfg/vnstat.conf

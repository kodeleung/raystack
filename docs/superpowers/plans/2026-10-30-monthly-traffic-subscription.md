# Monthly Traffic Subscription Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the interactive installer configure GB quota, monthly reset day, and billing timezone, then publish VPS usage in a Clash Party subscription.

**Architecture:** A dedicated vnstatd instance persists network-interface statistics in the billing timezone. A loopback Python HTTP service computes the current cycle from daily records and returns a complete Clash profile plus usage headers through Caddy. Existing proxy credentials and statistics survive repeat installation.

**Tech Stack:** Bash, Python standard library (Python 3.9+ with zoneinfo), vnStat 2.x, systemd, Caddy, existing Xray modes. Python and vnStat versions are implementation floors; unsupported machines fail with a useful message before activation.

**Spec:** `docs/superpowers/specs/2026-10-30-monthly-traffic-subscription-design.md`

## Global Constraints

- Accept a positive decimal quota in GB; 1 GB is exactly 1,000,000,000 bytes.
- Accept an integer reset day from 1 through 31, default 1.
- Offer Beijing time, UTC, and a validated custom IANA timezone.
- Offer outbound-only (default) or inbound plus outbound accounting.
- The VPS system timezone must remain unchanged.
- Retain at least 400 daily records.
- Missing database data or a failed query returns an error, never fabricated zero usage.
- Usage is informational; exceeding the quota does not stop the proxy.
- Do not send the monthly reset date as expire: the subscription itself does not expire.
- The current checkout has no HY2 implementation; do not incorporate changes from another worktree or expand into that installation mode in this change.
- Do not push, deploy, or expose real subscription tokens while running local tests.

## Review Focus

- A timezone with a non-hour UTC offset must aggregate billing-local dates correctly (Task 1).
- Older vnStat JSON or startup with an empty database must fail clearly without erasing an existing subscription (Tasks 1 and 3).
- Quotes, line breaks, and shell metacharacters in operator input must not become YAML, Caddy, or shell injection (Tasks 2 and 4).
- Repeated installation after a partial failure must preserve tokens, databases, and valid proxy configuration (Task 4).
- REALITY owns port 443, so subscription TLS and certificate validation must work without competing for that port (Tasks 4 and 5).

## File Responsibilities

- `scripts/traffic.py`: validated settings, billing calendar, vnStat JSON query and aggregation.
- `scripts/client_config.py`: node and full-profile serialization shared by installer and HTTP service.
- `scripts/subscription_server.py`: authenticated HTTP GET/HEAD and usage headers.
- `scripts/install_traffic.sh`: runtime files, permissions, dedicated services, and configuration staging.
- `scripts/traffic_prompts.sh`: interactive traffic settings and saved defaults; sourced by installer.
- `install.sh`: existing orchestration plus traffic setup and final URL.
- `scripts/generate_config.sh`, `config/Caddyfile`: validated conditional HTTPS subscription route.
- `config/raystack-vnstat.service`, `config/raystack-subscription.service`: hardened service templates.
- `tests/test_traffic.py`, `tests/test_client_config.py`, `tests/test_subscription_server.py`: standard-library unittest suites.
- `tests/test_traffic_install.sh`, `tests/fixtures/vnstat/`: isolated installation checks and representative JSON.
- `README.md`: operator setup and accounting limitations.

### Task 1: Billing Calendar and Persistent Statistics Adapter

**Files:** Create `scripts/traffic.py`, `tests/test_traffic.py`, and `tests/fixtures/vnstat/`.

**Interfaces:** Produces `validate_settings(values: dict) -> dict`, `cycle_bounds(now: datetime, reset_day: int, timezone: str) -> tuple[datetime, datetime]`, `query_usage(settings: dict, now: datetime) -> dict`. Validated settings contain `quota_bytes`, `reset_day`, `timezone`, `interface`, `accounting`, `domain`, `https_port`, and `node_address`. Usage contains integer `upload`, `download`, `total`, and Unix `next_reset`.

- [ ] **Step 1:** Write failing unittest cases for positive decimal GB conversion without float rounding; zero, negative, NaN, infinity, and sub-byte quotas must fail. Assert day 0/32 and unknown timezones fail.
- [ ] **Step 2:** Add calendar cases asserting Shanghai day-15 starts at 2026-10-14T16:00:00Z; day-31 yields 2028-02-29 and 2028-03-31; include before/at reset, December/January, New York DST, and Asia/Kathmandu midnight.
- [ ] **Step 3:** Add fixtures and tests asserting ingress=100 and egress=250 produce (0,250) outbound-only and (100,250) bidirectional; exclude previous-cycle dates. Test missing interface, empty/malformed JSON, unsupported schema, missing records, command failure, and timeout. An initialized current bucket with zero traffic is valid.
- [ ] **Step 4:** Run `python3 -m unittest discover -s tests -p test_traffic.py -v`; expect failure because implementation is absent.
- [ ] **Step 5:** Implement the declared interfaces using Decimal, calendar, zoneinfo, and bounded subprocess calls. Query only the dedicated vnStat database, validate record dates, and raise a typed `StatisticsUnavailable` exception on unavailable data.
- [ ] **Step 6:** Run the same unittest command; all cases pass. Commit these files with `feat: add monthly traffic accounting`.

### Task 2: Shared Clash Configuration Renderer

**Files:** Create `scripts/client_config.py` and `tests/test_client_config.py`; modify `install.sh` and `tests/test_clash_output.sh`.

**Interfaces:** Consumes existing mode/domain/UUID/REALITY public fields. Produces `render_nodes(node_settings: dict) -> str` and `render_profile(node_settings: dict, next_reset: int, timezone: str) -> str`. CLI accepts a settings JSON file or JSON from stdin; never pass private keys. Preserve terminal delimiter lines and existing node names.

- [ ] **Step 1:** Write failing tests for ws, reality, and both modes, checking UUID, REALITY ML-KEM support, port, concrete address, proxy-group membership, explicit MATCH routing, and absence of private keys. Assert newline/quote-containing values stay inside serialized string values.
- [ ] **Step 2:** Run `python3 -m unittest discover -s tests -p test_client_config.py -v`; expect missing-module failure.
- [ ] **Step 3:** Implement JSON-quoted YAML scalars, shared node rendering, complete profiles, and reset-time comments. Change terminal printing to use the renderer; retain the existing placeholder only for subscription-disabled legacy usage.
- [ ] **Step 4:** Run renderer unittest and `bash tests/test_clash_output.sh`; both pass. Commit with `feat: render complete Clash subscription profiles`.

### Task 3: Authenticated Loopback Subscription Service

**Files:** Create `scripts/subscription_server.py` and `tests/test_subscription_server.py`.

**Interfaces:** Consumes Task 1 settings/usage and Task 2 `render_profile`. Produces `make_server(settings: dict, node_settings: dict, token: str, host: str = "127.0.0.1", port: int = 8765) -> HTTPServer` plus a CLI loading a private runtime JSON file. Accept only `/subscription/<token>` with no query string; use constant-time token comparison.

- [ ] **Step 1:** Write failing local-server tests for authenticated GET and HEAD with identical headers, empty HEAD body, no expire field, `Profile-Update-Interval: 1`, `Cache-Control: no-store`, safe filename, and exact semicolon-space separated Subscription-Userinfo. Use synthetic credentials.
- [ ] **Step 2:** Add tests for invalid token/path returning 404, unsupported methods, statistics exception/timeout returning 503, no token in request logs, and a last valid profile unaffected by a later server failure.
- [ ] **Step 3:** Run `python3 -m unittest discover -s tests -p test_subscription_server.py -v`; expect failure.
- [ ] **Step 4:** Implement loopback-only production binding, bounded sockets/request handling, sanitized logging, and per-request fresh statistics. HEAD must execute the same success/error path as GET without sending its body.
- [ ] **Step 5:** Run the same unittest command; all cases pass. Commit with `feat: serve authenticated traffic subscriptions`.

### Task 4: Installer, Caddy, and Dedicated vnStat Services

**Files:** Create `scripts/install_traffic.sh`, `scripts/traffic_prompts.sh`, `config/raystack-vnstat.service`, `config/raystack-subscription.service`, and `tests/test_traffic_install.sh`; modify `install.sh`, `scripts/generate_config.sh`, and `config/Caddyfile`.

**Interfaces:** Produces `prompt_traffic_parameters` (Bash), and an install helper accepting a validated staged JSON configuration and runtime root. Runtime root defaults to `/`; tests must use a temporary directory with mocked commands. Install Python modules under `/usr/local/lib/raystack`, private settings under `/etc/raystack/traffic.json`, and database under `/var/lib/raystack/vnstat`. A dedicated raystack user owns the database and can read its configuration; secrets are not world-readable. Tests must never write real system directories.

- [ ] **Step 1:** Write failing mocked installation cases for all proxy modes, subscription-disabled legacy behavior, input retries, saved defaults, interface discovery/override, and malformed domain/address/interface rejection. Reject shell/Caddy control characters before rendering.
- [ ] **Step 2:** Add tests for repeat installation preserving token, UUID, and database; quota/reset changes retain data; timezone/interface changes require explicit acknowledgement and archive the old series. Verify disabling stops services/removes route but retains data. Force validation failure and assert live configuration is unchanged.
- [ ] **Step 3:** Run `bash tests/test_traffic_install.sh`; expect missing-helper failure.
- [ ] **Step 4:** Implement prompts and capability checks; add python3, tzdata, iproute/iproute2, and vnstat to supported package-manager paths. Check Python zoneinfo support and vnStat JSON/config features before activating files. Add a separate service-local TZ, database and log paths, 400-day retention, and dedicated daemon instance; never modify global vnStat configuration.
- [ ] **Step 5:** Generate/reuse a 32-byte cryptographic token without passing it through `run` logging. Write staged files atomically with restrictive permissions. Configure the HTTP service user and systemd filesystem restrictions. Invoke dedicated vnstatd with supported foreground/config options and run subscription service unprivileged.
- [ ] **Step 6:** Render conditional Caddy routing to loopback service without route-token logging. Keep ws on 443, both on 8443, and use 8443 for reality subscription. Ensure Caddy can obtain certificates over HTTP-01 without binding REALITY's 443. Validate staged Caddy/Xray configs before activation; retain recoverable backups and restore prior files/services on failure. Never restart Xray merely to roll a billing cycle.
- [ ] **Step 7:** Print interface, GB convention, accounting mode, timezone, next reset, first-install limitation, required ports, and subscription URL intentionally. Distinguish an invalid setup from a temporary statistics warmup.
- [ ] **Step 8:** Run mocked installer tests plus all three existing shell test scripts and `bash -n` on changed scripts. All pass. Commit with `feat: install monthly traffic subscription services`.

### Task 5: Linux Integration, Operator Documentation, and Final Verification

**Files:** Modify `README.md`; create `tests/test_traffic_linux.sh` for an opt-in isolated Linux environment.

**Interfaces:** Consumes the complete installer and runtime from Tasks 1–4. The Linux check must be disposable and must not use real VPS credentials or issue production certificates.

- [ ] **Step 1:** Build/run a disposable Linux check with actual vnstatd and Python. Verify dedicated database initialization, synthetic loopback traffic collection on an explicitly configured test interface, persistence after daemon restart, and that TZ-local daily bucket timestamps match Task 1 assumptions. Check supported apt-family and RPM-family package availability/version floors; if a supported distro lacks capabilities, report a specific preflight error rather than install broken services.
- [ ] **Step 2:** Validate Caddy routes for all modes with actual `caddy validate`; test local TLS using an internal test CA and explicitly disabled ACME. Verify reality subscription listens on 8443 without claiming TCP 443. If Mihomo is available, parse every generated profile with its config test command.
- [ ] **Step 3:** Resolve any vnStat timezone/schema discrepancy in the owning code and fixtures before proceeding. Run Linux checks once more only if fixes warrant it. If Docker/systemd tooling is unavailable, record exactly which validation remains unperformed.
- [ ] **Step 4:** Document prompts, GB units, quota/direction examples, reset semantics, timezone behavior, HTTPS ports, subscription refresh/import, upgrade/disable behavior, runtime paths, token privacy, statistics warmup, and provider-billing differences. Remove the obsolete README claim that runtime is Bash-only.
- [ ] **Step 5:** Run `python3 -m unittest discover -s tests -p 'test_*.py' -v`, each shell regression, shell syntax checks, and `git diff --check`. Check final diff and secret-bearing logging paths. Commit with `docs: document monthly usage subscriptions`.
- [ ] **Step 6:** Report completed behavior, checks actually run, and any live VPS/ACME/Clash Party verification still needed. Do not claim or perform deployment or push without authorization.

## Self-Review

All spec sections map to Tasks 1–5: calendar/statistics (1), YAML and credentials (2), HTTP/error semantics (3), prompts/services/lifecycle/security (4), and genuine Linux behavior/documentation (5). All five Review Focus conditions have explicit test owners. Function names and settings are shared through the Interfaces blocks. Implementation should take place on a `codex/` branch without disturbing the pre-existing local commits.

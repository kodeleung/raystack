# Hysteria 2 and Exclusive Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install exactly one of WS, REALITY, or HY2, automatically replace an old raystack mode, and recover the old installation if replacement fails.

**Architecture:** Keep Bash orchestration and add focused helpers for deployment inspection, safe configuration rendering, and reversible service changes. Stage and validate the new mode before stopping the old one, preserve a root-only snapshot, and commit the selected mode marker only after readiness succeeds.

**Tech Stack:** Bash, Python 3 standard library, OpenSSL, systemd, Xray, Caddy, Hysteria 2, Mihomo for client validation.

**Spec:** `docs/superpowers/specs/2026-10-27-hysteria2-exclusive-modes-design.md`

## Global Constraints

- The installer offers exactly `ws`, `reality`, and `hy2`; reject `--mode both` and remove `config/xray-both.json`.
- Reinstalling the same mode reuses credentials. Selecting another installed mode automatically uninstalls the old raystack mode and installs the selected mode.
- The user's selection authorizes switching; do not require another confirmation during installation.
- Preserve backups, credentials, and certificate state; never stop, uninstall, or overwrite unrelated services.
- HY2 listens on UDP 443, uses Let's Encrypt ACME HTTP-01 on TCP 80, and retains ACME state in `/var/lib/hysteria/acme`.
- HY2 uses the dedicated `hysteria` account and `/etc/hysteria/config.yaml`, rendered as JSON; no Python YAML dependency.
- Generate HY2 passwords with `openssl rand -hex 32`; store `/etc/raystack/hy2-password` with mode 0600.
- No custom obfuscation, port hopping, bandwidth tuning, DNS changes, automatic firewall changes, or certificate-verification bypass.
- Preserve `support-x25519mlkem768: true` and existing Xray ForceIPv4 behavior.
- Repository implementation only; do not change the Hong Kong server or claim live ACME/client validation without exercising it.

## Review Focus

- A stopped or disabled old service must retain its exact previous state after rollback, rather than being started unconditionally (Task 3).
- An unrelated Caddy site, custom service override, symlink, or arbitrary VLESS server must not be mistaken for a raystack deployment (Task 1).
- Downloads/package hooks can start services before cutover; preparation must prevent premature port binding or old-service restarts (Task 2).
- ACME can take longer than ordinary startup and systemd can remain active while startup is failing; readiness must verify the intended process/socket and timeout honestly (Task 3).
- A lost mode marker or interrupted prior switch must not cause configuration overwrite or two enabled modes on retry (Tasks 1 and 3).

---

### Task 1: Inspect existing deployments and reject unsafe conflicts

**Files:** Create `scripts/deployment_state.py`, `tests/test_deployment_state.py`; add test fixtures under `tests/fixtures/` as needed.

**Interfaces:**
- Produces `inspect_installation(root: pathlib.Path) -> dict` with keys `modes: list[str]`, `services: list[str]`, `managed_paths: list[str]`, and `marker: str | None`; modes are `ws`, `reality`, or `hy2`.
- Produces `validate_listeners(state: dict, selected_mode: str, sockets: list[dict]) -> None`; raises `ValueError` for unrelated required-port owners.
- CLI: `python3 scripts/deployment_state.py inspect --root ROOT` prints JSON or exits nonzero with a diagnostic. Paths in manifests are root-relative, never arbitrary user-supplied absolute paths.

- [ ] **Step 1: Write failing structural inspection tests.**

```python
def test_legacy_both_is_recognized():
    assert inspect_fixture("legacy-both")["modes"] == ["ws", "reality"]

def test_credentials_and_unused_binary_do_not_install_a_mode():
    assert inspect_fixture("credentials-only")["modes"] == []

def test_unmanaged_caddy_and_custom_vless_are_rejected():
    for fixture in ("unmanaged-caddy", "custom-vless", "symlink-config", "custom-unit"):
        with self.assertRaises(ValueError):
            inspect_fixture(fixture)
```

Also assert recognition of all three single modes, Xray+HY2 mixed state, adoption without a marker, matching previous template shapes/credential files, rejection of malformed JSON and inconsistent markers, and listener conflicts for TCP 80/443 and UDP 443. Treat unknown Hysteria YAML as unmanaged.
- [ ] **Step 2:** Run `python3 -m unittest discover -s tests -p 'test_deployment_state.py' -v`; expect missing module/functions before implementation.
- [ ] **Step 3:** Implement inspection and listener validation with Python standard-library JSON/path handling. Check ownership using recognized configurations and known unit layouts, including previous upstream Xray drop-ins; reject extra inbounds, extra Caddy sites, and unknown service commands. Do not mutate files during inspection.
- [ ] **Step 4:** Run the Task 1 tests; expect all pass with no real `/etc` access.
- [ ] **Step 5:** Commit `feat: detect managed proxy deployments and conflicts`.

### Task 2: Render and prepare single-mode installations including HY2

**Files:** Create `scripts/render_config.py`, `scripts/install_hysteria.sh`, `config/hysteria.json`, `tests/test_render_config.py`, `tests/test_hysteria_install.sh`; modify `scripts/generate_config.sh`, `scripts/install_xray.sh`, `scripts/install_caddy.sh`.

**Interfaces:**
- Consumes Task 1 inspection manifests; installer preparation must respect their ownership findings.
- Produces `render_configs(mode: str, values: dict) -> dict[str, str]` in `scripts/render_config.py`; keys are root-relative runtime paths, values are serialized configurations. `values` uses `domain`, `email`, `uuid`, `reality_dest`, `reality_sni`, `reality_private_key`, `reality_short_id`, `hy2_password`.
- Renderer CLI reads credential-bearing values from standard input JSON and writes to `--output-dir DIR`; never log secrets or put them in command arguments.
- `scripts/install_hysteria.sh` prepares a v2 binary/service without starting it; preserves an existing compatible installation and rejects incompatible ones. HY2 owns its config and ACME directories through the dedicated account.
- Extend `generate_config.sh` with a staging output directory while keeping existing single-mode arguments compatible. Reject `both`.

- [ ] **Step 1: Write failing rendering and preparation tests.**

```python
def test_hy2_uses_verified_acme_and_persistent_state():
    cfg = json.loads(render_configs("hy2", hy2_values())["etc/hysteria/config.yaml"])
    assert cfg["listen"] == ":443"
    assert cfg["acme"]["ca"] == "letsencrypt"
    assert cfg["acme"]["type"] == "http"
    assert cfg["acme"]["dir"] == "/var/lib/hysteria/acme"
    assert cfg["auth"]["password"] == hy2_values()["hy2_password"]
```

Add tests for all mode requirements, safe quote/backslash serialization, hostname/email rejection, rejection of `both`, missing credentials, unchanged Xray ForceIPv4, and absence of unwanted services/configs per mode. Stub downloads and package/service commands to prove no service starts during preparation, including existing running services and a failed curl.
- [ ] **Step 2:** Run `python3 -m unittest discover -s tests -p 'test_render_config.py' -v` and `bash tests/test_hysteria_install.sh`; expect failure before implementation.
- [ ] **Step 3:** Inspect current upstream installers and Hysteria `--help`; choose a version-checked official install path with service-start suppression. If upstream cannot guarantee preparation without service side effects, download the official release binary and install a controlled dedicated-user unit. Ensure `CAP_NET_BIND_SERVICE`, ACME directory ownership, root/group-only server config, and checked download failures. Stage all generated files and validate Xray/Caddy with their binaries before deployment. Do not invent HY2 flags.
- [ ] **Step 4:** Run Task 2 tests and Bash syntax checks for modified helpers; expect all pass.
- [ ] **Step 5:** Commit `feat: prepare standalone Hysteria 2 installations`.

### Task 3: Implement reversible mode replacement and readiness

**Files:** Create `scripts/deployment.sh`, `tests/test_mode_switch.sh`; extend `scripts/deployment_state.py` with snapshot helpers and `tests/test_deployment_state.py` with snapshot round-trip tests.

**Interfaces:**
- Consumes Task 1 manifests and Task 2 staged configurations.
- Python produces `snapshot_installation(root: Path, state: dict, backup_dir: Path, service_states: dict) -> None` and `restore_installation(root: Path, backup_dir: Path) -> dict`; snapshot includes bytes, modes, uid/gid, unit/drop-ins, file absence, marker, enabled/active states. Restore returns those service states.
- Bash produces `acquire_install_lock`, `backup_installation`, `stop_previous_services`, `activate_selected_mode`, `wait_for_selected_mode`, `rollback_installation`, `commit_selected_mode`.
- `RAYSTACK_ROOT` defaults to `/` and `RAYSTACK_STATE_DIR` to `${RAYSTACK_ROOT%/}/etc/raystack`; tests override root and stub service/socket commands. A root-scoped `flock` covers inspection through commit.
- Readiness polls at most 120 seconds for HY2 and 30 seconds for WS/REALITY; checks required service state and expected process-owned listening socket, aborting on failed service. Show ACME journal errors without credential-bearing debug logs.

- [ ] **Step 1: Write failing switch and rollback tests.** Use stubbed commands and temporary roots; assert event order for all six directed switches and same-mode reinstalls. Assert old services are untouched on preparation failure; legacy mixed mode ends with only the selected mode enabled. Assert an active old service restarts on failure, a stopped/disabled old service stays stopped/disabled, failed fresh install leaves no active mode, rollback failure is reported, credentials/ACME state survive, and snapshots are root-only. Test an interrupted switch/missing marker and lock contention.
- [ ] **Step 2:** Run `bash tests/test_mode_switch.sh` and Task 1 Python tests; expect failure on missing switching functions.
- [ ] **Step 3:** Implement staged cutover with explicit checked errors and cleanup traps that preserve the original failure status. Snapshot before installing runtime files; only remove proven old-mode configurations/units, retain shared packages and credentials, and never purge Caddy data. During rollback stop the failed target, restore file absence as well as file contents, reload systemd, then restore enabled/active states. Write the marker atomically after readiness; output the backup path and brief outage warning.
- [ ] **Step 4:** Run Task 3 tests; expect all pass. Include an ACME startup timeout with `active` systemd state but absent UDP listener to prove that active alone does not mean success.
- [ ] **Step 5:** Commit `feat: switch proxy modes with backup and rollback`.

### Task 4: Connect the interactive installer and client output

**Files:** Modify `install.sh`, `tests/test_clash_output.sh`, `tests/test_xray_templates.sh`; create `scripts/print_client_config.py`, `tests/test_install_flow.sh`; delete `config/xray-both.json`.

**Interfaces:**
- Consumes Tasks 1–3 through a main flow of lock, select, inspect, prompt/validate, prepare, snapshot, cutover, readiness, commit, client output.
- `prompt_mode` maps `1 -> ws`, `2 -> reality`, `3 -> hy2`. `prompt_mode_parameters` requests domain/email for HY2, domain for WS, destination/SNI for REALITY.
- `load_or_create_hy2_password` uses `openssl rand -hex 32`, validates reused 64-character hex passwords, saves mode 0600, and never logs the value.
- `print_client_config(mode: str, values: dict) -> str` emits one YAML proxy using JSON-quoted scalars; existing `print_clash_config` delegates while retaining its wrapper format. HY2 output uses `type: hysteria2`, `sni`, `password`, `port: 443`, `skip-cert-verify: false`. REALITY preserves its ML-KEM option.

- [ ] **Step 1:** Update failing client/template tests to use three exclusive modes, HY2 secure fields and no UUID, REALITY ML-KEM, no secret key leaks, fixed WS port 443, and escaped scalar values. Add installer-flow tests with all side effects stubbed: HY2 never calls Xray/Caddy helpers, switching uses Task 3, canceled input changes nothing, credential reuse and permissions hold, and success output/marker do not occur after failure.
- [ ] **Step 2:** Run `bash tests/test_clash_output.sh`, `bash tests/test_xray_templates.sh`, and `bash tests/test_install_flow.sh`; expect the new HY2/selection tests to fail before implementation.
- [ ] **Step 3:** Connect helpers, add explicit Python 3 and lock requirements before mutation, remove combined-mode branches and unconditional UUID/Xray operations, and source helpers safely without running main in tests. Keep secrets out of `run` output and generator command arguments. Have CLI failures return nonzero without success summaries.
- [ ] **Step 4:** Run Task 4 tests and all earlier tests; expect all pass.
- [ ] **Step 5:** Commit `feat: offer exclusive proxy modes and HY2 client output`.

### Task 5: Document usage and verify actual runtime compatibility

**Files:** Modify `README.md`; create `tests/run.sh` and `tests/test_hy2_runtime.sh`.

**Interfaces:**
- `bash tests/run.sh` runs all local safe tests and syntax checks; runtime smoke tests are opt-in and explicitly skip with a reason when their disposable Linux environment/binaries are unavailable.
- Runtime smoke testing consumes rendered HY2 configuration and a temporary certificate fixture; it never uses a production domain, edits host `/etc`, opens a cloud firewall, or stops existing host services.

- [ ] **Step 1:** Add a failing smoke-test harness that verifies an authenticated client can reach a controlled HTTP target through a real HY2 server with a trusted test certificate and rejects a wrong password. Separate this local TLS test from public ACME issuance.
- [ ] **Step 2:** Run the smoke test in an available disposable Linux environment; before implementation of the harness expect failure, or an explicit prerequisite skip when no safe environment exists.
- [ ] **Step 3:** Document the three modes, Python 3 requirement, exact ports/DNS preparation, automatic certificate renewal, mode switching/outage, backup path, rollback, credential reuse, journal commands, unsupported unmanaged deployments, and the distinction between local readiness and public reachability. Update the file tree and remove operational references to combined mode without changing historical documents.
- [ ] **Step 4:** Run `bash tests/run.sh`, `git diff --check`, and validate generated complete client configs with an available Mihomo `-t -f` invocation using a temporary directory. Run the opt-in HY2 smoke test if safe prerequisites exist. Report skipped Linux/ACME checks honestly and fix actual failures before expanding testing.
- [ ] **Step 5:** Commit `docs: document exclusive modes and verify HY2 compatibility`.

## Handoff

Recommend native execution in this session: the five tasks share deployment and rollback interfaces, and one implementer can keep their error handling consistent. Follow the executing-plans skill, then have one fresh reviewer inspect the complete change. The alternative is a fresh implementing subagent and reviewer per task. Wait for the user's review and execution-method choice before implementation.

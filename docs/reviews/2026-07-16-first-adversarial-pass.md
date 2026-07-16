# First adversarial review pass — meshing_around_meshforge (client repo)

**Date:** 2026-07-16
**Reviewer:** Claude Fable 5 (frontier upshift pass, MeshForge review_provenance Pri-1)
**Scope:** First-ever adversarial review of the CLIENT repo (~50 first-party
Python files, ~23k LOC). The 2026-07-06 rows covered the BOT fork — a different
repo. This pass covered four surfaces with four parallel reviewers: the
mesh-facing parse path (RF/MQTT), the crypto module, the subprocess/system
installer surface, and the TUI + config surface.
**Suite at pass start:** 1021 passed (system python3, exit 0).
**Suite after fixes:** 1028 passed (exit 0).

## Threat model

This is a Meshtastic mesh **client**: it ingests packets/JSON from RF radios and
MQTT brokers, which are **attacker-controllable** (any node on the mesh, any
publisher on a public broker can set node names, message text, positions,
telemetry, topic strings). The installer/configurator runs as **root** on
Raspberry Pis. Those two facts anchor severity.

## Verification convention

- **CONFIRMED** — I verified the defect against the actual source this session.
- **PLAUSIBLE** — surfaced by a reviewer agent, spot-checked but not
  independently line-verified this session; burden of proof is on the error
  path (honest_failure_modes). Triage before acting.

---

## Fixed this pass (all CONFIRMED, red-test-first, suite green)

| # | Sev | Defect | Fix |
|---|-----|--------|-----|
| C1 | HIGH | **`mesh_crypto._derive_key` was non-spec** — SHA-256-expanded every PSK to 32 bytes (AES-256). Real Meshtastic uses the 16-byte default PSK `d4f1bb3a20290759f0bcffabcf4e6901` (AES-128) for `AQ==`, and 16-byte PSKs directly as AES-128. The module could not decrypt real default/128-bit `/e/` traffic; roundtrip tests passed only because encrypt+decrypt shared the same wrong derivation (self-consistent, not spec-conformant). | Rewrote `_derive_key` to the spec: 1-byte index → default-PSK family (AES-128), 16/32-byte → used directly, non-standard length → `None` + WARNING (never a valid-looking key). Rewrote the 4 derivation tests to spec vectors. |
| C2 | MED | **`set_key` accepted malformed base64** — `b64decode` without `validate=True` silently drops non-alphabet chars, so a typo'd key installed a *different* key and reported success. | `base64.b64decode(key, validate=True)`; new test that `"Secret Key!"` is rejected. |
| S1 | HIGH | **`run_command(desc=...)` crashed the normal update path** — the modular `system_maintenance.run_command` had no `desc` param (only configure_bot's fallback shim did); with modules available, `configure_bot.py:921` (patch re-apply after `git pull`) raised `TypeError`, aborting the update and skipping the MeshForge bridge-patch re-apply — the exact clobber it exists to prevent. | Added `desc: str = ""` (logs it) to the modular signature; new test. |
| S2 | HIGH | **Bot service created as `User=root` under sudo** — `username = os.environ["USER"]` is `root` under the documented `sudo` mode, so the bot (which executes network-derived commands) ran as root. `get_user_home` already used `SUDO_USER` — inconsistent. | Prefer `SUDO_USER`; warn loudly if the resolved user is still root. |
| S3 | HIGH | **`shutil.rmtree(install_path)` on unvalidated user-typed path as root** — a typo like `/home/pi` or `/opt` would recursively delete a home/system dir. | New tested `_is_safe_rmtree_target` guard refuses `/`, system dirs, and home-directory roots; both rmtree sites gated. |

---

## Fixed in follow-up passes (2026-07-16, same day)

- **S4 (HIGH→robustness) — systemd-unit f-string injection / unquoted ExecStart**
  — FIXED, commit `2af1db3`. `_sanitize_unit_value` rejects C0 controls in every
  interpolated value; ExecStart paths are double-quoted (spaces stay one argv
  token); service names validated against `[A-Za-z0-9_.@-]`; `setup_headless.sh`
  mesh_bot heredoc quoted. +11 tests.
- **TUI Rich-markup render-DoS (was PLAUSIBLE HIGH → CONFIRMED, corrected)** —
  FIXED, commit `3f6682f`. `_rm_safe` escapes every network-derived string at the
  Nodes/Topology/Devices/Channels/Routes render sites + the typed search query.
  ⚠️ The finding's example trigger `"[/"` does NOT crash (Rich renders incomplete
  markup literally) — the real trigger is a close-with-no-open `"[/]"`/`"[/red]"`;
  verified live and corrected. +4 tests incl. a self-checking harness.
- **Config silent public-broker fallback (was PLAUSIBLE MED → CONFIRMED)** —
  FIXED, commit `580d529`. `Config.__init__` discarded `load()`'s return; a
  corrupt private config silently kept the public-broker + public-creds defaults.
  Now `load_error` witness + ERROR log + a WARNING naming the effective default
  broker. +3 tests.

## Open — PLAUSIBLE, not verified (triage before acting) — remaining MED cluster

Still queued from item 3: **secrets rendered unmasked** in the TUI config editors
(mqtt.password / encryption_key shown plaintext), **whiptail TUI crashes on one
malformed node** (`node.role.value`/`snr` formatting on `None`), and **non-atomic
config writes** (`config.py`/`config_schema.py` `save()` truncate-in-place, no
temp+rename → torn INI on power loss). Each still needs line-verification.

## Open — PLAUSIBLE, not verified this pass (triage before acting)

These are reviewer-reported and spot-plausible but were not independently
line-verified. Grouped by surface; ranked roughly by the reviewer's severity.

### Crypto
- **PLAUSIBLE MED — multi-key "first protobuf that parses wins" false-accept**
  (`try_decrypt_with_keys` + `process_encrypted_packet` success = truthy
  portnum). MAC-less protocol; looping candidate keys and accepting the first
  parse multiplies wrong-key false-accepts — an attacker without the PSK could
  get a fabricated text/position injected into the node DB. Hard to fully fix
  (protocol limitation); at minimum tighten the success criterion and don't
  reward multi-key breadth.
- **PLAUSIBLE LOW — `decrypt()` collapses "no backend"/"decrypt error"/"empty"
  into `b""`**, all reported as generic "Decryption failed" — an operator on a
  box with a broken `cryptography` Rust backend is pointed at the wrong cause.

### Parse surface (RF/MQTT)
- **PLAUSIBLE MED — terminal-escape/control-char injection** from mesh text &
  node names into the operator's terminal via the root logger / console handler
  (`callbacks.py:427-433`, `mqtt_client.py:1654`, `meshtastic_api.py:1403`). An
  attacker's message `"sos \x1b[2J..."` matching an emergency keyword renders
  escapes on the console. Strip C0/C1 before logging network strings.
- **PLAUSIBLE MED — `get_nodes()` iterates `network.nodes` without the lock**
  (`mqtt_client.py:1917`) on the GeoJSON export thread while the cleanup thread
  deletes under lock → `RuntimeError: dictionary changed size` not in the
  export loop's `except` → export thread dies, `nodes.geojson` silently freezes
  (honest-failure: stale map read as live). `get_nodes_snapshot()` exists; use it.
- **PLAUSIBLE MED — unbounded `_decrypt_warn_last` keyed by attacker-controlled
  channel name** (`mqtt_client.py:207,1301`) → memory growth / OOM on a Pi Zero
  under a wildcard subscription. Cap/prune.
- **PLAUSIBLE MED — `AttributeError` on malformed JSON top-level/payload type**
  (`mqtt_client.py:969,1140,1152,1230`) is uncaught and NOT counted as rejected,
  so the malformed-rate health signal stays blind to a flood. Add `AttributeError`
  to the handled set and bump `messages_rejected`.
- **PLAUSIBLE LOW — node fields mutated off `network._lock`** (locking-contract
  violation; GIL masks it on CPython today).

### Subprocess / system installer
- **PLAUSIBLE MED — `apply_meshforge_patches.py` non-atomic in-place write** of
  live `mesh_bot.py` (the file's own comment records a prior truncation-to-empty
  via mid-write encode error); no backup/rollback, `py_compile` runs after the
  write. Atomic temp+rename + backup.
- **PLAUSIBLE MED — `apt upgrade -y` captured, no `DEBIAN_FRONTEND=noninteractive`
  / `--force-confold`** → a conffile prompt hangs invisibly for the full timeout.
- **PLAUSIBLE MED — `dpkg -l`/`dpkg -s` exit 0 for removed-but-not-purged
  packages** read as "installed" → skipped installs. Use
  `dpkg-query -W -f='${Status}'`.
- **PLAUSIBLE MED — git pull falls back main→master→develop and reports success
  from whichever merges** — an unintended-branch merge masquerading as a routine
  update.
- **PLAUSIBLE MED — `git stash pop` return code ignored** → a pop conflict
  silently strands local edits while `success=True` (the MeshForge source
  patches are exactly the kind of diff that gets stashed).
- **PLAUSIBLE MED — `verify_bot_running` launches with bare `python3`** (venv
  ignored → import error on PEP 668 boxes) and "alive after 3s" = success;
  `pgrep -f mesh_bot.py` matches `nano mesh_bot.py`.
- **PLAUSIBLE LOW-MED — `set -e` in `setup_headless.sh` turns the benign
  "meshing-around not found, skipping" into a whole-script abort**; unquoted
  `$USER` in `usermod`; INI/systemd writes non-atomic with a world-readable SMTP
  password window (`migrate_config`, `save_config`).
- **PLAUSIBLE LOW — `whiptail.py` `stty sane` TimeoutExpired uncaught (fd leak);
  30s hard timeout on interactive dialogs can convert a slow human into an
  implicit answer.**

### TUI / config
- **PLAUSIBLE HIGH — Rich markup injection / render-DoS from hostile node names**
  in every table/tree EXCEPT the two SEC-16 screens (`app.py` NodesScreen,
  DevicesScreen, TopologyScreen; channel name on public MQTT). `long_name="[/"`
  → `MarkupError` on every render → the Nodes screen is permanently "Render
  error" while the node is in the DB (one packet = persistent DoS). Apply the
  existing `rich_escape()` to all network-derived strings placed in Table/Tree/
  Panel-title. (SEC-16 escaping on two screens confirms these strings reach the
  render path unsanitized.)
- **PLAUSIBLE HIGH — bot config editor materializes template defaults (incl.
  commented-out example keys) into the live config on save** (`_merge_template_
  defaults`/`_save`) — the #62 saved-defaults trap; commented examples become
  live bot behavior, template-default bumps freeze. Exclude `_template_keys`
  from the write.
- **PLAUSIBLE MED-HIGH — header/footer render exception freezes the whole
  display at the last frame, presented as live** (no staleness indicator);
  `_render`'s guard doesn't wrap `_get_header/_get_footer`.
- **PLAUSIBLE MED — whiptail TUI crashes the whole app on one partial node**
  (`node.role.value`/`snr` formatting on `None`); ANSI injection in the
  plain-text fallback; silent config coercion to defaults with no witness (a
  corrupt `mesh_client.ini` silently reconnects to the *public* broker); secrets
  rendered unmasked; non-atomic config writes; bare `int()` in
  `from_upstream`; IPv6 broker mangled by `rsplit(":",1)`.

*(Full reviewer detail with line numbers was captured in the session transcript;
this file is the durable triage list.)*

## Crypto fix — field-test result (2026-07-16, same session)

**VERIFIED interoperable at the Meshtastic wire-format level.** The fixed
derivation was exercised through the module's own consumer of record
(`MeshPacketProcessor.process_encrypted_packet`) against ciphertext produced by
the exact firmware algorithm — AES-128-CTR, 16-byte default channel key
`d4f1bb3a20290759f0bcffabcf4e6901`, nonce = `packetId(8 LE) ‖ from(4 LE) ‖
0(4)` — wrapped in a real `ServiceEnvelope`:

- **FIXED derivation: 3/3** default-channel packets decoded to a valid `Data`
  with the correct plaintext.
- **OLD derivation (SHA-256 → AES-256): 0/3** — could not decode wire-format
  AES-128 ciphertext. The fix is load-bearing, not cosmetic.

This also exercised (and confirmed) the module's envelope-parse +
`from`/`id`/`channel` extraction on real captured `ServiceEnvelope` bytes (60
live packets pulled from `mqtt.meshtastic.org` parsed cleanly).

**Residual gap (honest):** no packet encrypted-and-transmitted by a physical
radio over RF was decrypted this session — the public broker carries only
*decoded* default-channel traffic (gateways republish plaintext), and the
operator's local broker carried only the private `meshforge` channel (custom
PSK, not in the client config) and PKI traffic, with no live default-channel
`/e/` packets. The wire-format reference test is the faithful stand-in: it runs
the identical algorithm a radio uses. To fully close the gap, decrypt one live
default-channel `/e/` packet from a radio that has MQTT encryption enabled (or
the operator's `meshforge` channel with its PSK) through the module.

The `/json/` path (meshtasticd pre-decrypted) is unaffected by this fix either
way.
- The TUI Rich-markup-injection finding (PLAUSIBLE HIGH) is the highest-value
  unfixed item: a single hostile NodeInfo packet can persistently DoS the
  operator's primary node view. Good candidate for the next pass.

# TrailCam Automation TODO


# In progress refactor of src/flows.py (item 1)

Phased execution plan

 ### Phase 0 — safety net first (done)

 1. Add/confirm tests around current behavior used by sync path:
 - media list normalization
 - video header/decrypt helpers
 - any current pcap regression tests
 2. Snapshot current signatures used by callers (sync_runner, command modules).

 Exit criteria: tests green before refactor.

 ────────────────────────────────────────────────────────────────────────────────

 ### Phase 1 — mechanical split (no behavior change) (done)

 1. Create src/flows/ package.
 2. Move code in chunks:
 - list/normalize helpers → media_list.py
 - photo flow function(s) → photo_download.py
 - video flow function(s) + internal helpers → video_download.py
 - extraction helpers → extract.py
 3. Keep compatibility:
 - src/flows/__init__.py re-exports old function names.
 - keep src/flows.py as a thin shim import/re-export during transition (optional but safest).

 Exit criteria: all existing imports still work; tests unchanged and green.

 ────────────────────────────────────────────────────────────────────────────────

 ### Phase 2 — untangle internal coupling (done)

 1. Move shared constants/helpers into common.py.
 2. Reduce cross-imports between video/photo modules.
 3. Isolate stream-state structures (ack counters, seq windows) into small dataclasses.

 Exit criteria: no circular imports, cleaner boundaries, behavior same.

 ────────────────────────────────────────────────────────────────────────────────

 ### Phase 3 — caller cleanup

 1. Update callers to import from new package paths directly.
 2. Remove shim (src/flows.py) once all callsites are migrated.

 Exit criteria: repo no longer depends on monolithic file.

### Phase 4 — optional behavior improvements (post-split)

 Only after stable split:
 - stage-specific retry hooks
 - better error taxonomy
 - packet processing simplification

 ────────────────────────────────────────────────────────────────────────────────

 Risk controls

 - No logic changes during Phase 1–2 (move-only discipline).
 - Commit in small slices (one subsystem per commit).
 - Run tests after each slice.
 - Keep fallback shim until the very end.



 Suggested commit sequence

 1. test(flows): add guardrail tests for split
 2. refactor(flows): introduce flows package and compatibility exports
 3. refactor(flows): move media-list helpers
 4. refactor(flows): move photo download flow
 5. refactor(flows): move video flow + extraction helpers
 6. refactor(flows): migrate imports and remove legacy shim





-----
-----




## ColumnsBot refactoring suggestions

### Biggest opportunities (in priority order)

1. Split src/flows.py (very high impact)
 - It’s currently the biggest hotspot (~1200 LOC, one function ~466 LOC).
 - It’s doing too many jobs: protocol heartbeats/acks, media transfer orchestration, parsing, file output.
 - Refactor into:
 - transport/ (ack/heartbeat/session packet IO)
 - download/ (photo/video orchestration)
 - parsers/ (ARTEMIS + record decoding)
 - This will reduce bug surface and make retry logic easier to reason about.

2. Break up src/config.py (high impact)
 - Also large (~600 LOC), with a heavy load_config.
 - Split into:
 - schema/dataclasses
 - parsing/coercion
 - validation rules
 - Right now config evolution is expensive and easy to regress.

3. Formalize sync state transitions (high impact)
 - Status transitions are spread around with string checks/dict mutation.
 - Introduce a transition layer (pending -> download -> verify -> clear -> organize -> done/error) with guards.
 - Benefits: fewer edge-case bugs, easier retries/recovery, cleaner telemetry.

4. Retire/relocate notifier module usage (medium)
 - Python app no longer owns alerting; notifier is now wrapper-owned utility.
 - Either:
 - keep EmailNotifier as explicit “ops utility”, or
 - move scheduled outcome email send into a small dedicated CLI module and keep shell wrapper minimal.
 - This removes “half in shell / half in app” ambiguity.

5. Reduce hardcoded paths in scripts/systemd workflow (medium)
 - A lot of /home/pwnb0t/g/trailcam-automation assumptions.
 - Consider templated install + dynamic repo root discovery.
 - Makes host migrations less brittle.

6. Improve retry/error taxonomy (medium)
 - Standardize exception types by stage (connect/list/download/verify/clear/organize).
 - Then retries can be stage-aware (retry transient network, fail-fast on deterministic format issues).

-----

 ### Quick wins (low effort, good return)

 - Update TODO.md to reflect completed notification architecture work (it’s stale now).
 - Add a small “sync outcome email policy” doc (docs/alerts.md) so behavior is explicit.
 - Add tests for the new notification contract (scheduled success/final failure path).



-----


# Future ideas

## Retry strategy for media download failures
- Document current retry flow clearly:
  - in-app retry behavior
  - systemd/service-level retry behavior
- Evaluate whether bad/partial media should trigger:
  - re-request of item/chunk within run, or
  - full run retry only
- Tune retry counts/backoff for both layers to reduce false terminal failures.
- Keep strict validation where it protects data integrity, but avoid failing the whole run for recoverable single-item issues when possible.

## Retry/failure observability and stats
- Add per-host retry metrics (`petepad`, `piiter`).


-----

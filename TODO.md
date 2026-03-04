# TrailCam Automation TODO

## 2) Retry strategy for media download failures
- Document current retry flow clearly:
  - in-app retry behavior
  - systemd/service-level retry behavior
- Evaluate whether bad/partial media should trigger:
  - re-request of item/chunk within run, or
  - full run retry only
- Tune retry counts/backoff for both layers to reduce false terminal failures.
- Keep strict validation where it protects data integrity, but avoid failing the whole run for recoverable single-item issues when possible.

## 3) Retry/failure observability and stats
- Add per-host retry metrics (`petepad`, `piiter`).


-----

# ColumnsBot refactoring suggestions


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

 If you want, I can turn this into a concrete Refactor Plan v1 with 2-week phases (safe first, then deeper architecture) and start with the top quick win set.

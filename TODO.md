# TrailCam Automation TODO

## ColumnsBot refactoring suggestions

### Biggest opportunities (in priority order)

1. Break up src/config.py (high impact)
 - Also large (~600 LOC), with a heavy load_config.
 - Split into:
 - schema/dataclasses
 - parsing/coercion
 - validation rules
 - Right now config evolution is expensive and easy to regress.

Notes: We must make sure we plan this one out. The idea behind the config was supposed to be:
* Having strongly typed classes to represent the config file rather than loose calls like `cfg.undefined_dict.undefined_var`
* The Session is supposed to be easy to pass around and contain all the stuff for the running session to make it easy.
  * Before, every method call had a pile of arguments (anywhere from a handful to a dozen).
  * The session and config are supposed to be like context classes that provide the exact configuration and state of the app
  * Most arguments were just config items, or possibly a runtime setup item (like login_token_u32)
  * It made calls like: `DownloadMediaPageCommand(session)` much more simplified
  * The Config is supposed to have a similar purpose as Session, but it's just the "cold setup" items (config file and overrides)
* We could consider just going back a loosely defined Config
* We could consider using dependency-injector like we did with the `ownbot` project

2. Formalize sync state transitions (high impact)
 - Status transitions are spread around with string checks/dict mutation.
 - Introduce a transition layer (pending -> download -> verify -> clear -> organize -> done/error) with guards.
 - Benefits: fewer edge-case bugs, easier retries/recovery, cleaner telemetry.

3. Retire/relocate notifier module usage (medium)
 - Python app no longer owns alerting; notifier is now wrapper-owned utility.
 - Either:
 - keep EmailNotifier as explicit “ops utility”, or
 - move scheduled outcome email send into a small dedicated CLI module and keep shell wrapper minimal.
 - This removes “half in shell / half in app” ambiguity.

4. Reduce hardcoded paths in scripts/systemd workflow (medium)
 - A lot of /home/pwnb0t/g/trailcam-automation assumptions.
 - Consider templated install + dynamic repo root discovery.
 - Makes host migrations less brittle.

5. Improve retry/error taxonomy (medium)
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

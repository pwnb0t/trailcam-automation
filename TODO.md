# TrailCam Automation TODO

## 1) Alerting: notify only on terminal failure
- [ ] Stop sending email for intermediate/transient failures.
- [ ] Send email only when a sync run exhausts all configured retries and still fails.
- [ ] Decide alert owner:
  - Option A: move failure notification to systemd service wrapper (preferred candidate)
  - Option B: keep in sync app but gate on final-attempt context
- [ ] Include failure summary in alert (host, camera, stage, last error, retry count).

## 2) Retry strategy for media download failures
- [ ] Document current retry flow clearly:
  - in-app retry behavior
  - systemd/service-level retry behavior
- [ ] Evaluate whether bad/partial media should trigger:
  - re-request of item/chunk within run, or
  - full run retry only
- [ ] Tune retry counts/backoff for both layers to reduce false terminal failures.
- [ ] Keep strict validation where it protects data integrity, but avoid failing the whole run for recoverable single-item issues when possible.

## 3) Retry/failure observability and stats
- [ ] Add per-host retry metrics (`petepad`, `piiter`).
- [ ] Track retry rates by stage (list, photo download, video download, organize, etc.).
- [ ] Capture counts for:
  - first-pass success
  - recovered by in-app retry
  - recovered by service retry
  - terminal failures
- [ ] Produce a simple daily/weekly summary to guide tuning decisions.

## 4) Ops stopgap retirement plan
- [ ] Keep noon status check while retry/alerting is being improved.
- [ ] Remove or reduce noon check once terminal-failure-only alerting is reliable.

## 5) Final media naming: datetime-first + camera suffix
- [ ] Change final filename format to: `YYYY-MM-DD_HH-MM-SS_<back|front>.<ext>`.
- [ ] Ensure lexicographic sort matches chronological order across all final media.
- [ ] Remove `dirNum` and `mediaNum` from final filenames (no longer needed in organized output).
- [ ] Place camera alias at the end of basename so date/time stays first for sorting.

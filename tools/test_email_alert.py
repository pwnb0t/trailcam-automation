#!/usr/bin/env python3
from __future__ import annotations

import argparse
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Allow running as `python3 tools/test_email_alert.py` by adding repo root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.notify.email_notifier import EmailNotifier


def _resolve_config_path(explicit: Optional[str]) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise SystemExit(f"--config path does not exist: {p}")
        return p
    for name in ("config.yaml", "config.yml"):
        p = Path(name)
        if p.exists():
            return p
    raise SystemExit(
        "No config file found. Create config.yaml (see config.example.yaml), "
        "or pass --config /path/to/config.yaml"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Send a test TrailCam email alert using alerts.email config.")
    p.add_argument("--config", default=None, help="Path to config.yaml/config.yml (default: auto-detect)")
    p.add_argument("--subject", default=None, help="Override test email subject")
    p.add_argument("--body", default=None, help="Override test email body")
    p.add_argument(
        "--enable-temp",
        action="store_true",
        help="Temporarily force alerts.email.enabled=true for this test run",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    cfg_path = _resolve_config_path(args.config)
    app_cfg = load_config(cfg_path)
    email_cfg = app_cfg.alerts.email

    if not email_cfg.enabled and not args.enable_temp:
        raise SystemExit(
            "alerts.email.enabled is false. Set it true in config, or run with --enable-temp for a one-off test."
        )

    if args.enable_temp and not email_cfg.enabled:
        from dataclasses import replace

        email_cfg = replace(email_cfg, enabled=True)

    notifier = EmailNotifier(email_cfg)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    host = socket.gethostname()
    subject = args.subject or f"{email_cfg.subject_prefix} test email"
    body = args.body or (
        "This is a test TrailCam alert email.\n"
        f"Time (UTC): {now}\n"
        f"Host: {host}\n"
        f"Config: {cfg_path}\n"
    )

    notifier.send_message(subject=subject, body=body)
    print(f"Sent test email to: {', '.join(email_cfg.to_emails) or '(none)'}")


if __name__ == "__main__":
    main()


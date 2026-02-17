from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Optional

from src.config import EmailAlertsConfig


class EmailNotifier:
    def __init__(self, cfg: EmailAlertsConfig):
        self.cfg = cfg

    def send_message(self, *, subject: str, body: str) -> None:
        if not self.cfg.enabled:
            print("Email alerts disabled (alerts.email.enabled=false); skipping send")
            return
        if not self.cfg.to_emails:
            print("Email alerts enabled but alerts.email.to_emails is empty; skipping send")
            return
        if not self.cfg.smtp_user or not self.cfg.smtp_app_password:
            print("Email alerts enabled but smtp_user/smtp_app_password missing; skipping send")
            return

        from_email = self.cfg.from_email or self.cfg.smtp_user
        msg = EmailMessage()
        msg["From"] = from_email
        msg["To"] = ", ".join(self.cfg.to_emails)
        msg["Subject"] = subject
        msg.set_content(body)

        if int(self.cfg.smtp_port) == 465:
            with smtplib.SMTP_SSL(self.cfg.smtp_host, int(self.cfg.smtp_port), timeout=20) as smtp:
                smtp.login(self.cfg.smtp_user, self.cfg.smtp_app_password)
                smtp.send_message(msg)
            return

        with smtplib.SMTP(self.cfg.smtp_host, int(self.cfg.smtp_port), timeout=20) as smtp:
            if self.cfg.starttls:
                smtp.starttls()
            smtp.login(self.cfg.smtp_user, self.cfg.smtp_app_password)
            smtp.send_message(msg)

    def enabled_for_failure(self) -> bool:
        return bool(self.cfg.enabled) and ("failure" in {x.lower() for x in self.cfg.notify_on})

    def send_failure(self, *, camera_alias: str, error: str, details: Optional[str] = None) -> None:
        if not self.enabled_for_failure():
            return

        subject = f"{self.cfg.subject_prefix} camera={camera_alias} status=FAILED"
        body_lines = [
            f"Camera: {camera_alias}",
            f"Error: {error}",
        ]
        if details:
            body_lines.extend(["", "Details:", details])
        self.send_message(subject=subject, body="\n".join(body_lines))

"""Local CRM-event persistence and email notification adapter.

This is a demo adapter, not a bank CRM integration or a real transfer service.
"""
import json
import os
import smtplib
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"), override=False)
CRM_FILE = Path(__file__).with_name("crm_events.jsonl")


def save_crm_event(event: dict) -> dict:
    record = {
        **(event or {}),
        "event_id": str(uuid.uuid4()),
        "call_id": (event or {}).get("call_id") or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    CRM_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CRM_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def send_followup_email(record: dict) -> bool:
    """Send an internal notification; returns False when SMTP is not configured."""
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME") or os.getenv("GMAIL_ADDRESS")
    password = os.getenv("SMTP_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("FOLLOWUP_EMAIL_TO") or os.getenv("NOTIFICATION_EMAIL")
    if not all([username, password, recipient]):
        return False

    outcome = str(record.get("outcome_type") or record.get("outcome") or "FOLLOW_UP")
    subject = f"Collections voicebot follow-up: {outcome}"
    body = (
        "A collections voicebot follow-up event was recorded.\\n\\n"
        f"Event ID: {record.get('event_id', 'n/a')}\\n"
        f"Call ID: {record.get('call_id', 'n/a')}\\n"
        f"Outcome: {outcome}\\n"
        f"Reason: {record.get('reason', 'n/a')}\\n"
        f"Callback preference: {record.get('callback_time', 'n/a')}\\n"
        f"Customer statement: {record.get('customer_statement', 'n/a')}\\n"
        "\\nDemo notification only. This is not proof of a scheduled callback or completed human transfer."
    )
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = recipient
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)
        return True
    except Exception:
        return False


def send_escalation_email(record: dict) -> bool:
    return send_followup_email(record)

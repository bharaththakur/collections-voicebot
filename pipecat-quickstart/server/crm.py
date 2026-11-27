
import json
import os
import smtplib
import uuid

from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from dotenv import load_dotenv


CRM_FILE = Path(__file__).with_name("crm_events.jsonl")
load_dotenv(Path(__file__).with_name(".env"), override=True)


def save_crm_event(event: dict) -> dict:
    """
    Persist one structured call outcome or escalation event.
    Each event is stored as one JSON line.
    """

    record = {
        **event,
        "event_id": str(uuid.uuid4()),
        "call_id": event.get("call_id") or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with CRM_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record


def send_followup_email(record: dict) -> bool:
    """
    Send an internal notification for a human follow-up or callback.
    Returns False if configuration or delivery fails.
    """

    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_APP_PASSWORD")
    alert_email = os.getenv("ALERT_EMAIL")

    if not all([smtp_user, smtp_password, alert_email]):
        print("Email not sent: SMTP configuration is incomplete.")
        return False

    outcome = record.get("outcome", "HUMAN_FOLLOWUP")
    reason = record.get("reason", "Customer follow-up")

    if outcome == "CALLBACK_REQUEST":
        subject = "Collections Voicebot: Callback Requested"

        body = (
            "A callback request was captured by the Mumbai Bank "
            "Collections Voicebot.\n\n"
            f"Call ID: {record.get('call_id')}\n"
            f"Timestamp: {record.get('timestamp')}\n"
            f"Requested callback time: {record.get('callback_time')}\n"
            f"Customer statement: {record.get('customer_statement')}\n"
        )

    else:
        subject = f"Collections Voicebot Escalation: {reason}"

        body = (
            "A human escalation was raised by the Mumbai Bank "
            "Collections Voicebot.\n\n"
            f"Call ID: {record.get('call_id')}\n"
            f"Timestamp: {record.get('timestamp')}\n"
            f"Outcome: {outcome}\n"
            f"Reason: {reason}\n"
            f"Customer statement: {record.get('customer_statement')}\n\n"
            "Triggering customer statement:\n"
            f"{record.get('transcript', 'Not available')}\n"
        )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_user
    message["To"] = alert_email
    message.set_content(body)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)

        return True

    except Exception as exc:
        print(
            f"Follow-up email delivery failed: "
            f"{type(exc).__name__}: {exc}"
        )
        return False


def send_escalation_email(record: dict) -> bool:
    """
    Backward-compatible wrapper for existing escalation calls.
    """

    return send_followup_email(record)

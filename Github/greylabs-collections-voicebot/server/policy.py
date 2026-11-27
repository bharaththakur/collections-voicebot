"""Deterministic policy guardrails for the collections voicebot prototype."""
from dataclasses import dataclass
from enum import Enum
import re


class Intent(str, Enum):
    JOB_LOSS = "job_loss"
    MEDICAL_EMERGENCY = "medical_emergency"
    ABUSE = "abuse"
    ALREADY_PAID = "already_paid"
    WAIVER_REQUEST = "waiver_request"
    CALLBACK_REQUEST = "callback_request"
    DISPUTE = "dispute"
    BALANCE_REQUEST = "balance_request"
    OTHER_PRODUCT = "other_product"
    PROMISE_TO_PAY = "promise_to_pay"
    UNABLE_TO_PAY = "unable_to_pay"
    GENERAL = "general"


class Action(str, Enum):
    ESCALATE = "escalate_to_human"
    CAPTURE_ALREADY_PAID = "capture_already_paid"
    CAPTURE_WAIVER = "capture_waiver"
    CAPTURE_CALLBACK = "capture_callback"
    CAPTURE_DISPUTE = "capture_dispute"
    REFUSE_BALANCE_DISCLOSURE = "refuse_balance_disclosure"
    DECLINE_OTHER_PRODUCT = "decline_other_product"
    CAPTURE_PTP = "capture_ptp"
    CLARIFY_HARDSHIP = "clarify_hardship"
    CONTINUE = "continue"


@dataclass
class PolicyDecision:
    intent: Intent
    action: Action
    reason: str


def _has(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


PATTERNS = {
    Intent.JOB_LOSS: (r"\blost my job\b", r"\bjob loss\b", r"\bgot laid off\b", r"\bunemployed\b"),
    Intent.MEDICAL_EMERGENCY: (r"\bmedical emergency\b", r"\bin (?:the )?hospital\b", r"\bicu\b", r"\bserious illness\b"),
    Intent.ABUSE: (r"\b(?:fuck|shit|bastard|idiot)\b", r"\b(?:abusive|abuse)\b"),
    Intent.ALREADY_PAID: (r"\balready paid\b", r"\bmade the payment\b", r"\bpayment is done\b", r"\bpaid it\b"),
    Intent.WAIVER_REQUEST: (r"\bwaiv(?:er|e)\b", r"\bremove (?:the )?late fee\b", r"\breverse (?:the )?charges\b"),
    Intent.CALLBACK_REQUEST: (r"\bcall me back\b", r"\bcallback\b", r"\bcall back\b", r"\bring me later\b"),
    Intent.DISPUTE: (r"\bdisput(?:e|ed|ing)\b", r"\bnot my transaction\b", r"\bwrong amount\b", r"\bdon't owe\b"),
    Intent.BALANCE_REQUEST: (r"\bhow much (?:do i owe|is outstanding)\b", r"\bmy balance\b", r"\boutstanding balance\b"),
    Intent.OTHER_PRODUCT: (r"\bpersonal loan\b", r"\bhome loan\b", r"\bother product\b", r"\bloan offer\b"),
    Intent.UNABLE_TO_PAY: (r"\bcan't pay\b", r"\bcannot pay\b", r"\bunable to pay\b", r"\bnot sure i can pay\b"),
    Intent.PROMISE_TO_PAY: (r"\bi will pay\b", r"\bi'll pay\b", r"\bpay tomorrow\b", r"\bpay on\b"),
}


def classify_message(message: str, awaiting_callback_time: bool = False) -> PolicyDecision:
    text = (message or "").strip().lower()

    # Safety and vulnerability triggers always take priority.
    priority = [
        (Intent.JOB_LOSS, Action.ESCALATE),
        (Intent.MEDICAL_EMERGENCY, Action.ESCALATE),
        (Intent.ABUSE, Action.ESCALATE),
    ]
    for intent, action in priority:
        if _has(text, PATTERNS[intent]):
            return PolicyDecision(intent, action, f"Mandatory escalation trigger: {intent.value}")

    if awaiting_callback_time:
        # Callback-time parsing is intentionally conservative: this prototype
        # accepts a non-empty customer utterance; production needs date/time parsing.
        return PolicyDecision(Intent.CALLBACK_REQUEST, Action.CAPTURE_CALLBACK,
                              "Customer supplied a callback preference while awaiting callback time.")

    ordered = [
        (Intent.ALREADY_PAID, Action.CAPTURE_ALREADY_PAID),
        (Intent.WAIVER_REQUEST, Action.CAPTURE_WAIVER),
        (Intent.CALLBACK_REQUEST, Action.CAPTURE_CALLBACK),
        (Intent.DISPUTE, Action.CAPTURE_DISPUTE),
        (Intent.BALANCE_REQUEST, Action.REFUSE_BALANCE_DISCLOSURE),
        (Intent.OTHER_PRODUCT, Action.DECLINE_OTHER_PRODUCT),
        (Intent.UNABLE_TO_PAY, Action.CLARIFY_HARDSHIP),
        (Intent.PROMISE_TO_PAY, Action.CAPTURE_PTP),
    ]
    for intent, action in ordered:
        if _has(text, PATTERNS[intent]):
            return PolicyDecision(intent, action, f"Matched intent: {intent.value}")

    return PolicyDecision(Intent.GENERAL, Action.CONTINUE, "No deterministic policy trigger matched.")


def validate_outcome(outcome: dict) -> tuple[bool, str]:
    """Validate required fields for the supported structured outcomes."""
    kind = (outcome or {}).get("outcome_type") or (outcome or {}).get("outcome")
    required = {
        "PTP": ("payment_date", "payment_amount"),
        "Already-Paid": ("payment_date", "payment_mode"),
        "CALLBACK_REQUEST": ("callback_time",),
        "Callback-Request": ("callback_time",),
        "Dispute": ("reason",),
        "Transfer-to-Human": ("reason",),
    }
    fields = required.get(kind)
    if fields is None:
        return False, f"Unsupported outcome type: {kind}"
    missing = [field for field in fields if not str(outcome.get(field, "")).strip()]
    if missing:
        return False, "Missing required field(s): " + ", ".join(missing)
    return True, "Outcome contains the required fields."

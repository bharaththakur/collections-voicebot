
"""
Mumbai Bank Collections Voicebot
Deterministic policy and outcome validation engine.

The LLM handles natural conversation.
This module identifies policy-sensitive inputs and validates outcomes.
"""

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any


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
    CAPTURE_WAIVER = "capture_waiver_request"
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
    requires_human: bool = False


# ---------------------------------------------------------
# POLICY PATTERNS
# ---------------------------------------------------------

JOB_LOSS_PATTERNS = [
    r"\blost my job\b",
    r"\bjob loss\b",
    r"\bmade redundant\b",
    r"\blaid off\b",
    r"\bgot laid off\b",
    r"\bgot fired\b",
    r"\bwas fired\b",
    r"\bterminated from my job\b",
    r"\bunemployed\b",
    r"\bno longer employed\b",
    r"\bcompany let me go\b",
    r"\bcompany has let me go\b",
]

MEDICAL_PATTERNS = [
    r"\bmedical emergency\b",
    r"\bhospital emergency\b",
    r"\bmedical crisis\b",
    r"\bserious medical condition\b",
    r"\bcritical condition\b",
    r"\bin the hospital\b",
    r"\bemergency surgery\b",
]

ABUSE_PATTERNS = [
    r"\bfuck you\b",
    r"\bshut up\b",
    r"\bgo to hell\b",
    r"\bidiot\b",
    r"\bstupid\b",
    r"\bmotherfucker\b",
]

# General inability to pay is not automatically job loss.
UNABLE_TO_PAY_PATTERNS = [
    r"\bcannot pay\b",
    r"\bcan't pay\b",
    r"\bunable to pay\b",
    r"\bcan't afford\b",
    r"\bcannot afford\b",
    r"\bno money\b",
    r"\bshort of money\b",
]

WAIVER_PATTERNS = [
    r"\bwaive\b",
    r"\bwaiver\b",
    r"\bremove the late fee\b",
    r"\breverse the late fee\b",
    r"\binterest reversal\b",
    r"\bfee reversal\b",
]

BALANCE_PATTERNS = [
    r"\bwhat is my (current )?(due|balance)\b",
    r"\bhow much do i owe\b",
    r"\boutstanding balance\b",
    r"\baccount balance\b",
    r"\bcurrent outstanding\b",
]

OTHER_PRODUCT_PATTERNS = [
    r"\bpersonal loan\b",
    r"\bhome loan\b",
    r"\bcar loan\b",
    r"\binsurance product\b",
    r"\bother products\b",
    r"\bnew credit card\b",
]

DISPUTE_PATTERNS = [
    r"\bdispute\b",
    r"\bwrong charge\b",
    r"\bincorrect amount\b",
    r"\bnot my transaction\b",
    r"\bfraudulent transaction\b",
    r"\bunauthorised transaction\b",
    r"\bunauthorized transaction\b",
]

ALREADY_PAID_PATTERNS = [
    r"\balready paid\b",
    r"\bi have paid\b",
    r"\bi've paid\b",
    r"\bpayment is done\b",
    r"\bmade the payment\b",
    r"\bpayment was made\b",
]

CALLBACK_PATTERNS = [
    r"\bcall me later\b",
    r"\bcall back\b",
    r"\bcall me back\b",
    r"\bcallback\b",
    r"\bnot a good time\b",
    r"\bnot convenient\b",
    r"\bbusy right now\b",
    r"\b(schedule|arrange|request)\s+(a\s+)?callback\b",
]

# These patterns are only used when the conversation is
# explicitly waiting for the customer's callback preference.
CALLBACK_TIME_PATTERNS = [
    r"\btomorrow\b",
    r"\btoday\b",
    r"\bthis evening\b",
    r"\bthis afternoon\b",
    r"\bnext week\b",
    r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b",
    r"\b\d{1,2}\s*(in the morning|in the afternoon|in the evening)\b",
]

PTP_PATTERNS = [
    r"\bi will pay\b",
    r"\bi'll pay\b",
    r"\bwill make the payment\b",
    r"\bpay on\b",
    r"\bpay by\b",
    r"\bpay tomorrow\b",
]


# ---------------------------------------------------------
# MATCHING HELPER
# ---------------------------------------------------------

def _matches(text: str, patterns: list[str]) -> bool:
    """Return True if any pattern matches the input."""
    return any(re.search(pattern, text) for pattern in patterns)


# ---------------------------------------------------------
# MESSAGE CLASSIFICATION
# ---------------------------------------------------------

def classify_message(
    message: str,
    awaiting_callback_time: bool = False,
) -> PolicyDecision:
    """
    Classify customer input.

    Priority:
    1. Safety escalation
    2. Callback scheduling context
    3. Other customer intents
    4. General conversation

    awaiting_callback_time must only be True when the
    conversation state confirms that the bot is collecting
    a callback date/time from the customer.
    """

    text = message.lower().strip()

    if not text:
        return PolicyDecision(
            Intent.GENERAL,
            Action.CONTINUE,
            "Empty or unclear input.",
        )

    # 1. Immediate escalation conditions.
    # These always take priority over ordinary intents.

    if _matches(text, JOB_LOSS_PATTERNS):
        return PolicyDecision(
            Intent.JOB_LOSS,
            Action.ESCALATE,
            "Customer disclosed job loss or unemployment.",
            True,
        )

    if _matches(text, MEDICAL_PATTERNS):
        return PolicyDecision(
            Intent.MEDICAL_EMERGENCY,
            Action.ESCALATE,
            "Customer disclosed a medical emergency.",
            True,
        )

    if _matches(text, ABUSE_PATTERNS):
        return PolicyDecision(
            Intent.ABUSE,
            Action.ESCALATE,
            "Abusive language detected.",
            True,
        )

    # 2. Callback scheduling context.
    # A date/time is a callback preference only when the
    # conversation is explicitly collecting one.

    if awaiting_callback_time and _matches(
        text, CALLBACK_TIME_PATTERNS
    ):
        return PolicyDecision(
            Intent.CALLBACK_REQUEST,
            Action.CAPTURE_CALLBACK,
            "Customer provided a callback scheduling preference.",
        )

    # 3. Other customer intents.

    if _matches(text, ALREADY_PAID_PATTERNS):
        return PolicyDecision(
            Intent.ALREADY_PAID,
            Action.CAPTURE_ALREADY_PAID,
            "Customer says payment has already been made.",
        )

    if _matches(text, WAIVER_PATTERNS):
        return PolicyDecision(
            Intent.WAIVER_REQUEST,
            Action.CAPTURE_WAIVER,
            "Customer requested a fee or interest waiver.",
        )

    if _matches(text, CALLBACK_PATTERNS):
        return PolicyDecision(
            Intent.CALLBACK_REQUEST,
            Action.CAPTURE_CALLBACK,
            "Customer requested a callback.",
        )

    if _matches(text, DISPUTE_PATTERNS):
        return PolicyDecision(
            Intent.DISPUTE,
            Action.CAPTURE_DISPUTE,
            "Customer disputed the payment or transaction.",
        )

    if _matches(text, BALANCE_PATTERNS):
        return PolicyDecision(
            Intent.BALANCE_REQUEST,
            Action.REFUSE_BALANCE_DISCLOSURE,
            "Balance disclosure requires OTP verification.",
        )

    if _matches(text, OTHER_PRODUCT_PATTERNS):
        return PolicyDecision(
            Intent.OTHER_PRODUCT,
            Action.DECLINE_OTHER_PRODUCT,
            "Request is outside the collections scope.",
        )

    if _matches(text, UNABLE_TO_PAY_PATTERNS):
        return PolicyDecision(
            Intent.UNABLE_TO_PAY,
            Action.CLARIFY_HARDSHIP,
            "Customer expressed inability to pay; reason is unclear.",
        )

    if _matches(text, PTP_PATTERNS):
        return PolicyDecision(
            Intent.PROMISE_TO_PAY,
            Action.CAPTURE_PTP,
            "Customer expressed an intention to pay.",
        )

    return PolicyDecision(
        Intent.GENERAL,
        Action.CONTINUE,
        "No specific policy intent detected.",
    )


# ---------------------------------------------------------
# STRUCTURED OUTCOME VALIDATION
# ---------------------------------------------------------

def validate_outcome(
    outcome: dict[str, Any]
) -> tuple[bool, str]:
    """
    Validate structured outcomes before CRM submission.

    Required fields:
    PTP: date + amount
    Already-Paid: payment date + payment mode
    Callback-Request: callback time
    Dispute / Transfer-to-Human: reason
    """

    outcome_type = outcome.get("outcome_type")

    if outcome_type == "PTP":
        if not outcome.get("date"):
            return False, "PTP requires a payment date."

        if outcome.get("amount") is None:
            return False, "PTP requires a payment amount."

        try:
            amount = float(outcome["amount"])

            if amount <= 0:
                return False, "PTP amount must be greater than zero."

        except (ValueError, TypeError):
            return False, "PTP amount must be numeric."

        return True, "PTP outcome is valid."

    if outcome_type == "Already-Paid":
        if not outcome.get("payment_date"):
            return False, "Already-Paid requires a payment date."

        if not outcome.get("payment_mode"):
            return False, "Already-Paid requires a payment mode."

        return True, "Already-Paid outcome is valid."

    if outcome_type == "Callback-Request":
        if not outcome.get("callback_time"):
            return False, "Callback-Request requires a callback time."

        return True, "Callback outcome is valid."

    if outcome_type in ("Dispute", "Transfer-to-Human"):
        if not outcome.get("reason"):
            return False, f"{outcome_type} requires a reason."

        return True, f"{outcome_type} outcome is valid."

    return False, "Unknown or unsupported outcome type."

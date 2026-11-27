
import os
import sys

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner

from policy import classify_message, validate_outcome
from crm import (
    save_crm_event,
    send_escalation_email,
    send_followup_email,
)
import uuid


# ---------------------------------------------------------
# 1. ENVIRONMENT
# ---------------------------------------------------------

load_dotenv(override=True)

REQUIRED_ENV_VARS = [
    "DEEPGRAM_API_KEY",
    "OPENAI_API_KEY",
    "CARTESIA_API_KEY",
]

missing = [key for key in REQUIRED_ENV_VARS if not os.getenv(key)]

if missing:
    raise RuntimeError(
        f"Missing required environment variables: {', '.join(missing)}"
    )


# ---------------------------------------------------------
# 2. BANK POLICY / SYSTEM PROMPT
# ---------------------------------------------------------

SYSTEM_PROMPT = """
You are an outbound credit-card collections voice assistant
calling on behalf of Mumbai Bank.

YOUR PURPOSE
Contact credit-card customers whose payments are 1–30 days overdue.
Help them resolve the pending payment or record the appropriate outcome.

COMMUNICATION RULES
- Speak only in English.
- Customers may speak English, Hindi, or Hinglish.
- Understand Hindi and Hinglish, but always respond in English.
- Use short, natural, conversational sentences.
- Ask one question at a time.
- Be respectful, calm, and non-threatening.
- Aim to complete the call within 2–3 minutes.
- Never invent customer information.
- Never pretend to be a human agent.

BANK FACTS
- Credit-card interest: 3.5% per month.
- Late fee: ₹750 when the outstanding balance exceeds ₹10,000.
- Never disclose an account balance without OTP verification.
- This demo has no OTP verification capability. Therefore, do not
  disclose account balances.
- Never mention CIBIL scores or predict credit scores.
- Never threaten legal action or provide legal advice.
- Never offer discounts or approve fee/interest waivers.
- Never invent bank policies, payment channels, or operating hours.

REQUIRED CONVERSATION FLOWS

1. PROMISE TO PAY (PTP)
Capture:
- Payment date.
- Payment amount.

Both fields are mandatory.
If either is missing, ask for the missing information.
Repeat the date and amount and ask the customer to confirm.
Do not invent either value.

2. ALREADY PAID
Ask:
- When was the payment made?
- What payment mode was used?

Once both details are captured, say:
"Thank you. The payment should reflect in our records
within 2 working days."

Do not claim that the payment has been verified.

3. LATE-FEE OR INTEREST WAIVER
You cannot approve or promise a waiver.
Acknowledge the request and explain that a human agent
will follow up.
Do not promise a specific callback time.

4. CALLBACK REQUEST
If the customer requests a callback:
- Ask for their preferred callback date and time.
- Do not claim the request has been recorded before application confirmation.
- Do not invent callback operating hours.
- Do not claim that an appointment has been booked.
- Only confirm a recorded request when the application confirms CRM persistence.

5. DISPUTE
If the customer disputes the payment, amount, or transaction,
stop the collections pitch and arrange human follow-up.
Capture the reason.

6. JOB LOSS, MEDICAL EMERGENCY OR ABUSE
Stop the collections pitch immediately.
Do not ask for a payment commitment.
Do not pressure the customer.
Escalate to a human agent.

7. BALANCE REQUEST
Do not reveal the balance without OTP verification.
This demo does not implement OTP verification.
Explain that you cannot disclose the balance during this call.

8. OTHER PRODUCTS
If asked about another product, say exactly:
"I'm only here for your pending payment. For other queries,
please visit a branch or call the helpline."

9. UNABLE TO PAY
If the customer says they cannot pay:
- Respond empathetically.
- Ask whether they would like a bank representative to call them back.
- Ask for the preferred callback date and time only after acceptance.
- Do not pressure the customer.

10. OTHER QUESTIONS
Answer only when the answer is supported by the bank facts
and the assignment rules.
If unsure, do not invent an answer.

CLOSING
Close politely once a clear outcome has been reached.
Do not force every customer into a promise to pay.

IMPORTANT INTEGRITY RULES
- Never say a payment has been recorded unless the application
  confirms that it has been saved.
- Never say a human agent has been notified unless the application
  confirms that the escalation has been submitted.
- Never promise that collection calls will stop.
- Never promise a waiver, discount, or special treatment.
- Never fabricate dates, amounts, customer details, or outcomes.

PAYMENT GUIDANCE:
- If the customer asks about payment methods, do not refuse
  the question.
- Do not invent or guarantee payment channels.
- Direct the customer to Mumbai Bank's official mobile app,
  internet banking, branch, or helpline for verified options.
- If asked specifically about UPI, explain that they should
  use UPI only if it is listed as an available option in
  the bank's official payment channels.
- Never request a UPI PIN, OTP, card PIN, or other payment
  credentials.
- Answer the question briefly before returning to the
  payment conversation.
"""


# ---------------------------------------------------------
# 3. POLICY DECISION INSTRUCTIONS
# ---------------------------------------------------------

def build_policy_instruction(decision) -> str:
    """
    Convert the deterministic policy engine's decision into
    an instruction for the LLM.
    """

    intent = decision.intent.value
    action = decision.action.value

    logger.info(
        "Policy decision | intent={} | action={} | reason={}",
        intent,
        action,
        decision.reason,
    )

    instructions = {
        "escalate_to_human": """
POLICY OVERRIDE:
The customer has triggered a mandatory human escalation.
Stop the collections conversation immediately.
Do not ask for payment or continue the pitch.
Politely explain that a human agent will follow up.
Do not claim that the transfer has already been completed.
""",

        "capture_already_paid": """
POLICY OVERRIDE:
The customer says they have already paid.
Ask for the payment date and payment mode.
Do not continue asking for a payment commitment.
""",

        "capture_waiver_request": """
POLICY OVERRIDE:
The customer has requested a waiver.
You cannot approve or promise a waiver.
Acknowledge the request and explain that a human agent
will follow up.
""",

        "capture_callback": """
POLICY OVERRIDE:
The customer has requested a callback.
Ask for their preferred callback time.
Do not invent operating hours.
""",

        "capture_dispute": """
POLICY OVERRIDE:
The customer has raised a dispute.
Stop the collections pitch.
Acknowledge the dispute and arrange human follow-up.
Ask for the reason if it is not already clear.
""",

        "refuse_balance_disclosure": """
POLICY OVERRIDE:
The customer is asking for their account balance.
OTP verification is unavailable in this demo.
Do not disclose any balance or account-specific amount.
""",

        "decline_other_product": """
POLICY OVERRIDE:
The customer is asking about another bank product.
Respond with exactly:
"I'm only here for your pending payment. For other queries,
please visit a branch or call the helpline."
""",

        "capture_ptp": """
POLICY OVERRIDE:
The customer appears willing to make a payment.
Capture both the payment amount and payment date.
If one is missing, ask for it.
Repeat both details and ask for confirmation.
Never invent missing details.
""",

        "clarify_hardship": """
POLICY OVERRIDE:
The customer says they cannot pay.
Be empathetic and do not pressure them.
Ask one brief question about whether they prefer
a callback or would like to discuss another payment date.
""",

        "continue": """
Continue the conversation according to the bank policy.
""",
    }

    return instructions.get(
        action,
        "Continue according to the bank policy. Do not invent information.",
    )


# ---------------------------------------------------------
# 4. PIPECAT BOT
# ---------------------------------------------------------

async def run_bot(
    transport: BaseTransport,
    runner_args: RunnerArguments,
) -> None:

    logger.info("Starting Mumbai Bank Collections Voicebot")
    call_id = str(uuid.uuid4())
    escalation_submitted = False

    # Callback conversation state:
    # none -> awaiting_confirmation -> awaiting_time -> none
    callback_state = "none"

    # -----------------------------------------------------
    # Speech-to-Text: Deepgram
    # -----------------------------------------------------

    stt = DeepgramSTTService(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
        settings=DeepgramSTTService.Settings(
            model="nova-3",
            language="multi",
            interim_results=True,
            punctuate=True,
            smart_format=True,
            numerals=True,
        ),
    )

    # -----------------------------------------------------
    # Text-to-Speech: Cartesia
    # -----------------------------------------------------

    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        settings=CartesiaTTSService.Settings(
            model=os.getenv("CARTESIA_MODEL", "sonic-3.6"),
            voice=os.getenv(
                "CARTESIA_VOICE_ID",
                "86e30c1d-714b-4074-a1f2-1cb6b552fb49",
            ),
        ),
    )

    # -----------------------------------------------------
    # LLM: OpenAI
    # -----------------------------------------------------

    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        settings=OpenAILLMService.Settings(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
            system_instruction=SYSTEM_PROMPT,
        ),
    )

    # -----------------------------------------------------
    # Conversation context
    # -----------------------------------------------------

    context = LLMContext()

    user_aggregator, assistant_aggregator = (
        LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(),
            ),
        )
    )

    # -----------------------------------------------------
    # Deterministic policy engine integration
    # -----------------------------------------------------

    @user_aggregator.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped(
        aggregator,
        strategy,
        message,
    ):
        """Classify each complete customer utterance and enforce policy."""

        nonlocal escalation_submitted, callback_state

        customer_text = (message.content or "").strip()
        if not customer_text:
            return

        logger.info("Customer transcript: {}", customer_text)
        normalized_text = customer_text.lower().strip()

        # -------------------------------------------------
        # CALLBACK: WAITING FOR CUSTOMER ACCEPTANCE
        # -------------------------------------------------

        affirmative = {
            "yes", "yeah", "yep", "sure", "okay", "ok",
            "please do", "that would help", "yes please", "go ahead",
        }
        negative = {
            "no", "no thanks", "not now", "not interested",
            "no thank you",
        }

        if callback_state == "awaiting_confirmation" and classify_message(customer_text).action.value != "escalate_to_human":
            if normalized_text in affirmative:
                callback_state = "awaiting_time"
                context.add_message({
                    "role": "developer",
                    "content": """
CALLBACK STATE: CUSTOMER ACCEPTED.
Ask the customer for their preferred callback date and time.
Ask one question only. Do not claim that a callback has been
recorded or scheduled. Wait for the customer's response.
""",
                })
                return

            if normalized_text in negative:
                callback_state = "none"
                context.add_message({
                    "role": "developer",
                    "content": """
The customer declined a callback. Do not pressure them.
Ask whether they would like to discuss a payment date instead.
Continue according to bank policy.
""",
                })
                return

            context.add_message({
                "role": "developer",
                "content": """
You are waiting for the customer's yes/no answer to a callback offer.
Politely clarify whether they want a bank representative to call them.
Do not assume acceptance.
""",
            })
            return

        # -------------------------------------------------
        # POLICY CLASSIFICATION
        # -------------------------------------------------

        # While collecting a callback time, preserve an explicit
        # payment promise such as "I'll pay tomorrow" as a PTP.
        if callback_state == "awaiting_time":
            ordinary_decision = classify_message(customer_text)
            if ordinary_decision.action.value == "capture_ptp":
                callback_state = "none"
                decision = ordinary_decision
            else:
                decision = classify_message(
                    customer_text,
                    awaiting_callback_time=True,
                )
        else:
            decision = classify_message(customer_text)

        logger.info(
            "Policy engine selected: {}",
            decision.action.value,
        )

        # -------------------------------------------------
        # CALLBACK: CAPTURE AND SAVE PREFERRED TIME
        # -------------------------------------------------

        if callback_state == "awaiting_time":
            if decision.action.value != "capture_callback":
                context.add_message({
                    "role": "developer",
                    "content": """
The customer has not yet provided a clear callback date/time.
Ask them to specify a preferred date and time. Do not claim
that a callback request has been recorded.
""",
                })
                return

            callback_outcome = {
                "outcome_type": "Callback-Request",
                "callback_time": customer_text,
            }
            is_valid, validation_message = validate_outcome(callback_outcome)
            logger.info(
                "Callback validation: {} | {}",
                is_valid,
                validation_message,
            )

            if not is_valid:
                context.add_message({
                    "role": "developer",
                    "content": """
The callback preference was incomplete or invalid.
Ask the customer to provide a clear preferred callback date and time.
Do not claim that the request has been recorded.
""",
                })
                return

            try:
                event = save_crm_event({
                    "call_id": call_id,
                    "outcome": "CALLBACK_REQUEST",
                    "outcome_type": "Callback-Request",
                    "reason": "Customer requested a callback.",
                    "callback_time": customer_text,
                    "customer_statement": customer_text,
                })

                logger.info(
                    "Callback request saved to CRM: {}",
                    event["event_id"],
                )
                callback_state = "none"

                email_sent = send_followup_email(event)
                logger.info(
                    "Callback notification email delivery: {}",
                    email_sent,
                )

                if email_sent:
                    instruction = """
CALLBACK REQUEST SUCCESSFULLY SAVED.
CRM confirms the callback request was persisted, and the internal
notification email was successfully delivered.
Tell the customer: "Thank you. I've recorded your callback preference.
A bank representative will follow up with you."
Do not claim a specific callback appointment has been booked.
"""
                else:
                    instruction = """
CALLBACK REQUEST SAVED, BUT EMAIL NOTIFICATION FAILED.
CRM confirms that the callback request was persisted. The internal
notification email was not successfully delivered.
Tell the customer the request was recorded, but you cannot confirm
the follow-up notification. Direct them to the bank helpline for
assistance. Do not claim an appointment has been booked.
"""

            except Exception as exc:
                logger.exception("Callback CRM persistence failed: {}", exc)
                callback_state = "none"
                instruction = """
CALLBACK REQUEST COULD NOT BE SAVED.
Do not claim that the callback was recorded, scheduled, or submitted.
Apologize briefly and direct the customer to the bank helpline
to arrange a callback.
"""

            context.add_message({
                "role": "developer",
                "content": instruction,
            })
            return

        # -------------------------------------------------
        # CALLBACK: CUSTOMER REQUESTED ONE DIRECTLY
        # -------------------------------------------------

        if decision.action.value == "capture_callback":
            callback_state = "awaiting_time"
            context.add_message({
                "role": "developer",
                "content": """
The customer requested a callback.
Ask for their preferred callback date and time.
Do not claim that the request has been recorded yet.
Do not invent callback operating hours.
""",
            })
            return

        # -------------------------------------------------
        # CUSTOMER UNABLE TO PAY: OFFER CALLBACK
        # -------------------------------------------------

        if decision.action.value == "clarify_hardship":
            callback_state = "awaiting_confirmation"
            context.add_message({
                "role": "developer",
                "content": """
The customer expressed difficulty making the payment.
Be empathetic and do not pressure them.
Ask this clear yes/no question:
"Would you like a bank representative to call you back?"
Do not ask for a callback time until the customer accepts.
Do not claim that a callback has been recorded.
""",
            })
            return

        # -------------------------------------------------
        # HUMAN FOLLOW-UP / ESCALATION
        # -------------------------------------------------

        human_followup_actions = {
            "escalate_to_human",
            "capture_dispute",
            "capture_waiver_request",
        }

        if (
            decision.action.value in human_followup_actions
            and not escalation_submitted
        ):
            event = save_crm_event({
                "call_id": call_id,
                "outcome": "TRANSFER_TO_HUMAN",
                "reason": decision.intent.value,
                "customer_statement": customer_text,
                "transcript": customer_text,
            })
            escalation_submitted = True

            logger.info(
                "CRM escalation saved: {}",
                event["event_id"],
            )

            email_sent = send_escalation_email(event)
            logger.info("Escalation email delivery: {}", email_sent)

            if not email_sent:
                context.add_message({
                    "role": "developer",
                    "content": """
The escalation was saved in CRM, but the internal notification
email failed. Do not claim that a human agent has been notified.
Do not claim that a transfer has been completed.
""",
                })

        policy_instruction = build_policy_instruction(decision)
        context.add_message({
            "role": "developer",
            "content": policy_instruction,
        })

    # -----------------------------------------------------
    # Pipeline
    # -----------------------------------------------------

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    runner = WorkerRunner(
        handle_sigint=runner_args.handle_sigint,
    )

    await runner.add_workers(worker)

    # -----------------------------------------------------
    # Client lifecycle
    # -----------------------------------------------------

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        logger.info("Browser client is ready")

        context.add_message(
            {
                "role": "developer",
                "content": (
                    "Start the call now. Introduce yourself as "
                    "Mumbai Bank's automated collections assistant. "
                    "Briefly explain that you are calling about "
                    "a pending credit-card payment. Ask whether "
                    "this is a convenient time to talk."
                ),
            }
        )

        await worker.queue_frames(
            [LLMRunFrame()]
        )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")

        await worker.cancel()

    # -----------------------------------------------------
    # Start worker
    # -----------------------------------------------------

    logger.info("Collections voicebot is ready")

    await runner.run()


# ---------------------------------------------------------
# 5. RUNNER ENTRY POINT
# ---------------------------------------------------------

async def bot(runner_args: RunnerArguments):
    transport_params = {
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    }

    transport = await create_transport(
        runner_args,
        transport_params,
    )

    await run_bot(
        transport,
        runner_args,
    )


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()

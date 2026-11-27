# Collections Voicebot

A browser-based AI voicebot prototype for an outbound credit-card collections use case. Built as a Senior Product Manager take-home assignment for GreyLabs.ai.

The prototype demonstrates how a voice assistant can hold a short, policy-led conversation with a customer who is 1–30 days overdue, identify the customer's intent, and capture a relevant next step.

> **Status: Proof of concept.** This is a simulated demonstration, not a production banking or telephony system. Do not use it with real customer data or live collections operations.

## What it demonstrates

- Real-time, browser-based voice interaction.
- Speech recognition for customer input, including English and Hindi/Hinglish input; the assistant is instructed to respond in English.
- Policy-guided conversation for common collections scenarios:
  - Promise to pay (payment date and amount).
  - Already paid (payment date and mode).
  - Callback request.
  - Fee-waiver request.
  - Payment dispute.
  - Job loss, medical emergency, or abusive language requiring human follow-up.
  - Requests for account balance without OTP verification.
  - Questions about unrelated bank products.
- A lightweight Python policy layer that classifies selected intents and validates required outcome fields.
- Local JSONL event logging and email notifications for selected follow-up scenarios.

## How it works

```text
Customer speaks in browser
        |
        v
Deepgram speech-to-text
        |
        v
OpenAI GPT-4.1 conversation
        |
        v
Python policy checks
        |
        +----> Save selected outcome to local JSONL
        |      and send internal email notification
        |
        v
Cartesia text-to-speech
        |
        v
Customer hears the response
```

The policy layer provides deterministic checks for selected intents and required fields. The language model handles the conversational response within the bank-policy instructions.

## Technology choices

| Component | Technology | Purpose |
|---|---|---|
| Voice pipeline | Pipecat | Orchestrates the real-time voice conversation |
| Browser audio transport | SmallWebRTC | Connects the browser client to the voice pipeline |
| Speech-to-text | Deepgram Nova-3 | Converts customer speech into text |
| Conversation model | OpenAI GPT-4.1 | Interprets the conversation and generates responses |
| Text-to-speech | Cartesia Sonic 3.6 | Converts responses into speech |
| Policy checks | Python | Classifies selected intents and validates outcome fields |
| Demo follow-up | Local JSONL + SMTP email | Persists selected events and sends internal notifications |
| Browser interface | React + Vite | Provides the voice interaction interface |

## Project structure

```text
.
├── pipecat-quickstart/
│   ├── server/       # Pipecat voice pipeline, policy logic and CRM demo
│   └── client/       # Browser-based React client
├── src/
│   └── collections_voicebot/
└── README.md
```

The repository also contains supporting assignment material and evaluation artefacts.

## Running the prototype locally

### Prerequisites

- Python 3.11–3.14
- [uv](https://docs.astral.sh/uv/)
- Node.js and npm
- API keys for Deepgram, OpenAI and Cartesia

### 1. Configure the server

Open a terminal in `pipecat-quickstart/server`.

Create a local `.env` file using the example file as a reference, then add your own API credentials:

```env
DEEPGRAM_API_KEY=your_deepgram_api_key
OPENAI_API_KEY=your_openai_api_key
CARTESIA_API_KEY=your_cartesia_api_key
OPENAI_MODEL=gpt-4.1
CARTESIA_MODEL=sonic-3.6
```

Do not commit your `.env` file or share API keys.

Install dependencies and start the server:

```bash
uv sync
uv run bot.py
```

### 2. Start the browser client

Open a second terminal in `pipecat-quickstart/client`:

```bash
npm install
npm run dev
```

Open the local URL printed by Vite in your browser and follow the interface to start a voice session.

## Important limitations

- No live telephony integration or outbound phone calling.
- No connection to a bank's production CRM, customer database, payment gateway, agent desktop, or callback scheduling system.
- No OTP verification, account-balance retrieval, payment verification, or payment initiation.
- Waivers and fee changes cannot be approved by the bot.
- Local event logging and SMTP notifications are demonstration mechanisms, not a production CRM or confirmed agent handoff.
- Callback capture has a known transcript-segmentation issue: a spoken date/time may be saved incompletely. Callback capture should therefore be treated as **not production-ready**.
- Repeated call/session lifecycle reliability has not been fully verified.
- The prototype has not undergone production security, privacy, load, or reliability testing.

The assignment evaluation is a functional prototype exercise; the scripted scenarios are not evidence of production performance or statistically significant accuracy.

## Safety and data handling

Use fictional test conversations only. The application requires API credentials in a local environment file. Keep credentials, real customer information, call recordings, and local test logs out of the public repository.

## Assignment context

This prototype was built to demonstrate product thinking across a constrained collections use case: customer intent handling, policy adherence, outcome capture, escalation paths, technology selection, and transparent documentation of limitations.

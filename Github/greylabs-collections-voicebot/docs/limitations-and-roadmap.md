# Limitations and roadmap

## Known limitations
1. Callback transcript segmentation: one observed utterance intended as “Tomorrow morning, 9 AM” was received as “Tomorrow,”. The non-empty-field validator accepted it and the incomplete value was persisted and emailed.
2. Repeat-call lifecycle: the developer observed that a second call in the same backend run did not behave reliably. Root cause was not isolated; treat multi-call reliability as unverified.
3. Regex policy classification is brittle and requires broader paraphrase and adversarial testing.
4. Local JSONL is not a production CRM: no authentication, access control, retention policy, idempotency guarantees, or operational dashboard.
5. SMTP success confirms notification delivery only, not callback scheduling or successful human transfer.
6. No OTP, telephony, real agent transfer, bank CRM, payment rails, or production-grade observability.
7. End-to-end 15-scenario controlled evaluation is incomplete; results must remain evidence-led.

## Week 1 — Reliability and controlled pilot readiness
- Fix turn-finalization/transcript aggregation and validate callback date/time semantically.
- Isolate state per call; test at least 5 consecutive calls in one backend process.
- Add schema validation, idempotency keys, retry handling, and explicit event status.
- Run all 15 scripted scenarios plus 8+ adversarial/failure cases; attach transcripts and backend logs.
- Add latency, interruption, silence, and escalation-recall measurements.
- Conduct a limited internal pilot with synthetic/test accounts only.

## Week 2 — Production-readiness work
- Integrate approved telephony, bank CRM, agent queue, and callback scheduler.
- Implement OTP through an approved secure channel before any balance disclosure.
- Add authentication, encryption, secrets management, PII minimization, audit trails, retention controls, and access controls.
- Add dashboards and alerts for policy violations, dropped calls, webhook/email failures, latency, and outcome completeness.
- Run load, regression, security, privacy, and compliance reviews; obtain bank operations/legal approval.

Rules for this codebase. Do not deviate without asking.

1. LLM only RECOMMENDS an action with reasoning. It never calls a money-moving API directly.
   LLM ↓ Recommendation ↓ Policy Engine ↓ Action Executor ↓ Razorpay API

2. Failure classification (TEMPORARY / PERMANENT / REPEATED_FAILURE / UNKNOWN) is a fixed,
   deterministic lookup — never an LLM judgment.

3. The LLM's job is NOT category→action lookup. It receives structured context
   (category, attempt_count, amount, time_since_last_attempt, retry_budget_remaining)
   and produces: recommended_action + a short reason. This must involve real
   interpretation of context, not a hardcoded if/else disguised as an LLM call.

4. Only 4 recovery decisions exist: RETRY, SEND_RECOVERY_LINK, ESCALATE, STOP.
   Never invent a 5th. Notifications, Slack posts, and audit logging are
   infrastructure operations, not recovery actions — do not treat them as such.

5. Policy engine is plain deterministic code, no AI. It is the only thing that can
   approve or block an action. See POLICY.md for exact rules — do not infer rules
   from examples, use POLICY.md as source of truth.

6. Action executor is the only component allowed to call external APIs
   (Razorpay, Slack). LLM and policy engine never call external APIs directly.

7. Every step (failure detected, classified, recommended, policy decision,
   action executed, execution result, business outcome) writes to audit_log.

8. Webhook/event processing must be idempotent. Use event_id + payment_id to
   detect duplicates. A duplicate event must never create a duplicate recovery action.

9. Track execution outcome and business outcome as separate fields. A retry API
   call succeeding is NOT the same as the payment succeeding — verify the actual
   payment result before marking anything "recovered."

10. Use the state machine in POLICY.md. Never write a status/action combination
    that isn't a valid state transition (e.g. status=recovered with action=escalate).

11. DEMO_MODE changes only timing (retry backoff), never policy logic. When
    DEMO_MODE=true, the UI must visibly show a "DEMO MODE" badge at all times.

12. Never call REPEATED_FAILURE "fraud detection" — it's a repeat-failure count only.

13. Never phrase money language as "lost/recovered from a loss" — say
    "captured/uncaptured revenue." No transfer reverses in this system.

Full policy rules: POLICY.md. Full product context: README.md.
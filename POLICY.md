CATEGORIES (fixed, deterministic lookup)
- TEMPORARY        — likely to succeed on retry (network/gateway error, soft decline)
- PERMANENT        — retry won't help (expired card, insufficient funds, cancelled)
- REPEATED_FAILURE — 3+ consecutive unsuccessful attempts on the same payment,
                      including the initial attempt
- UNKNOWN          — anything unmapped or malformed — default to safest handling

ATTEMPT COUNTING (explicit — do not infer)
- The initial failed payment counts as attempt 1.
- Attempt 1 fails → may trigger Retry 1 (attempt 2).
- Attempt 2 fails → may trigger Retry 2 (attempt 3).
- Attempt 3 fails → this is 3 consecutive failures → reclassify as REPEATED_FAILURE
  → ESCALATE. No further automatic retry.

ACTION RULES (condition-based, not rigid category-lock)
- TEMPORARY, retry budget available (< 2 retries used, > min interval since last attempt)
    → RETRY
- TEMPORARY, retry budget exhausted
    → SEND_RECOVERY_LINK, or ESCALATE if amount > HIGH_VALUE_THRESHOLD_INR
- PERMANENT
    → SEND_RECOVERY_LINK
- REPEATED_FAILURE
    → ESCALATE (never auto-retry)
- UNKNOWN
    → STOP if amount > HIGH_VALUE_THRESHOLD_INR, otherwise ESCALATE

HARD OVERRIDE (always wins, regardless of LLM recommendation)
- amount > HIGH_VALUE_THRESHOLD_INR (config, default ₹10,000 — a configurable
  prototype merchant-risk threshold) AND category is REPEATED_FAILURE or UNKNOWN
    → hard STOP, no exceptions

TIMING
- Production: minimum 15 minutes between retries
- DEMO_MODE=true: minimum 15 seconds between retries (UI must show DEMO MODE badge)
- DEMO_MODE never changes any rule above — timing only

STATE MACHINE (only valid transitions allowed)
FAILED → CLASSIFIED → RECOMMENDED → (APPROVED | BLOCKED)
APPROVED → EXECUTING → (SUCCEEDED | FAILED_EXECUTION | ESCALATED | STOPPED)
BLOCKED → (ESCALATED | STOPPED)

OUTCOME SEPARATION
- execution_result: did the API call/action itself succeed? (e.g. retry call succeeded)
- business_outcome: did the payment actually get captured? (verify separately —
  a successful retry call does not guarantee a successful payment)
- Only mark business_outcome = "recovered" after independently verifying payment status.

LOGGING
- Every policy decision (approved/blocked) logged with its reason, regardless of
  whether the resulting action succeeds.

NO FAKE METRICS. NO FRAUD-DETECTION CLAIMS.
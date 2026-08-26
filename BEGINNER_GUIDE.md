# RecoverAI — Complete Codebase Masterclass & Learning Guide

> **Audience**: Developers with intermediate Python knowledge (functions, dictionaries, loops, basic classes).  
> **Goal**: Understand every concept, architectural decision, design pattern, and line of code in the **RecoverAI** revenue recovery platform.

---

## 📚 Table of Contents
1. [Module 1: The Real-World Problem & Core Solution](#module-1-the-real-world-problem--core-solution)
2. [Module 2: The "Separation of Powers" Architecture](#module-2-the-separation-of-powers-architecture)
3. [Module 3: Database Mechanics & Financial Precision](#module-3-database-mechanics--financial-precision)
4. [Module 4: File-by-File Deep Dive & Code Walkthrough](#module-4-file-by-file-deep-dive--code-walkthrough)
   - [4.1 Data Models (`models.py` & `checkout_models.py`)](#41-data-models-modelspy--checkout_modelspy)
   - [4.2 Database Schema & Immutable Triggers (`db.py` & `checkout_db.py`)](#42-database-schema--immutable-triggers-dbpy--checkout_dbpy)
   - [4.3 Synthetic Data Generator (`generator.py`)](#43-synthetic-data-generator-generatorpy)
   - [4.4 Deterministic Classifier (`classifier.py`)](#44-deterministic-classifier-classifierpy)
   - [4.5 LLM Recommendation Engine (`llm_recommender.py`)](#45-llm-recommendation-engine-llm_recommenderpy)
   - [4.6 Deterministic Policy Engine (`policy_engine.py`)](#46-deterministic-policy-engine-policy_enginepy)
   - [4.7 Action Executor & Live Integrations (`action_executor.py` & `razorpay_client.py`)](#47-action-executor--live-integrations-action_executorpy--razorpay_clientpy)
   - [4.8 Financial Metrics & EV Aggregator (`metrics_aggregator.py`)](#48-financial-metrics--ev-aggregator-metrics_aggregatorpy)
   - [4.9 Web Dashboard & Simulation API (`app.py` & `index.html`)](#49-web-dashboard--simulation-api-apppy--indexhtml)
5. [Module 5: How to Run, Test, and Extend the Codebase](#module-5-how-to-run-test-and-extend-the-codebase)

---

## Module 1: The Real-World Problem & Core Solution

### 1.1 The E-Commerce Payment Problem
When a customer buys something online (e.g. on Razorpay), payments fail **15% to 25% of the time**. Reasons include:
- Temporary bank server outages (`gateway_error`, `bank_declined`).
- Customer issues like expired cards (`card_expired`) or insufficient balance (`insufficient_funds`).
- Customers abandoning their cart right before clicking pay (`cart_idle_15m`, `shipping_cost_too_high`).

If merchants don't intervene, they **lose uncaptured revenue**. But if they use primitive scripts (e.g. automatically retrying every failure), they risk spamming customers or wasting money on retries that will never succeed.

### 1.2 The Naive AI Mistake vs. RecoverAI
Many AI developers build agents by giving Large Language Models (LLMs) direct access to API functions like `execute_payment_retry()` or `send_90_percent_discount()`.

**Why this is dangerous in finance:**
1. LLMs can **hallucinate**: An LLM might decide to issue a 90% discount on a ₹100,000 item.
2. LLMs are **non-deterministic**: Asking the same LLM twice might produce two different actions.
3. LLMs lack **retry limits**: An LLM might loop retries infinitely, annoying customers.

**RecoverAI's Solution**: Enforce a strict **"Separation of Powers"** where the LLM is treated as an *advisor only*, governed by deterministic Python code.

---

## Module 2: The "Separation of Powers" Architecture

To keep financial systems safe, RecoverAI structures code into 4 distinct layers:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      1. FAILURE CLASSIFIER                              │
│         (Pure Python lookup table — Categorizes failure reason)         │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      2. LLM RECOMMENDER                                 │
│   (Ollama mistral:7b / Gemini API — Advises recommended action + reason)│
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      3. POLICY ENGINE                                   │
│        (Deterministic Python code — Absolute Veto & Hard Overrides)     │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
    [If Policy Engine = APPROVED]           [If Policy Engine = BLOCKED]
                 │                                       │
                 ▼                                       ▼
┌──────────────────────────────────┐    ┌─────────────────────────────────┐
│        4. ACTION EXECUTOR        │    │       HUMAN OPS ESCALATION      │
│  (Razorpay REST API / Slack)     │    │  (Logged as ESCALATED in DB)    │
└────────────────┬─────────────────┘    └────────────────┬────────────────┘
                 │                                       │
                 └───────────────────┬───────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      5. IMMUTABLE AUDIT LOG                             │
│       (SQLite database triggers append every step to audit ledger)      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Real-World Analogy:
- **Classifier** = The Police Report (Factual details of what went wrong).
- **LLM Recommender** = The Advisory Committee (Suggests what action to take).
- **Policy Engine** = The Judge (Checks written law; approves or overrides the suggestion).
- **Action Executor** = The Officer (Performs the approved action).
- **Audit Log** = The Court Clerk (Writes down everything permanently).

---

## Module 3: Database Mechanics & Financial Precision

### 3.1 Money Representation: Storing Paise as Integers
In Python, floating-point arithmetic causes rounding bugs:
```python
>>> 0.1 + 0.2
0.30000000000000004  # DANGEROUS FOR CURRENCY!
```
In RecoverAI, all monetary amounts are strictly stored as **integers representing paise** (1 INR = 100 paise).
- ₹499.00 is stored as `49900` paise.
- ₹10,000.00 is stored as `1000000` paise.
- Conversion to INR happens **only when displaying to humans**: `amount_in_inr = amount_in_paise / 100.0`.

### 3.2 Immutability via SQLite Triggers
Audit logs in financial software must be **tamper-proof**. In [db.py](file:///d:/Z_shared/Razarrr/db.py), SQLite triggers prevent any Python code from modifying or deleting audit log records:

```sql
CREATE TRIGGER IF NOT EXISTS audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(FAIL, 'UPDATE operation forbidden on immutable table audit_log');
END;
```
If any script tries to run `UPDATE audit_log SET ...`, SQLite immediately crashes with an `IntegrityError`.

### 3.3 Idempotency Protection
If a webhook fires twice due to a network retry, RecoverAI uses an `idempotency` table with a `PRIMARY KEY` on `event_id`. Inserting a duplicate `event_id` is rejected by SQLite, preventing duplicate money retries.

---

## Module 4: File-by-File Deep Dive & Code Walkthrough

Let's examine how each Python file works line by line.

---

### 4.1 Data Models ([models.py](file:///d:/Z_shared/Razarrr/models.py) & [checkout_models.py](file:///d:/Z_shared/Razarrr/checkout_models.py))

[models.py](file:///d:/Z_shared/Razarrr/models.py) uses Python's standard library `enum` and `dataclass` modules to define strict data structures:

```python
from enum import Enum
from dataclasses import dataclass

# Category enum: Valid classification buckets
class Category(str, Enum):
    TEMPORARY = "TEMPORARY"          # Likely to succeed on retry (soft decline)
    PERMANENT = "PERMANENT"          # Hard decline (expired card, cancelled)
    REPEATED_FAILURE = "REPEATED_FAILURE" # Failed 3+ times
    UNKNOWN = "UNKNOWN"              # Unmapped failure reason code

# Valid actions allowed in Loop 1 (Payment Recovery)
class RecoveryAction(str, Enum):
    RETRY = "RETRY"
    SEND_RECOVERY_LINK = "SEND_RECOVERY_LINK"
    ESCALATE = "ESCALATE"
    STOP = "STOP"

# Valid state machine statuses
class PaymentStatus(str, Enum):
    FAILED = "FAILED"
    CLASSIFIED = "CLASSIFIED"
    RECOMMENDED = "RECOMMENDED"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_EXECUTION = "FAILED_EXECUTION"
    ESCALATED = "ESCALATED"
    STOPPED = "STOPPED"
```

**Key Takeaway**: Using `Enum` prevents typos (e.g. typing `"RETRYY"` instead of `"RETRY"`).

---

### 4.2 Database Schema & Immutable Triggers ([db.py](file:///d:/Z_shared/Razarrr/db.py) & [checkout_db.py](file:///d:/Z_shared/Razarrr/checkout_db.py))

[db.py](file:///d:/Z_shared/Razarrr/db.py) sets up SQLite connections and creates tables with strict constraints:

```python
def init_db(db_path: str = "recover_ai.db"):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    # 1. Main Payments Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id TEXT PRIMARY KEY,
            amount_in_paise INTEGER NOT NULL,
            failure_reason TEXT NOT NULL,
            ground_truth_category TEXT NOT NULL,
            category TEXT CHECK(category IN ('TEMPORARY', 'PERMANENT', 'REPEATED_FAILURE', 'UNKNOWN') OR category IS NULL),
            status TEXT NOT NULL CHECK(status IN ('FAILED', 'CLASSIFIED', 'RECOMMENDED', 'APPROVED', 'BLOCKED', 'EXECUTING', 'SUCCEEDED', 'FAILED_EXECUTION', 'ESCALATED', 'STOPPED')),
            attempt_count INTEGER NOT NULL DEFAULT 1,
            last_attempt_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            recommended_action TEXT,
            recommendation_reason TEXT
        );
    """)

    # 2. Immutable Audit Log Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payment_id TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            category TEXT,
            recommended_action TEXT,
            policy_decision TEXT,
            policy_reason TEXT,
            action_taken TEXT,
            execution_result TEXT,
            business_outcome TEXT,
            amount_in_paise INTEGER NOT NULL
        );
    """)
    conn.commit()
    conn.close()
```

---

### 4.3 Synthetic Data Generator ([generator.py](file:///d:/Z_shared/Razarrr/generator.py))

[generator.py](file:///d:/Z_shared/Razarrr/generator.py) uses `random.seed(seed)` to generate 100 reproducible synthetic payment records for testing.

```python
def generate_synthetic_data(seed: int = 42) -> List[Dict[str, Any]]:
    random.seed(seed)  # Fix random seed so results are 100% reproducible every time
    
    records = []
    # Generate distribution: 40 TEMPORARY, 25 PERMANENT, 20 REPEATED_FAILURE, 15 UNKNOWN
    for i in range(1, 101):
        pid = f"pay_42_{i:03d}"  # pay_42_001, pay_42_002...
        ...
```

---

### 4.4 Deterministic Classifier ([classifier.py](file:///d:/Z_shared/Razarrr/classifier.py))

[classifier.py](file:///d:/Z_shared/Razarrr/classifier.py) contains the zero-AI deterministic classification rules.

```python
TEMPORARY_REASONS = {"network_error", "gateway_error", "bank_declined"}
PERMANENT_REASONS = {"insufficient_funds", "card_expired", "payment_cancelled"}

def classify_failure(failure_reason: str, attempt_count: int) -> Category:
    # Rule 1: 3 or more attempts automatically forces REPEATED_FAILURE
    if attempt_count >= 3:
        return Category.REPEATED_FAILURE

    reason_clean = failure_reason.strip().lower() if failure_reason else ""

    # Rule 2: Fixed lookup table
    if reason_clean in TEMPORARY_REASONS:
        return Category.TEMPORARY
    elif reason_clean in PERMANENT_REASONS:
        return Category.PERMANENT
    else:
        return Category.UNKNOWN
```

**Key Takeaway**: Classification is **100% pure code**, making it deterministic and instant (<1 millisecond).

---

### 4.5 LLM Recommendation Engine ([llm_recommender.py](file:///d:/Z_shared/Razarrr/llm_recommender.py))

[llm_recommender.py](file:///d:/Z_shared/Razarrr/llm_recommender.py) passes structured context to the local Ollama LLM (`mistral:latest` 7B model) using Python's standard library `urllib.request`.

```python
def call_llm_api(context: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
    prompt = PROMPT_TEMPLATE.format(**context)
    url = "http://127.0.0.1:11434/api/generate"
    
    payload = {
        "model": "mistral:latest",
        "prompt": prompt,
        "stream": False,
        "format": "json"  # Forces LLM to reply in JSON format!
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        llm_output = json.loads(body["response"])
        
        action = llm_output.get("recommended_action")
        reason = llm_output.get("reason")
        return action, reason, None
```

---

### 4.6 Deterministic Policy Engine ([policy_engine.py](file:///d:/Z_shared/Razarrr/policy_engine.py))

[policy_engine.py](file:///d:/Z_shared/Razarrr/policy_engine.py) inspects the LLM's recommendation and decides whether to approve or block it.

```python
def evaluate_policy(context: Dict[str, Any]) -> Tuple[str, str]:
    category = context["category"]
    amount_in_paise = context["amount_in_paise"]
    recommended_action = context["recommended_action"]
    high_value_thresh_paise = 10000 * 100  # ₹10,000 threshold (1,000,000 paise)

    is_high_value = amount_in_paise > high_value_thresh_paise

    # 1. HARD OVERRIDE CHECK (Rule 1)
    # High-value + REPEATED_FAILURE or UNKNOWN forces mandatory STOP
    if is_high_value and category in (Category.REPEATED_FAILURE.value, Category.UNKNOWN.value):
        if recommended_action != RecoveryAction.STOP.value:
            return (
                "BLOCKED",
                f"BLOCKED: Hard override — amount INR {amount_in_paise/100:,.2f} exceeds high-value threshold (INR 10,000) in '{category}' category. Mandatory action is STOP."
            )
        else:
            return ("APPROVED", "APPROVED: Hard override matched for high-value payment.")

    # 2. CATEGORY ALLOWED ACTION CHECK (Rule 2)
    allowed_actions = get_allowed_actions(category, amount_in_paise, context["retry_budget_remaining"])
    
    if recommended_action in allowed_actions:
        return ("APPROVED", f"APPROVED: '{recommended_action}' is allowed for category '{category}'.")
    else:
        return ("BLOCKED", f"BLOCKED: '{recommended_action}' is not allowed for category '{category}'.")
```

---

### 4.7 Action Executor & Live Integrations ([action_executor.py](file:///d:/Z_shared/Razarrr/action_executor.py) & [razorpay_client.py](file:///d:/Z_shared/Razarrr/razorpay_client.py))

[action_executor.py](file:///d:/Z_shared/Razarrr/action_executor.py) executes APPROVED actions.

```python
def execute_single_action(payment_id, category, recommended_action, policy_decision, amount_in_paise, ...):
    # Idempotency check: Don't process twice!
    if is_already_processed(f"evt_act_{payment_id}"):
        return "skipped"

    if policy_decision == "BLOCKED":
        # Route policy-blocked payments directly to human ops review
        execute_escalate(payment_id)
        return

    if recommended_action == "RETRY":
        # Call Razorpay Orders API for real test payments, or execute simulation for synthetic batch
        execute_razorpay_retry(payment_id, amount_in_paise)
    elif recommended_action == "SEND_RECOVERY_LINK":
        # Generate Razorpay Payment Link
        client.create_payment_link(amount_in_paise, description=f"Recovery Link for {payment_id}")
    elif recommended_action == "ESCALATE":
        # Post notification to Slack Webhook
        post_to_slack_webhook(payment_id, category, amount_in_paise)
```

---

### 4.8 Financial Metrics & EV Aggregator ([metrics_aggregator.py](file:///d:/Z_shared/Razarrr/metrics_aggregator.py))

[metrics_aggregator.py](file:///d:/Z_shared/Razarrr/metrics_aggregator.py) calculates expected values and batch summaries:

$$EV = P(\text{success} \mid \text{action}) \times \text{amount}$$

- Probability for `RETRY` = 70% (`0.70`)
- Probability for `SEND_RECOVERY_LINK` = 30% (`0.30`)
- Probability for `ESCALATE` / `STOP` = 0% (`0.0`)

```python
def compute_batch_metrics(db_path: str = "recover_ai.db"):
    revenue_at_risk = sum(p.amount for p in all_payments)
    revenue_recovered = sum(p.amount for p in recovered_payments)
    recovery_rate = (revenue_recovered / revenue_at_risk) * 100.0
    ...
```

---

### 4.9 Web Dashboard & Simulation API ([app.py](file:///d:/Z_shared/Razarrr/app.py) & [templates/index.html](file:///d:/Z_shared/Razarrr/templates/index.html))

[app.py](file:///d:/Z_shared/Razarrr/app.py) is a lightweight Flask application serving JSON endpoints:
- `GET /`: Renders the dark-mode HTML dashboard.
- `GET /api/metrics`: Returns JSON revenue summary.
- `GET /api/payments/<id>/timeline`: Returns the 5-stage chronological audit history for a payment.
- `POST /api/simulate-payment-failure`: Runs a single simulated payment failure live against `recover_ai_live_test.db`.

---

## Module 5: How to Run, Test, and Extend the Codebase

### 5.1 Step-by-Step Running Instructions

1. **Install Flask**:
   ```bash
   pip install flask
   ```

2. **Start the Web Dashboard**:
   ```bash
   python app.py
   ```
   Open `http://127.0.0.1:5000` in your web browser.

3. **Run Pipeline Verification Runners**:
   ```bash
   python run_metrics_aggregator.py
   python run_checkout_metrics_aggregator.py
   python run_baseline_verification_check.py
   ```

4. **Run Live Razorpay REST API Test**:
   ```bash
   python run_razorpay_live_test.py
   ```

---

### 5.2 Exercise for Beginners: Add a New Failure Reason Code

Try adding a new reason code `"otp_timeout"` to [classifier.py](file:///d:/Z_shared/Razarrr/classifier.py):

1. Open [classifier.py](file:///d:/Z_shared/Razarrr/classifier.py).
2. Add `"otp_timeout"` to `TEMPORARY_REASONS`:
   ```python
   TEMPORARY_REASONS = {"network_error", "gateway_error", "bank_declined", "otp_timeout"}
   ```
3. Run `python run_classifier.py` to verify that any payment with failure reason `"otp_timeout"` is automatically classified as `TEMPORARY`!

---

### Summary Checklist for Beginners
- [x] Money amounts are integers in **paise**.
- [x] SQLite triggers make the `audit_log` table **append-only and immutable**.
- [x] Classification is **100% deterministic code** (zero AI).
- [x] LLM provides **recommendations only**; Policy Engine has absolute veto power.
- [x] Live simulations run on isolated test databases (`recover_ai_live_test.db`), leaving baseline databases untouched.

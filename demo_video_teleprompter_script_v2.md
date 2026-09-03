# 🎬 RecoverAI 5-Minute Masterclass — Voiceover Script & Video Sync Cue Sheet (Final 5-Min Cut)

> [!IMPORTANT]
> **VIDEO SYNC GUIDE**: This script is synchronized **1:1 with your recorded screen actions and video editing cut points**. Fast-forward/cut the long pipeline wait times (e.g. 33s, 47s, 51s) down to 4–5 seconds each in your video editor to hit the **exact 5.00-minute target length**!

---

## ⏱️ Video Editing & Voiceover Sync Matrix (Exact 5:00 Cut)

| Final Edited Time | Raw Recorded Time | Action / Dropdown Selected | Video Editing Cut / Trim Cue | Primary On-Screen Visual |
| :---: | :---: | :--- | :--- | :--- |
| **0:00 – 0:30** | `0:00 – 0:30` | `Loop 1 Tab` $\rightarrow$ Scroll Down/Up | Keep original speed | Top tabs $\rightarrow$ Scroll transaction table $\rightarrow$ Scroll back up |
| **0:30 – 1:15** | `0:33 – 1:20` | Select `Option 0 (TEMPORARY)` $\rightarrow$ Run Live Sim | **Cut 33s pipeline run to 5s** | ⚡ **5-Node Stepper** $\rightarrow$ Audit Drawer (`RECOVERED`) |
| **1:15 – 1:55** | `1:22 – 1:47` | Select `Option 1 (PERMANENT ₹22.5k)` $\rightarrow$ Run Live Sim | **Cut 19s pipeline run to 4s** | ⚡ **5-Node Stepper** $\rightarrow$ Policy **`BLOCKED`** + 📢 **Slack Alert** |
| **1:55 – 2:45** | `1:48 – 3:00` | `Loop 2 Tab` $\rightarrow$ Select `Option 0 (RECENT)` $\rightarrow$ Run Sim | **Cut 47s pipeline run to 6s** | ⚡ **5-Node Stepper** $\rightarrow$ 💬 **WhatsApp Voucher** (`RECOVER10`) |
| **2:45 – 3:35** | `3:02 – 4:06` | Select `Option 3 (REPEAT)` $\rightarrow$ Run Live Sim | **Cut 51s pipeline run to 5s** | ⚡ **5-Node Stepper** $\rightarrow$ Policy **`BLOCKED`** + 📢 **Slack Alert** |
| **3:35 – 4:15** | `4:08 – 4:43` | `Loop 3 Tab` $\rightarrow$ Select `Option 0 (DUPLICATE)` $\rightarrow$ Run Sim | **Cut 19s pipeline run to 4s** | ⚡ **5-Node Stepper** $\rightarrow$ Latency Chip + Razorpay Auto-Refund |
| **4:15 – 4:45** | `4:51 – 5:25` | Select `Option 2 (POSSIBLE_FRAUD)` $\rightarrow$ Run Live Sim | **Cut 19s pipeline run to 4s** | ⚡ **5-Node Stepper** $\rightarrow$ Policy **`SECURITY OVERRIDE`** |
| **4:45 – 5:00** | `5:29 – 5:58` | `Loop 1 Tab` $\rightarrow$ Click **`🔄 Instant Reset`** | Keep original speed | Browser Alert OK $\rightarrow$ Top KPI Cards Wrap-Up |

---

## 🎙️ Teleprompter & On-Screen Cue Cards

---

### SECTION 1: Hook & Architecture Overview (0:00 – 0:40)

#### 🖱️ ON-SCREEN MOUSE & SCROLL CUES
1. Ensure **`Loop 1: Payment Recovery`** tab is active on screen load (`0:00`).
2. Point cursor at active **`⚡ DEMO MODE`** badge and top tabs (**`Loop 1`**, **`Loop 2`**, **`Loop 3`**) (`0:05–0:15`).
3. 📜 **Scroll Down Cue (0:18 – 0:22)**: When saying *"we evaluated 100 real-world scenario cases..."*, smoothly scroll down for **4 seconds** to display the transaction data table showing `100 / 100` evaluated payments.
4. 📜 **Scroll Back Up Cue (0:23 – 0:26)**: At **0:23**, smoothly scroll back up to the top toolbar for **3 seconds** to prepare for Section 2.

#### 📢 SPOKEN VOICEOVER (Read Aloud)
> *"Merchant revenue frequently slips away through payment failures, checkout abandonment, and unintended duplicate charges. Standard webhooks log these failure events, but lack an automated decision and recovery layer.*
>
> *We built RecoverAI — an intelligent, bounded recovery pipeline operating across three distinct failure loops. To validate reliability at scale, we evaluated 100 real-world scenario cases in each of our three loops — 300 in total.*
>
> *The core architecture is strictly decoupled: the LLM provides contextual recommendations, but a 100% code-only Policy Engine holds final authority to approve or block execution. If the AI recommendation conflicts with policy rules, policy wins every single time."*

---

### SECTION 2: Loop 1 — Payment Failure Recovery (0:40 – 2:00)

#### 🔹 SCENARIO 1: Temporary Bank Failure & Automated Retry Success

##### 🖱️ ON-SCREEN MOUSE & ACTION CUES
1. In the **Loop 1 Toolbar**, select from dropdown: **`[ ⚡ Scenario: TEMPORARY Failure (Retry Success) ]`** (Option 0).
2. Click target button: **`[ ⚡ Run Live Simulation ]`**.
3. Watch ⚡ **Real-Time 5-Node Stepper Progress Bar** animate live (`1. Ingest → 2. Classify → 3. AI Recommends → 4. Policy Reviews → 5. Execute`).
4. Point cursor at latency breakdown chip: **`LLM Reasoning: 15.2s · Policy Engine: 12ms · Action Executor: 45ms`**.
5. When Audit Drawer opens, point cursor at: `TEMPORARY` $\rightarrow$ `RETRY` $\rightarrow$ Policy **`APPROVED`** $\rightarrow$ **`RECOVERED`**.

##### 📢 SPOKEN VOICEOVER (Read Aloud)
> *"First, let's examine Loop 1 for payment failures. When a temporary bank error occurs, we trigger our live simulation.*
>
> *You can watch our 5-node pipeline stepper execute live: classifying the failure as TEMPORARY. The LLM recommended STOP, but the Policy Engine BLOCKED it, enforcing an automated bank retry to recover the revenue.*
>
> *Opening the UI Audit Timeline reveals the full event trace — proving every policy decision and override is logged without AI hallucination."*

---

#### 🔸 SCENARIO 2: High-Value Permanent Failure & Policy Blocked Escalation

##### 🖱️ ON-SCREEN MOUSE & ACTION CUES
1. Close drawer **`✕`**.
2. In the **Loop 1 Toolbar**, select from dropdown: **`[ ⚡ Scenario: PERMANENT Failure (High Value ₹22.5k, Policy Blocked) ]`** (Option 1).
3. Click target button: **`[ ⚡ Run Live Simulation ]`**.
4. Point cursor at:
   - Policy Decision: **`BLOCKED`** badge.
   - **📢 Slack Escalation Alert** (`#payment-ops-escalations`).
   - Click **`[ 🔍 Toggle Raw Webhook JSON ]`** to expand raw webhook payload.

##### 📢 SPOKEN VOICEOVER (Read Aloud)
> *"Now consider a high-value payment failure of 22,500 rupees. Here, the LLM suggested stopping recovery, but the Policy Engine blocked the recommendation because high-value permanent failures fall outside permitted auto-abandon thresholds.*
>
> *This policy block triggers an automated escalation to human operations on Slack, complete with auditable JSON event context."*

---

### SECTION 3: Loop 2 — Checkout Abandonment (2:00 – 3:30)

#### 🔹 SCENARIO 3: Targeted Discount Nudge

##### 🖱️ ON-SCREEN MOUSE & ACTION CUES
1. Click top tab: **`Loop 2: Checkout Abandonment`**.
2. In the **Loop 2 Toolbar**, select from dropdown: **`[ ⚡ Scenario: RECENT_ABANDON (Discount Nudge - ₹2,999) ]`** (Option 0).
3. Click target button: **`[ ⚡ Run Live Simulation ]`**.
4. Watch ⚡ **Real-Time 5-Node Stepper Progress Bar** animate live.
5. When Audit Drawer opens, point cursor at **💬 WhatsApp Delivery Preview** card displaying 10% discount voucher **`RECOVER10`**.

##### 📢 SPOKEN VOICEOVER (Read Aloud)
> *"Next, Loop 2 addresses checkout abandonment. When a first-time shopper leaves a 2,999 rupee cart idle, RecoverAI classifies it as a recent abandon, the LLM recommends a discount nudge, and policy approves a 10% voucher — Code RECOVER10.*
>
> *The shopper receives a personalized WhatsApp notification directing them back to complete checkout."*

---

#### 🔸 SCENARIO 4: Margin Protection & Repeat Abandoner Policy Block

##### 🖱️ ON-SCREEN MOUSE & ACTION CUES
1. Close drawer **`✕`**.
2. In the **Loop 2 Toolbar**, select from dropdown: **`[ ⚡ Scenario: REPEAT_ABANDONER (Price Check - ₹7,999) ]`** (Option 3).
3. Click target button: **`[ ⚡ Run Live Simulation ]`**.
4. Watch ⚡ **Real-Time 5-Node Stepper Progress Bar** animate live.
5. Point cursor at Policy Decision: **`BLOCKED`** badge and **📢 Slack Escalation Alert** (`#cart-escalations`).

##### 📢 SPOKEN VOICEOVER (Read Aloud)
> *"However, if a customer repeatedly abandons carts, merchant policy restricts sending additional discount vouchers. The Policy Engine blocks the AI recommendation, protecting gross margins against discount abuse and escalating the cart to operations for manual review."*

---

### SECTION 4: Loop 3 — Duplicate Charge Financial Protection (3:30 – 4:30)

#### 🔹 SCENARIO 5: Live Pipeline Stepper & API Auto-Refund

##### 🖱️ ON-SCREEN MOUSE & ACTION CUES
1. Click top tab: **`Loop 3: Duplicate Charges`**.
2. In the **Loop 3 Toolbar**, select from dropdown: **`[ ⚡ Scenario: EXACT_DUPLICATE (Auto-Refund Approved) ]`** (Option 0).
3. Click target button: **`[ ⚡ Run Live Simulation ]`**.
4. Watch ⚡ **Real-Time 5-Node Stepper Progress Bar** animate live (`1. Ingest → 2. Classify → 3. AI Recommends → 4. Policy Reviews → 5. Execute`).
5. Point cursor at latency breakdown chip: **`LLM Reasoning: 15.2s · Policy Engine: 12ms · Action Executor: 45ms`**.

##### 📢 SPOKEN VOICEOVER (Read Aloud)
> *"Finally, Loop 3 handles financial exception management for duplicate charges. Let's trigger a live simulation for an accidental double-click event.*
>
> *Our real-time 5-node pipeline stepper measures execution latency down to the millisecond across classification, policy evaluation, and action execution. Policy approves an automated refund, executing the call through the Razorpay test API."*

---

#### 🔸 SCENARIO 6: Fraud Pattern Security Escalation

##### 🖱️ ON-SCREEN MOUSE & ACTION CUES
1. Close drawer **`✕`**.
2. In the **Loop 3 Toolbar**, select from dropdown: **`[ ⚡ Scenario: POSSIBLE_FRAUD (Fraud Override → Escalated to Security) ]`** (Option 2).
3. Click target button: **`[ ⚡ Run Live Simulation ]`**.
4. Watch ⚡ **Real-Time 5-Node Stepper Progress Bar** animate live (`AI: ESCALATE_AS_FRAUD → Policy: APPROVED → Execute: ESCALATE_AS_FRAUD`).
5. Point cursor at Policy Decision: **`APPROVED`** badge and **📢 Slack Security Alert** (`#security-alerts`).

##### 📢 SPOKEN VOICEOVER (Read Aloud)
> *"Let me show you Loop 3 for duplicate charges. When repeat duplicate patterns signal suspected fraud, we trigger our live simulation.*
>
> *Watch our 5-node stepper execute in real time: classifying the charge as EXACT_DUPLICATE. The LLM recommended ESCALATE_AS_FRAUD, and the Policy Engine APPROVED it, enforcing a fraud escalation to halt auto-refunds.*
>
> *Opening the UI Audit Timeline reveals the full event trace — proving every policy decision, Slack security alert, and execution result is logged without AI hallucination."*

---

### SECTION 5: Summary & Track 03 Metrics Wrap-Up (4:30 – 5:00)

#### 🖱️ ON-SCREEN MOUSE CUES
1. Click back to **`Loop 1: Payment Recovery`** tab.
2. Point cursor at top KPI summary cards (**Revenue At Risk: ₹6.5L+**, **Revenue Recovered: ₹70k+**, **Recovery Rate: 10.79%**).

#### 📢 SPOKEN VOICEOVER (Read Aloud)
> *"In summary: RecoverAI provides a bounded, policy-controlled framework that converts uncaptured revenue into verified recovery across payment failures, abandoned carts, and duplicate charges.*
>
> *Our measured batch results across 300 test scenarios demonstrate full auditability, explicit policy blocks, and verified outcomes. AI recommends, policy controls, actions execute, outcomes are verified, and every step is audited. Thank you!"*

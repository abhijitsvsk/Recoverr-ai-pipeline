"""
Data models and Enums for Loop 3: Duplicate Charge Detection & Auto-Refund.
100% isolated from Loop 1 and Loop 2 models.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class DupCategory(str, Enum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    LIKELY_DUPLICATE = "LIKELY_DUPLICATE"
    SUSPECTED_DUPLICATE = "SUSPECTED_DUPLICATE"
    UNRELATED = "UNRELATED"


class DupAction(str, Enum):
    AUTO_REFUND = "AUTO_REFUND"
    HOLD_FOR_REVIEW = "HOLD_FOR_REVIEW"
    ESCALATE_AS_FRAUD = "ESCALATE_AS_FRAUD"
    NO_ACTION = "NO_ACTION"


class DupStatus(str, Enum):
    INGESTED = "INGESTED"
    CLASSIFIED = "CLASSIFIED"
    RECOMMENDED = "RECOMMENDED"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_EXECUTION = "FAILED_EXECUTION"
    ESCALATED = "ESCALATED"
    NO_ACTION_TAKEN = "NO_ACTION_TAKEN"


@dataclass
class DupCharge:
    id: str
    customer_id: str
    order_id: str
    card_id: str
    amount_in_paise: int
    time_delta_seconds: int
    prior_duplicate_count: int
    purchase_type: str
    ground_truth_category: str
    status: str
    created_at: str
    updated_at: str
    category: Optional[str] = None
    recommended_action: Optional[str] = None
    recommendation_reason: Optional[str] = None
    policy_decision: Optional[str] = None
    policy_reason: Optional[str] = None
    action_taken: Optional[str] = None
    execution_result: Optional[str] = None
    business_outcome: Optional[str] = None

    @property
    def amount_in_inr(self) -> float:
        return self.amount_in_paise / 100.0


@dataclass
class DupAuditLogEntry:
    id: str
    event_id: str
    event_type: str
    charge_id: str
    timestamp: str
    amount_in_paise: int
    category: Optional[str] = None
    recommended_action: Optional[str] = None
    policy_decision: Optional[str] = None
    policy_reason: Optional[str] = None
    action_taken: Optional[str] = None
    execution_result: Optional[str] = None
    business_outcome: Optional[str] = None


@dataclass
class DupIdempotencyRecord:
    event_id: str
    charge_id: str
    processed_at: str

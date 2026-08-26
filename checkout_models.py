"""
Models and Dataclasses for Checkout Abandonment Loop 2 Foundation.
100% separate from Loop 1 payment models.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class CheckoutCategory(str, Enum):
    RECENT_ABANDON = "RECENT_ABANDON"
    STALE_ABANDON = "STALE_ABANDON"
    REPEAT_ABANDONER = "REPEAT_ABANDONER"
    HIGH_VALUE_ABANDON = "HIGH_VALUE_ABANDON"
    UNKNOWN_ABANDON = "UNKNOWN_ABANDON"


class CheckoutStatus(str, Enum):
    ABANDONED = "ABANDONED"
    CLASSIFIED = "CLASSIFIED"
    RECOMMENDED = "RECOMMENDED"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_EXECUTION = "FAILED_EXECUTION"
    ESCALATED = "ESCALATED"
    STOPPED = "STOPPED"


class CheckoutRecoveryAction(str, Enum):
    SEND_CART_REMINDER = "SEND_CART_REMINDER"
    SEND_DISCOUNT_NUDGE = "SEND_DISCOUNT_NUDGE"
    ESCALATE = "ESCALATE"
    STOP = "STOP"


@dataclass
class Checkout:
    id: str
    cart_value_in_paise: int
    customer_abandon_reason: str
    expected_category: str
    category: Optional[str]
    abandon_count: int
    status: str
    abandoned_at: str
    created_at: str
    updated_at: str
    recommended_action: Optional[str] = None
    recommendation_reason: Optional[str] = None
    policy_decision: Optional[str] = None
    policy_reason: Optional[str] = None
    cart_recovery_confirmed: bool = False


@dataclass
class CheckoutAuditLogEntry:
    id: str
    event_id: str
    event_type: str
    checkout_id: str
    timestamp: str
    cart_value_in_paise: int
    category: Optional[str] = None
    recommended_action: Optional[str] = None
    policy_decision: Optional[str] = None
    policy_reason: Optional[str] = None
    action_taken: Optional[str] = None
    execution_result: Optional[str] = None
    business_outcome: Optional[str] = None


@dataclass
class CheckoutIdempotencyRecord:
    event_id: str
    checkout_id: str
    processed_at: str

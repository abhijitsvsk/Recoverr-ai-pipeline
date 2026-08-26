"""
Data models and enum definitions for RecoverAI Payment Recovery Foundation.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class Category(str, Enum):
    TEMPORARY = "TEMPORARY"
    PERMANENT = "PERMANENT"
    REPEATED_FAILURE = "REPEATED_FAILURE"
    UNKNOWN = "UNKNOWN"


class RecoveryAction(str, Enum):
    RETRY = "RETRY"
    SEND_RECOVERY_LINK = "SEND_RECOVERY_LINK"
    ESCALATE = "ESCALATE"
    STOP = "STOP"


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


@dataclass
class Payment:
    id: str
    amount_in_paise: int
    failure_reason: str
    ground_truth_category: str
    category: Optional[str]
    status: str
    attempt_count: int
    last_attempt_at: str
    created_at: str
    updated_at: str
    recommended_action: Optional[str] = None
    recommendation_reason: Optional[str] = None


@dataclass
class AuditLogEntry:
    id: str
    event_id: str
    event_type: str
    payment_id: str
    attempt_number: int
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
class IdempotencyRecord:
    event_id: str
    payment_id: str
    processed_at: str

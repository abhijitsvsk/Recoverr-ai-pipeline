"""
Razorpay REST API Client for Live Test Mode Execution.
Uses Python standard library (urllib.request) with HTTP Basic Authentication.
100% separate from synthetic batch evaluation.
"""

import os
import json
import base64
import urllib.request
import urllib.error
from typing import Dict, Any, Optional


def _load_env_file(env_path: str = ".env") -> None:
    """Load key-value pairs from .env file into os.environ if present."""
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    val = v.strip()
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1].strip()
                    os.environ[k.strip()] = val


class RazorpayClient:
    def __init__(self, key_id: Optional[str] = None, key_secret: Optional[str] = None):
        _load_env_file()
        raw_key_id = (key_id or os.getenv("RAZORPAY_KEY_ID", "")).strip().strip('"').strip("'")
        raw_key_secret = (key_secret or os.getenv("RAZORPAY_KEY_SECRET", "")).strip().strip('"').strip("'")

        placeholder_patterns = [
            "rzp_test_key_sample123",
            "rzp_test_secret_sample123",
            "YOUR_KEY_ID",
            "YOUR_KEY_SECRET",
            "sample",
            "placeholder",
        ]

        is_key_invalid = (
            not raw_key_id
            or any(pat.lower() in raw_key_id.lower() for pat in placeholder_patterns)
        )
        is_secret_invalid = (
            not raw_key_secret
            or any(pat.lower() in raw_key_secret.lower() for pat in placeholder_patterns)
        )

        if is_key_invalid or is_secret_invalid:
            raise ValueError(
                "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET is not set — real Razorpay test credentials required in .env. "
                "Please configure valid RAZORPAY_KEY_ID (e.g. rzp_test_...) and RAZORPAY_KEY_SECRET in .env."
            )

        self.key_id = raw_key_id
        self.key_secret = raw_key_secret
        self.base_url = "https://api.razorpay.com/v1"

    def _get_auth_header(self) -> str:
        credentials = f"{self.key_id}:{self.key_secret}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        return f"Basic {encoded}"

    def _make_request(
        self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": self._get_auth_header(),
            "Content-Type": "application/json",
            "User-Agent": "RecoverAI-Razorpay-Client/1.0",
        }

        body_bytes = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req) as response:
                response_body = response.read().decode("utf-8")
                return {
                    "status_code": response.status,
                    "headers": dict(response.headers),
                    "body": json.loads(response_body),
                    "raw_body": response_body,
                }
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            try:
                parsed_json = json.loads(error_body)
            except Exception:
                parsed_json = {"error": error_body}
            return {
                "status_code": e.code,
                "headers": dict(e.headers),
                "body": parsed_json,
                "raw_body": error_body,
            }
        except Exception as e:
            return {
                "status_code": 500,
                "headers": {},
                "body": {"error": str(e)},
                "raw_body": json.dumps({"error": str(e)}),
            }

    def create_order(
        self, amount_in_paise: int, receipt: str, currency: str = "INR", notes: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Create an order via Razorpay Orders API: POST /v1/orders"""
        payload = {
            "amount": amount_in_paise,
            "currency": currency,
            "receipt": receipt,
            "notes": notes or {"source": "RecoverAI_Live_Test"},
        }
        return self._make_request("POST", "/orders", payload)

    def create_payment_link(
        self,
        amount_in_paise: int,
        description: str,
        customer: Optional[Dict[str, str]] = None,
        notes: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Create a payment recovery link via Razorpay Payment Links API: POST /v1/payment_links"""
        payload = {
            "amount": amount_in_paise,
            "currency": "INR",
            "description": description,
            "customer": customer or {"name": "Test Merchant Customer", "email": "customer@example.com"},
            "notify": {"sms": False, "email": True},
            "reminder_enable": True,
            "notes": notes or {"source": "RecoverAI_Recovery_Link"},
        }
        return self._make_request("POST", "/payment_links", payload)

    def get_payment(self, payment_id: str) -> Dict[str, Any]:
        """Fetch payment details via Razorpay Payments API: GET /v1/payments/{payment_id}"""
        return self._make_request("GET", f"/payments/{payment_id}")

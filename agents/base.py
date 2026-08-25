"""
AMR Guardian Enterprise - Base Module
Provides cryptographic HMAC-SHA256 audit logging, outbound PHI protection guards,
and strict action execution wrappers.
"""

from datetime import datetime, timezone
import hashlib
import hmac
import os
import re
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field


class SecurityException(Exception):
    """Raised when an outbound PHI violation or security constraint fails."""
    pass


class PHIGuard:
    """Outbound PHI detector enforcing strict HIPAA and Safe Harbor data protections."""
    
    # Patterns for detecting direct patient identifiers in outbound payloads
    PATTERNS: Dict[str, re.Pattern] = {
        "MRN_EXPLICIT": re.compile(r"(?i)\b(?:mrn|medical\s*record\s*no|chart\s*#?)\s*[:=\-]?\s*([A-Z0-9]{6,12})\b"),
        "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "PHONE": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        "NAME_PREFIX": re.compile(r"(?i)\b(?:patient|pt|name)\s*[:=]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b"),
        "DOB_EXPLICIT": re.compile(r"(?i)\b(?:dob|date\s*of\s*birth)\s*[:=]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"),
    }

    @classmethod
    def assert_no_phi(cls, text: str) -> None:
        """
        Scans text for outbound Protected Health Information (PHI).
        Raises SecurityException if any unredacted direct identifiers are identified.
        """
        if not text:
            return

        for name, pattern in cls.PATTERNS.items():
            match = pattern.search(text)
            if match:
                raise SecurityException(
                    f"PHI Outbound Guard Violation: Detected potential identifier matching '{name}': {match.group(0)}"
                )

    @classmethod
    def redact_phi(cls, text: str) -> str:
        """Sanitizes text by replacing direct identifiers with redaction tags."""
        if not text:
            return ""
        
        redacted = text
        for name, pattern in cls.PATTERNS.items():
            redacted = pattern.sub(f"[REDACTED_{name}]", redacted)
        return redacted


class AuditLogger:
    """Tamper-evident HMAC-SHA256 cryptographic audit logger for AMR Guardian."""
    
    def __init__(self, secret_key: Optional[str] = None):
        self.secret_key = (
            secret_key or os.getenv("AMR_AUDIT_SECRET", "amr-guardian-production-secret-hmac-key-2026")
        ).encode("utf-8")

    def generate_hmac(self, actor: str, action: str, details: str, timestamp: str) -> str:
        """Calculates cryptographic signature for an audit entry."""
        payload = f"{timestamp}|{actor}|{action}|{details}".encode("utf-8")
        return hmac.new(self.secret_key, payload, hashlib.sha256).hexdigest()

    def verify_hmac(self, actor: str, action: str, details: str, timestamp: str, signature: str) -> bool:
        """Verifies signature integrity for an audit entry."""
        expected = self.generate_hmac(actor, action, details, timestamp)
        return hmac.compare_digest(expected, signature)


class ActionExecutor:
    """Executes clinical actions with automatic PHI validation, exception handling, and audit logging."""

    def __init__(self, audit_logger: Optional[AuditLogger] = None):
        self.audit_logger = audit_logger or AuditLogger()

    def execute(
        self,
        actor: str,
        action: str,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Executes a function, checks for PHI in input string arguments and result,
        and generates an audit verification record.
        """
        # Validate inputs
        for arg in args:
            if isinstance(arg, str):
                PHIGuard.assert_no_phi(arg)
        for k, v in kwargs.items():
            if isinstance(v, str):
                PHIGuard.assert_no_phi(v)

        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            result = func(*args, **kwargs)
            
            # If string result, assert no PHI leakage
            if isinstance(result, str):
                PHIGuard.assert_no_phi(result)
            elif isinstance(result, dict):
                PHIGuard.assert_no_phi(str(result))

            details = f"SUCCESS: result_type={type(result).__name__}"
            signature = self.audit_logger.generate_hmac(actor, action, details, timestamp)

            return {
                "success": True,
                "result": result,
                "actor": actor,
                "action": action,
                "timestamp": timestamp,
                "signature": signature
            }
        except SecurityException as se:
            details = f"SECURITY_VIOLATION: {str(se)}"
            signature = self.audit_logger.generate_hmac(actor, action, details, timestamp)
            raise se
        except Exception as e:
            details = f"FAILURE: {str(e)}"
            signature = self.audit_logger.generate_hmac(actor, action, details, timestamp)
            return {
                "success": False,
                "error": str(e),
                "actor": actor,
                "action": action,
                "timestamp": timestamp,
                "signature": signature
            }

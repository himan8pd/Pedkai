"""
PII Scrubber Service.

Strips sensitive personal and network subscriber data from text before
any LLM prompt leaves Pedkai. Uses regex-only detection (no heavy NLP models)
for low latency and predictable behaviour.

Scrub manifest records what was removed (hashed) for audit purposes.
The original value is NEVER stored — only a SHA-256 hash.

Used by: WS2 (llm_service.py), WS8 (LLM adapter pipeline).
"""
import re
import hashlib
import logging
from typing import Dict, List, Tuple, Any, Optional

logger = logging.getLogger(__name__)

# Regex patterns for PII detection
_PATTERNS = {
    "phone_uk": re.compile(
        r"(\+44\s?[\d\s\-]{9,13}|0[1-9][\d\s\-]{8,12})",
        re.IGNORECASE,
    ),
    "phone_us": re.compile(
        r"(\+1[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4})",
        re.IGNORECASE,
    ),
    "imsi": re.compile(
        r"\b(\d{15})\b",  # 15-digit IMSI
    ),
    "subscriber_name": re.compile(
        r"((?:Customer|Subscriber):\s*)([A-Z][a-z]+ [A-Z][a-z]+)",
        re.IGNORECASE,
    ),
    "billing_amount": re.compile(
        r"([£$€]\s?\d+(?:[.,]\d{1,2})?(?:\s?(?:million|billion|k))?)",
        re.IGNORECASE,
    ),
    "account_number": re.compile(
        r"\b(?:account\s*(?:number|no\.?|#)?\s*:?\s*)(\d{5,12})\b",
        re.IGNORECASE,
    ),
    "ipv4": re.compile(
        r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b",
    ),
}

# Replacement tokens
_REPLACEMENTS = {
    "phone_uk": "[PHONE_REDACTED]",
    "phone_us": "[PHONE_REDACTED]",
    "imsi": "[IMSI_REDACTED]",
    "subscriber_name": "[NAME_REDACTED]",
    "billing_amount": "[AMOUNT_REDACTED]",
    "account_number": "[ACCOUNT_REDACTED]",
    "ipv4": "[IP_REDACTED]",
}


class PIIScrubber:
    """
    Regex-based PII scrubber for LLM prompt sanitisation.

    Configurable via constructor to include/exclude specific field types.
    All scrubbed values are hashed (SHA-256) in the manifest — originals are never stored.
    """

    def __init__(
        self,
        fields_to_scrub: Optional[List[str]] = None,
        fields_to_pass_through: Optional[List[str]] = None,
    ):
        """
        Args:
            fields_to_scrub: List of field types to scrub. Defaults to all.
            fields_to_pass_through: List of field types to skip (pass through unchanged).
        """
        all_fields = list(_PATTERNS.keys())
        self.fields_to_scrub = fields_to_scrub or all_fields
        self.fields_to_pass_through = set(fields_to_pass_through or [])

        # Active patterns: scrub minus pass-through
        self.active_fields = [
            f for f in self.fields_to_scrub if f not in self.fields_to_pass_through
        ]

    def scrub(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Scrub PII from text.

        Returns:
            (scrubbed_text, scrub_manifest)

        scrub_manifest is a list of dicts:
            {
                "field_type": str,
                "original_value_hash": str,  # SHA-256 of original, NOT the original
                "replacement": str,
            }
        """
        scrubbed = text
        manifest: List[Dict[str, Any]] = []

        for field_type in self.active_fields:
            pattern = _PATTERNS.get(field_type)
            replacement = _REPLACEMENTS.get(field_type, "[REDACTED]")

            if not pattern:
                continue

            if field_type == "subscriber_name":
                # Special case: keep the label, only redact the name
                def replace_name(m: re.Match) -> str:
                    label = m.group(1)
                    name = m.group(2)
                    manifest.append({
                        "field_type": field_type,
                        "original_value_hash": self._hash(name),
                        "replacement": replacement,
                    })
                    return f"{label}{replacement}"
                scrubbed = pattern.sub(replace_name, scrubbed)
            else:
                def make_replacer(ft: str, rep: str):
                    def replacer(m: re.Match) -> str:
                        original = m.group(0)
                        manifest.append({
                            "field_type": ft,
                            "original_value_hash": self._hash(original),
                            "replacement": rep,
                        })
                        return rep
                    return replacer
                scrubbed = pattern.sub(make_replacer(field_type, replacement), scrubbed)

        return scrubbed, manifest

    def _hash(self, value: str) -> str:
        """SHA-256 hash of a value, truncated to 16 hex chars for readability."""
        return hashlib.sha256(value.encode()).hexdigest()[:16]

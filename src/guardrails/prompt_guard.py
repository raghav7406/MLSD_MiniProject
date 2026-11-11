"""Input/output guardrails for the preauth system."""
import re


# Prompt injection patterns
_INJECTION_PATTERNS = [
    r"ignore\s+(previous|above|all)\s+(instructions?|prompts?|rules?)",
    r"you\s+are\s+now\s+",
    r"act\s+as\s+(if\s+you\s+are|a)\s+",
    r"forget\s+(everything|all|your)\s+",
    r"system\s*:\s*",
    r"<\s*(?:script|img|iframe|svg)",
    r"(?:SELECT|INSERT|UPDATE|DELETE|DROP|UNION)\s+",
    r"pretend\s+(?:to|you)",
    r"override\s+(?:your|the|all)",
    r"new\s+instructions?\s*:",
    r"disregard\s+",
    r"\{\{.*\}\}",
    r"\\x[0-9a-f]{2}",
]

_TOXIC_PATTERNS = [
    r"(?:kill|murder|harm|attack|bomb|weapon)\s+(?:the|a|this)",
]

_AUTHORIZATION_PATTERNS = [
    r"(?:hereby|officially|formally)\s+(?:approve|authorize|authorise|grant)",
    r"this\s+(?:request|claim|admission)\s+is\s+(?:approved|authorized|authorised)",
    r"coverage\s+is\s+(?:confirmed|guaranteed|assured)",
    r"we\s+(?:approve|authorize|authorise|confirm)",
]


def check_prompt_injection(*fields: str) -> str | None:
    """Check free-text fields for prompt injection patterns.

    Returns a description of the issue if detected, None if clean.
    """
    for field_value in fields:
        if not field_value:
            continue
        text = field_value.lower()
        for pattern in _INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return "Potential prompt injection detected: matched pattern in input"
    return None


def check_toxicity(*fields: str) -> str | None:
    """Check for toxic/unsafe content."""
    for field_value in fields:
        if not field_value:
            continue
        for pattern in _TOXIC_PATTERNS:
            if re.search(pattern, field_value.lower(), re.IGNORECASE):
                return "Toxic content detected in input"
    return None


def filter_output(text: str) -> str:
    """Filter model output to never claim to authorise an admission."""
    for pattern in _AUTHORIZATION_PATTERNS:
        text = re.sub(
            pattern,
            "[RECOMMENDATION ONLY - not an authorization]",
            text,
            flags=re.IGNORECASE,
        )
    return text


def validate_grounding(citations, retrieved_clauses) -> bool:
    """Check that every citation is grounded in the retrieved clauses.

    Uses substring matching so truncated citation text still validates against
    the full retrieved passage.
    """
    retrieved_texts: list[str] = []
    for clause in retrieved_clauses:
        if isinstance(clause, dict):
            retrieved_texts.append(clause.get("text", ""))
        elif isinstance(clause, str):
            retrieved_texts.append(clause)
        else:
            retrieved_texts.append(getattr(clause, "text", str(clause)))

    def _is_grounded(clause_text: str) -> bool:
        if not clause_text:
            return True
        # Exact match
        if clause_text in retrieved_texts:
            return True
        # Substring match (handles truncated citations)
        for rt in retrieved_texts:
            if clause_text in rt or rt in clause_text:
                return True
        return False

    for citation in citations:
        if isinstance(citation, dict):
            clause_text = citation.get("clause", "")
        else:
            clause_text = getattr(citation, "clause", "")
        if not _is_grounded(clause_text):
            return False
    return True

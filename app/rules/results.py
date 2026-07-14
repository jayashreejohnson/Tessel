import enum

from pydantic import BaseModel


class RuleStatus(str, enum.Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    NEEDS_REVIEW = "NEEDS_REVIEW"  # genuinely ambiguous — the LLM escalation layer's input


class RuleFinding(BaseModel):
    rule_name: str
    applicant_id: int
    status: RuleStatus

    subject_event_ids: list[int]
    """Timeline events this finding is about (e.g. the gap and the candidate EAD_PENDING event)."""

    what_happened: str
    """Plain-language narrative of what was evaluated and observed."""

    supporting_evidence_ids: list[int] = []
    """evidence_documents.id values backing this finding, if any."""

    unresolved_reason: str | None = None
    what_would_resolve: str | None = None

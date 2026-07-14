import enum

from pydantic import BaseModel


class EscalationResolution(str, enum.Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"


class EscalationDecision(BaseModel):
    resolution: EscalationResolution
    reasoning: str
    cited_event_ids: list[int] = []
    cited_evidence_ids: list[int] = []
    what_would_resolve: str | None = None


ESCALATION_TOOL = {
    "name": "record_escalation_decision",
    "description": (
        "Record your evidence-grounded decision about this ambiguous case. "
        "Ground every claim in the structured records provided — do not infer "
        "facts, dates, or amounts that are not present in the input."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "resolution": {
                "type": "string",
                "enum": ["RESOLVED", "UNRESOLVED", "ESCALATE_TO_HUMAN"],
                "description": (
                    "RESOLVED: the evidence provided satisfactorily explains the ambiguity. "
                    "UNRESOLVED: the evidence provided does not support the pattern, despite "
                    "reaching this stage. ESCALATE_TO_HUMAN: still genuinely ambiguous even "
                    "after review — a person should decide."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "Concise explanation, grounded only in the provided records.",
            },
            "cited_event_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "IDs of the timeline_events records this decision relied on.",
            },
            "cited_evidence_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "IDs of the evidence_documents records this decision relied on.",
            },
            "what_would_resolve": {
                "type": ["string", "null"],
                "description": (
                    "If not RESOLVED, the specific evidence or information that would resolve "
                    "it. Null if resolution is RESOLVED."
                ),
            },
        },
        "required": [
            "resolution",
            "reasoning",
            "cited_event_ids",
            "cited_evidence_ids",
            "what_would_resolve",
        ],
        "additionalProperties": False,
    },
}

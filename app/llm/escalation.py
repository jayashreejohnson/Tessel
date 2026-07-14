import json

import anthropic
import pydantic
from sqlalchemy.orm import Session

from app.llm.context import build_context
from app.llm.schemas import ESCALATION_TOOL, EscalationDecision, EscalationResolution
from app.models import AuditLogEntry

MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """\
You are the escalation-review step in a lending evidence system. A \
deterministic rule engine has already evaluated one case and could not \
resolve it on dates and evidence-link status alone — that is the only \
reason you are being asked.

You are given the exact structured records the rule engine considered: \
timeline events and evidence documents, nothing else. Decide whether this \
specific ambiguity should now be treated as:
- RESOLVED — the evidence provided satisfactorily explains it
- UNRESOLVED — the evidence does not support the pattern
- ESCALATE_TO_HUMAN — still genuinely ambiguous; a person should decide

You are not producing a risk score or an approval decision. Ground every \
claim in the records provided — never invent a fact, date, or amount that \
is not present in the input. Always call record_escalation_decision.
"""


def escalate(db: Session, entry: AuditLogEntry, client: anthropic.Anthropic | None = None) -> EscalationDecision:
    """
    Sends one NEEDS_REVIEW rule-check entry to Claude for review via forced,
    schema-constrained tool use. On any API failure, defaults to
    ESCALATE_TO_HUMAN rather than silently dropping the case.
    """
    context = build_context(db, entry)
    client = client or anthropic.Anthropic()

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[ESCALATION_TOOL],
            tool_choice={"type": "tool", "name": "record_escalation_decision"},
            messages=[{"role": "user", "content": json.dumps(context, indent=2)}],
        )
        tool_use = next(b for b in response.content if b.type == "tool_use")
        return EscalationDecision(**tool_use.input)
    except (
        anthropic.APIError,
        anthropic.APIConnectionError,
        StopIteration,
        ValueError,
        TypeError,  # e.g. missing credentials — raised before any request is sent
        pydantic.ValidationError,
    ) as e:
        return EscalationDecision(
            resolution=EscalationResolution.ESCALATE_TO_HUMAN,
            reasoning=f"LLM escalation call failed or returned an unusable response: {e}",
            what_would_resolve="Retry the escalation call, or route directly to human review.",
        )

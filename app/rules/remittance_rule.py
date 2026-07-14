from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import EventType, TimelineEvent
from app.rules.config import TRANSFER_WINDOW_BUFFER_DAYS
from app.rules.results import RuleFinding, RuleStatus

RULE_NAME = "remittance_explains_income_gap"


def evaluate(db: Session, gap: TimelineEvent) -> RuleFinding:
    assert gap.event_type == EventType.INCOME_GAP

    buffer = timedelta(days=TRANSFER_WINDOW_BUFFER_DAYS)
    window_start = gap.start_date - buffer
    window_end = (gap.end_date + buffer) if gap.end_date else None

    query = db.query(TimelineEvent).filter(
        TimelineEvent.applicant_id == gap.applicant_id,
        TimelineEvent.event_type == EventType.INTL_TRANSFER_RECEIVED,
        TimelineEvent.start_date >= window_start,
    )
    if window_end is not None:
        query = query.filter(TimelineEvent.start_date <= window_end)
    transfers = query.order_by(TimelineEvent.start_date).all()

    gap_label = f"{gap.start_date} to {gap.end_date or 'present'}"

    if not transfers:
        return RuleFinding(
            rule_name=RULE_NAME,
            applicant_id=gap.applicant_id,
            status=RuleStatus.UNRESOLVED,
            subject_event_ids=[gap.id],
            what_happened=f"No international transfers found during the income gap ({gap_label}).",
            unresolved_reason="No INTL_TRANSFER_RECEIVED events fall within the gap window "
            f"(±{TRANSFER_WINDOW_BUFFER_DAYS} days).",
            what_would_resolve="Confirm whether any international transfers were received during this period.",
        )

    senders = ", ".join(t.counterparty or "unknown sender" for t in transfers)

    # The temporal fact is now certain. Whether the pattern is plausibly
    # "family support during the gap" — as opposed to, say, a business
    # payment that happens to land in the same window — isn't something a
    # date comparison can decide. That judgment is deliberately left to the
    # LLM escalation layer; this rule only ever narrows the ambiguity, never
    # resolves it.
    return RuleFinding(
        rule_name=RULE_NAME,
        applicant_id=gap.applicant_id,
        status=RuleStatus.NEEDS_REVIEW,
        subject_event_ids=[gap.id, *[t.id for t in transfers]],
        what_happened=(
            f"{len(transfers)} international transfer(s) received during the income gap ({gap_label}), "
            f"from: {senders}."
        ),
        unresolved_reason="Temporal alignment is confirmed; whether this reflects a plausible "
        "family-support pattern (vs. unrelated transfer) requires judgment.",
        what_would_resolve="LLM or human review of counterparty relationship, amount, and frequency.",
    )

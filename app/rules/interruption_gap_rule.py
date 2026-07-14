from datetime import date, timedelta
from enum import Enum

from sqlalchemy.orm import Session

from app.models import EventCategory, EventEvidenceLink, EventType, MatchType, TimelineEvent
from app.rules.config import INTERRUPTION_ALIGNMENT_TOLERANCE_DAYS
from app.rules.results import RuleFinding, RuleStatus

RULE_NAME = "authorized_interruption_explains_income_gap"


class Alignment(str, Enum):
    FULL = "FULL"       # gap falls inside the interruption span (± tolerance)
    PARTIAL = "PARTIAL"  # spans overlap but neither contains the other
    NONE = "NONE"        # spans don't overlap at all


def _classify(
    gap_start: date,
    gap_end: date | None,
    interruption_start: date,
    interruption_end: date | None,
    as_of: date,
    tolerance_days: int,
) -> Alignment:
    tolerance = timedelta(days=tolerance_days)
    effective_gap_end = gap_end or as_of
    effective_interruption_end = interruption_end or as_of

    lo = interruption_start - tolerance
    hi = effective_interruption_end + tolerance

    if gap_start >= lo and effective_gap_end <= hi:
        return Alignment.FULL
    if gap_start <= hi and lo <= effective_gap_end:
        return Alignment.PARTIAL
    return Alignment.NONE


def evaluate(db: Session, gap: TimelineEvent, as_of: date) -> RuleFinding:
    """
    Checks whether an income gap aligns with a documented, evidence-backed
    authorized interruption — any EventType in the AUTHORIZED_INTERRUPTION
    category. F-1/OPT (EAD_PENDING) is the one instance populated today; a
    future interruption type (a leave, a severance/notice period) is a new
    EventType in the same category and needs no change here.
    """
    assert gap.event_type == EventType.INCOME_GAP

    interruption_events = (
        db.query(TimelineEvent)
        .filter(
            TimelineEvent.applicant_id == gap.applicant_id,
            TimelineEvent.category == EventCategory.AUTHORIZED_INTERRUPTION,
        )
        .all()
    )

    gap_label = f"{gap.start_date} to {gap.end_date or 'present'}"

    if not interruption_events:
        return RuleFinding(
            rule_name=RULE_NAME,
            applicant_id=gap.applicant_id,
            status=RuleStatus.UNRESOLVED,
            subject_event_ids=[gap.id],
            what_happened=f"Income gap from {gap_label} has no documented authorized interruption on file to align with.",
            unresolved_reason="No authorized-interruption status exists for this applicant.",
            what_would_resolve="Record the interruption's start date, ideally backed by supporting documentation.",
        )

    best_event, best_alignment = None, Alignment.NONE
    for event in interruption_events:
        alignment = _classify(
            gap.start_date, gap.end_date, event.start_date, event.end_date, as_of, INTERRUPTION_ALIGNMENT_TOLERANCE_DAYS
        )
        if alignment == Alignment.FULL:
            best_event, best_alignment = event, alignment
            break
        if alignment == Alignment.PARTIAL and best_alignment == Alignment.NONE:
            best_event, best_alignment = event, alignment

    if best_alignment == Alignment.NONE:
        return RuleFinding(
            rule_name=RULE_NAME,
            applicant_id=gap.applicant_id,
            status=RuleStatus.UNRESOLVED,
            subject_event_ids=[gap.id, *[e.id for e in interruption_events]],
            what_happened=f"Income gap from {gap_label} does not overlap any documented authorized-interruption span.",
            unresolved_reason="Gap dates and authorized-interruption span(s) do not align, even with a "
            f"{INTERRUPTION_ALIGNMENT_TOLERANCE_DAYS}-day tolerance.",
            what_would_resolve="Confirm the gap dates or the interruption's recorded start date — one of them is likely wrong.",
        )

    if best_alignment == Alignment.PARTIAL:
        return RuleFinding(
            rule_name=RULE_NAME,
            applicant_id=gap.applicant_id,
            status=RuleStatus.NEEDS_REVIEW,
            subject_event_ids=[gap.id, best_event.id],
            what_happened=(
                f"Income gap from {gap_label} partially overlaps the authorized-interruption span "
                f"({best_event.start_date} to {best_event.end_date or 'ongoing'}), but neither contains the other."
            ),
            unresolved_reason="Partial overlap is ambiguous — could be normal reporting lag or a genuine mismatch.",
            what_would_resolve="Human or LLM review of the exact gap boundaries against the supporting document's date.",
        )

    # FULL alignment: the dates are certain. What's left is whether it's evidenced.
    link = (
        db.query(EventEvidenceLink)
        .filter(EventEvidenceLink.timeline_event_id == best_event.id)
        .order_by(EventEvidenceLink.similarity_score.desc())
        .first()
    )

    if link and link.match_type == MatchType.SUPPORTS:
        return RuleFinding(
            rule_name=RULE_NAME,
            applicant_id=gap.applicant_id,
            status=RuleStatus.RESOLVED,
            subject_event_ids=[gap.id, best_event.id],
            what_happened=(
                f"Income gap from {gap_label} falls fully within the documented authorized-interruption span "
                f"({best_event.start_date} to {best_event.end_date or 'ongoing'}), confirmed by supporting evidence."
            ),
            supporting_evidence_ids=[link.evidence_document_id],
        )

    reason = (
        "No evidence document is linked to the authorized-interruption status."
        if link is None
        else f"Linked evidence document's match to the authorized-interruption status is '{link.match_type.value}', not a clear support."
    )
    return RuleFinding(
        rule_name=RULE_NAME,
        applicant_id=gap.applicant_id,
        status=RuleStatus.NEEDS_REVIEW,
        subject_event_ids=[gap.id, best_event.id],
        what_happened=(
            f"Income gap from {gap_label} aligns with the authorized-interruption span "
            f"({best_event.start_date} to {best_event.end_date or 'ongoing'}), but the supporting evidence is not conclusive."
        ),
        supporting_evidence_ids=[link.evidence_document_id] if link else [],
        unresolved_reason=reason,
        what_would_resolve="Upload or re-check the supporting document for this applicant's interruption status.",
    )

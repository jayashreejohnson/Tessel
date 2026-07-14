from datetime import date, timedelta
from enum import Enum

from sqlalchemy.orm import Session

from app.models import EventEvidenceLink, EventType, MatchType, TimelineEvent
from app.rules.config import EAD_ALIGNMENT_TOLERANCE_DAYS
from app.rules.results import RuleFinding, RuleStatus

RULE_NAME = "ead_pending_explains_income_gap"


class Alignment(str, Enum):
    FULL = "FULL"       # gap falls inside the pending span (± tolerance)
    PARTIAL = "PARTIAL"  # spans overlap but neither contains the other
    NONE = "NONE"        # spans don't overlap at all


def _classify(
    gap_start: date,
    gap_end: date | None,
    pending_start: date,
    pending_end: date | None,
    as_of: date,
    tolerance_days: int,
) -> Alignment:
    tolerance = timedelta(days=tolerance_days)
    effective_gap_end = gap_end or as_of
    effective_pending_end = pending_end or as_of

    lo = pending_start - tolerance
    hi = effective_pending_end + tolerance

    if gap_start >= lo and effective_gap_end <= hi:
        return Alignment.FULL
    if gap_start <= hi and lo <= effective_gap_end:
        return Alignment.PARTIAL
    return Alignment.NONE


def evaluate(db: Session, gap: TimelineEvent, as_of: date) -> RuleFinding:
    assert gap.event_type == EventType.INCOME_GAP

    pending_events = (
        db.query(TimelineEvent)
        .filter(
            TimelineEvent.applicant_id == gap.applicant_id,
            TimelineEvent.event_type == EventType.EAD_PENDING,
        )
        .all()
    )

    gap_label = f"{gap.start_date} to {gap.end_date or 'present'}"

    if not pending_events:
        return RuleFinding(
            rule_name=RULE_NAME,
            applicant_id=gap.applicant_id,
            status=RuleStatus.UNRESOLVED,
            subject_event_ids=[gap.id],
            what_happened=f"Income gap from {gap_label} has no EAD_PENDING status on file to align with.",
            unresolved_reason="No documented EAD-pending status exists for this applicant.",
            what_would_resolve="Record an EAD filing/receipt date, ideally backed by the I-797C receipt notice.",
        )

    best_pe, best_alignment = None, Alignment.NONE
    for pe in pending_events:
        alignment = _classify(
            gap.start_date, gap.end_date, pe.start_date, pe.end_date, as_of, EAD_ALIGNMENT_TOLERANCE_DAYS
        )
        if alignment == Alignment.FULL:
            best_pe, best_alignment = pe, alignment
            break
        if alignment == Alignment.PARTIAL and best_alignment == Alignment.NONE:
            best_pe, best_alignment = pe, alignment

    if best_alignment == Alignment.NONE:
        return RuleFinding(
            rule_name=RULE_NAME,
            applicant_id=gap.applicant_id,
            status=RuleStatus.UNRESOLVED,
            subject_event_ids=[gap.id, *[pe.id for pe in pending_events]],
            what_happened=f"Income gap from {gap_label} does not overlap any documented EAD-pending span.",
            unresolved_reason="Gap dates and EAD-pending span(s) do not align, even with a "
            f"{EAD_ALIGNMENT_TOLERANCE_DAYS}-day tolerance.",
            what_would_resolve="Confirm the gap dates or the EAD filing date — one of them is likely wrong.",
        )

    if best_alignment == Alignment.PARTIAL:
        return RuleFinding(
            rule_name=RULE_NAME,
            applicant_id=gap.applicant_id,
            status=RuleStatus.NEEDS_REVIEW,
            subject_event_ids=[gap.id, best_pe.id],
            what_happened=(
                f"Income gap from {gap_label} partially overlaps the EAD-pending span "
                f"({best_pe.start_date} to {best_pe.end_date or 'ongoing'}), but neither contains the other."
            ),
            unresolved_reason="Partial overlap is ambiguous — could be normal processing lag or a genuine mismatch.",
            what_would_resolve="Human or LLM review of the exact gap boundaries against the EAD notice date.",
        )

    # FULL alignment: the dates are certain. What's left is whether it's evidenced.
    link = (
        db.query(EventEvidenceLink)
        .filter(EventEvidenceLink.timeline_event_id == best_pe.id)
        .order_by(EventEvidenceLink.similarity_score.desc())
        .first()
    )

    if link and link.match_type == MatchType.SUPPORTS:
        return RuleFinding(
            rule_name=RULE_NAME,
            applicant_id=gap.applicant_id,
            status=RuleStatus.RESOLVED,
            subject_event_ids=[gap.id, best_pe.id],
            what_happened=(
                f"Income gap from {gap_label} falls fully within the documented EAD-pending span "
                f"({best_pe.start_date} to {best_pe.end_date or 'ongoing'}), confirmed by supporting evidence."
            ),
            supporting_evidence_ids=[link.evidence_document_id],
        )

    reason = (
        "No evidence document is linked to the EAD-pending status."
        if link is None
        else f"Linked evidence document's match to EAD-pending status is '{link.match_type.value}', not a clear support."
    )
    return RuleFinding(
        rule_name=RULE_NAME,
        applicant_id=gap.applicant_id,
        status=RuleStatus.NEEDS_REVIEW,
        subject_event_ids=[gap.id, best_pe.id],
        what_happened=(
            f"Income gap from {gap_label} aligns with the EAD-pending span "
            f"({best_pe.start_date} to {best_pe.end_date or 'ongoing'}), but the supporting evidence is not conclusive."
        ),
        supporting_evidence_ids=[link.evidence_document_id] if link else [],
        unresolved_reason=reason,
        what_would_resolve="Upload or re-check the EAD receipt notice for this applicant.",
    )

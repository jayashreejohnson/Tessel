from sqlalchemy.orm import Session

from app.models import (
    Applicant,
    AuditEventType,
    EventCategory,
    EventSource,
    EventType,
    EventEvidenceLink,
    EvidenceDocument,
    MatchType,
    RuleRun,
    TimelineEvent,
    AuditLogEntry,
)

_ACRONYMS = {"EAD", "INTL", "RAG"}


def pretty_label(value: str) -> str:
    """Formats an ENUM_VALUE-style string for display, preserving known acronyms."""
    return " ".join(w if w.upper() in _ACRONYMS else w.capitalize() for w in value.split("_"))


def _derive_current_stage(events: list[TimelineEvent], links: list[EventEvidenceLink]) -> dict:
    """
    Leads with a generic financial-risk headline — income continuity is the
    primary framing for any underwriting audience, regardless of what kind
    of interruption is behind a gap. The specific interruption type (EAD
    pending, or whatever a future scenario populates) only appears in the
    secondary "basis" line, where that precision is actually earned.
    """
    links_by_event: dict[int, list[EventEvidenceLink]] = {}
    for link in links:
        links_by_event.setdefault(link.timeline_event_id, []).append(link)

    def is_verified(event: TimelineEvent) -> bool:
        return any(l.match_type == MatchType.SUPPORTS for l in links_by_event.get(event.id, []))

    interruption_events = [e for e in events if e.category == EventCategory.AUTHORIZED_INTERRUPTION]
    any_gap = any(e.event_type == EventType.INCOME_GAP for e in events)
    open_gap = any(e.event_type == EventType.INCOME_GAP and e.end_date is None for e in events)

    basis = None
    if interruption_events:
        latest = sorted(interruption_events, key=lambda e: e.start_date)[-1]
        basis = f"{pretty_label(latest.event_type.value)} ({'verified' if is_verified(latest) else 'unverified'})"

    if not any_gap:
        headline = "Income Continuity — No Interruption Detected"
    elif interruption_events and is_verified(sorted(interruption_events, key=lambda e: e.start_date)[-1]):
        headline = "Income Interruption — Verified" + (" (Ongoing)" if open_gap else " (Resolved)")
    elif interruption_events:
        headline = "Income Interruption — Awaiting Evidence Confirmation"
    else:
        headline = "Income Interruption — Unexplained"

    return {"headline": headline, "basis": basis}


def _build_milestones(events: list[TimelineEvent], links: list[EventEvidenceLink]) -> list[dict]:
    links_by_event: dict[int, list[EventEvidenceLink]] = {}
    for link in links:
        links_by_event.setdefault(link.timeline_event_id, []).append(link)

    milestones = []
    for event in events:
        is_status_milestone = event.category in (EventCategory.AUTHORIZED_INTERRUPTION, EventCategory.CASE_STATUS)
        is_gap_milestone = event.event_type == EventType.INCOME_GAP
        if not (is_status_milestone or is_gap_milestone):
            continue

        event_links = links_by_event.get(event.id, [])
        best_link = max(event_links, key=lambda l: l.similarity_score or 0, default=None)
        milestones.append(
            {
                "event": event,
                "verified": best_link is not None and best_link.match_type == MatchType.SUPPORTS,
                "link": best_link,
            }
        )
    return sorted(milestones, key=lambda m: m["event"].start_date)


def _build_evidence_matches(
    links: list[EventEvidenceLink], documents: list[EvidenceDocument], events: list[TimelineEvent]
) -> list[dict]:
    docs_by_id = {d.id: d for d in documents}
    events_by_id = {e.id: e for e in events}
    return [
        {
            "document": docs_by_id.get(link.evidence_document_id),
            "event": events_by_id.get(link.timeline_event_id),
            "match_type": link.match_type,
            "similarity_score": link.similarity_score,
        }
        for link in links
    ]


def _build_findings(audit_entries: list[AuditLogEntry], latest_run_id: int | None) -> list[dict]:
    """
    Findings shows only the LATEST run's RULE_CHECK entries — re-running the
    engine creates new audit rows rather than overwriting old ones (by
    design, for history), but showing every run ever computed here would
    read as duplication or contradiction. The full history still lives in
    the Audit Log section below, unfiltered.
    """
    rule_checks = [
        e for e in audit_entries if e.event_type == AuditEventType.RULE_CHECK and e.run_id == latest_run_id
    ]
    escalations_by_source: dict[int, list[AuditLogEntry]] = {}
    for entry in audit_entries:
        if entry.event_type == AuditEventType.LLM_CALL and entry.source_entry_id:
            escalations_by_source.setdefault(entry.source_entry_id, []).append(entry)

    return [
        {"rule_check": rc, "escalations": escalations_by_source.get(rc.id, [])}
        for rc in sorted(rule_checks, key=lambda e: e.created_at)
    ]


def _build_human_decisions(audit_entries: list[AuditLogEntry]) -> list[AuditLogEntry]:
    decisions = [e for e in audit_entries if e.event_type == AuditEventType.HUMAN_DECISION]
    return sorted(decisions, key=lambda e: e.created_at, reverse=True)


def build_evidence_trail(db: Session, applicant_id: int) -> dict | None:
    """
    Assembles the full evidence trail for one applicant: current stage,
    verified milestones, real Plaid-sourced transactions, RAG evidence
    matches, rule findings (with any LLM escalation nested under the finding
    it escalated), and the complete chronological audit log. Pure read —
    doesn't trigger ingestion, matching, or rule runs; it reports whatever
    has already been computed and persisted for this applicant.
    """
    applicant = db.get(Applicant, applicant_id)
    if applicant is None:
        return None

    events = (
        db.query(TimelineEvent)
        .filter(TimelineEvent.applicant_id == applicant_id)
        .order_by(TimelineEvent.start_date)
        .all()
    )
    documents = db.query(EvidenceDocument).filter(EvidenceDocument.applicant_id == applicant_id).all()
    links = (
        db.query(EventEvidenceLink)
        .join(TimelineEvent, EventEvidenceLink.timeline_event_id == TimelineEvent.id)
        .filter(TimelineEvent.applicant_id == applicant_id)
        .all()
    )
    audit_entries = (
        db.query(AuditLogEntry)
        .filter(AuditLogEntry.applicant_id == applicant_id)
        .order_by(AuditLogEntry.created_at)
        .all()
    )
    latest_run = (
        db.query(RuleRun)
        .filter(RuleRun.applicant_id == applicant_id)
        .order_by(RuleRun.created_at.desc())
        .first()
    )

    transactions = [e for e in events if e.source == EventSource.BANK_FEED]

    return {
        "applicant": applicant,
        "current_stage": _derive_current_stage(events, links),
        "milestones": _build_milestones(events, links),
        "transactions": sorted(transactions, key=lambda e: e.start_date),
        "evidence_matches": _build_evidence_matches(links, documents, events),
        "findings": _build_findings(audit_entries, latest_run.id if latest_run else None),
        "human_decisions": _build_human_decisions(audit_entries),
        "latest_run_id": latest_run.id if latest_run else None,
        "audit_log": audit_entries,
    }

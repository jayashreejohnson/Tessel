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
    TimelineEvent,
    AuditLogEntry,
)

_STAGE_ORDER = [
    (EventType.EAD_DENIED, "EAD Denied"),
    (EventType.EAD_APPROVED, "OPT Authorized (EAD Approved)"),
    (EventType.EAD_PENDING, "OPT Application Pending"),
    (EventType.F1_ACTIVE, "F-1 Active"),
]


def _derive_current_stage(events: list[TimelineEvent]) -> str:
    immigration_types = {e.event_type for e in events if e.category == EventCategory.IMMIGRATION_STATUS}

    stage = "No immigration-status data recorded"
    for event_type, label in _STAGE_ORDER:
        if event_type in immigration_types:
            stage = label
            break

    if any(e.event_type == EventType.INCOME_GAP and e.end_date is None for e in events):
        stage += " — income gap ongoing"

    return stage


def _build_milestones(events: list[TimelineEvent], links: list[EventEvidenceLink]) -> list[dict]:
    links_by_event: dict[int, list[EventEvidenceLink]] = {}
    for link in links:
        links_by_event.setdefault(link.timeline_event_id, []).append(link)

    milestones = []
    for event in events:
        is_status_milestone = event.category == EventCategory.IMMIGRATION_STATUS
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


def _build_findings(audit_entries: list[AuditLogEntry]) -> list[dict]:
    rule_checks = [e for e in audit_entries if e.event_type == AuditEventType.RULE_CHECK]
    escalations_by_source: dict[int, list[AuditLogEntry]] = {}
    for entry in audit_entries:
        if entry.event_type == AuditEventType.LLM_CALL and entry.source_entry_id:
            escalations_by_source.setdefault(entry.source_entry_id, []).append(entry)

    return [
        {"rule_check": rc, "escalations": escalations_by_source.get(rc.id, [])}
        for rc in sorted(rule_checks, key=lambda e: e.created_at)
    ]


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

    transactions = [e for e in events if e.source == EventSource.BANK_FEED]

    return {
        "applicant": applicant,
        "current_stage": _derive_current_stage(events),
        "milestones": _build_milestones(events, links),
        "transactions": sorted(transactions, key=lambda e: e.start_date),
        "evidence_matches": _build_evidence_matches(links, documents, events),
        "findings": _build_findings(audit_entries),
        "audit_log": audit_entries,
    }

from sqlalchemy.orm import Session

from app.models import AuditLogEntry, EvidenceDocument, TimelineEvent


def build_context(db: Session, entry: AuditLogEntry) -> dict:
    """
    Assembles the exact structured records a NEEDS_REVIEW rule-check entry
    considered, for the LLM escalation layer. The model sees only this — no
    open-ended DB access — so its decision is grounded in what the rule engine
    actually evaluated, not whatever it might otherwise infer or look up.
    """
    events = (
        db.query(TimelineEvent)
        .filter(TimelineEvent.id.in_(entry.subject_event_ids or []))
        .all()
    )
    evidence = (
        db.query(EvidenceDocument)
        .filter(EvidenceDocument.id.in_(entry.supporting_evidence_ids or []))
        .all()
    )
    finding_detail = entry.detail.get("finding", {})

    return {
        "rule_name": entry.actor,
        "status": entry.status,
        "summary": entry.summary,
        "unresolved_reason": finding_detail.get("unresolved_reason"),
        "what_would_resolve": finding_detail.get("what_would_resolve"),
        "timeline_events": [
            {
                "id": e.id,
                "event_type": e.event_type.value,
                "start_date": e.start_date.isoformat(),
                "end_date": e.end_date.isoformat() if e.end_date else None,
                "amount": float(e.amount) if e.amount is not None else None,
                "currency": e.currency,
                "counterparty": e.counterparty,
                "source": e.source.value,
            }
            for e in events
        ],
        "evidence_documents": [
            {
                "id": d.id,
                "doc_type": d.doc_type.value,
                "raw_text": d.raw_text,
                "uploaded_at": d.uploaded_at.isoformat(),
            }
            for d in evidence
        ],
    }

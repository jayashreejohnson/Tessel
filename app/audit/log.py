from datetime import date

from sqlalchemy.orm import Session

from app.llm.context import build_context
from app.llm.escalation import MODEL as LLM_MODEL
from app.llm.escalation import escalate
from app.models import AuditEventType, AuditLogEntry, EvidenceDocument, RuleRun, TimelineEvent
from app.rag.config import EMBEDDING_MODEL_NAME
from app.rag.matcher import match_document_to_event
from app.rules import config as rule_config
from app.rules.engine import run_transition_check
from app.rules.results import RuleFinding, RuleStatus

_CONFIG_SNAPSHOT = {
    "MIN_GAP_DAYS": rule_config.MIN_GAP_DAYS,
    "INTERRUPTION_ALIGNMENT_TOLERANCE_DAYS": rule_config.INTERRUPTION_ALIGNMENT_TOLERANCE_DAYS,
    "TRANSFER_WINDOW_BUFFER_DAYS": rule_config.TRANSFER_WINDOW_BUFFER_DAYS,
}


def persist_findings(
    db: Session,
    applicant_id: int,
    as_of: date,
    findings: list[RuleFinding],
    triggered_by: str = "system",
) -> RuleRun:
    """
    Writes one RuleRun plus one AuditLogEntry per finding. Every call creates
    new rows — re-running the engine never overwrites prior findings, so the
    history of what was concluded at each point in time is preserved.
    """
    run = RuleRun(applicant_id=applicant_id, as_of_date=as_of, triggered_by=triggered_by)
    db.add(run)
    db.flush()  # assigns run.id without committing

    for finding in findings:
        db.add(
            AuditLogEntry(
                run_id=run.id,
                applicant_id=applicant_id,
                event_type=AuditEventType.RULE_CHECK,
                actor=finding.rule_name,
                status=finding.status.value,
                summary=finding.what_happened,
                subject_event_ids=finding.subject_event_ids,
                supporting_evidence_ids=finding.supporting_evidence_ids,
                detail={
                    "config": _CONFIG_SNAPSHOT,
                    "as_of": as_of.isoformat(),
                    "finding": finding.model_dump(mode="json"),
                },
            )
        )

    db.commit()
    db.refresh(run)
    return run


def run_and_log(db: Session, applicant_id: int, as_of: date, triggered_by: str = "system") -> RuleRun:
    """Runs the deterministic rule engine and persists every finding it produces."""
    findings = run_transition_check(db, applicant_id, as_of)
    return persist_findings(db, applicant_id, as_of, findings, triggered_by)


def persist_escalation(db: Session, source_entry: AuditLogEntry, client=None) -> AuditLogEntry:
    """
    Sends one NEEDS_REVIEW RULE_CHECK entry to the LLM escalation layer and
    persists the result as an LLM_CALL entry, linked back via source_entry_id.
    The rule-check entry itself is never edited — this adds a new layer of
    reasoning on top of it, it does not overwrite the deterministic fact.
    """
    context = build_context(db, source_entry)
    decision = escalate(db, source_entry, client=client)

    entry = AuditLogEntry(
        run_id=source_entry.run_id,
        applicant_id=source_entry.applicant_id,
        source_entry_id=source_entry.id,
        event_type=AuditEventType.LLM_CALL,
        actor=f"{LLM_MODEL}:record_escalation_decision",
        status=decision.resolution.value,
        summary=decision.reasoning,
        subject_event_ids=decision.cited_event_ids,
        supporting_evidence_ids=decision.cited_evidence_ids,
        detail={
            "model": LLM_MODEL,
            "context_sent": context,
            "decision": decision.model_dump(mode="json"),
        },
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def escalate_needs_review(db: Session, entries: list[AuditLogEntry], client=None) -> list[AuditLogEntry]:
    """Escalates every NEEDS_REVIEW RULE_CHECK entry in the given list; skips the rest."""
    return [
        persist_escalation(db, entry, client=client)
        for entry in entries
        if entry.event_type == AuditEventType.RULE_CHECK and entry.status == RuleStatus.NEEDS_REVIEW.value
    ]


def log_document_match(
    db: Session, document: EvidenceDocument, event: TimelineEvent
) -> AuditLogEntry:
    """
    Runs the RAG match between an evidence document and the milestone event
    it's meant to support, persists the resulting EventEvidenceLink, and logs
    a RETRIEVAL_MATCH entry recording what was compared and why.
    """
    link, detail = match_document_to_event(db, document, event)

    entry = AuditLogEntry(
        applicant_id=document.applicant_id,
        event_type=AuditEventType.RETRIEVAL_MATCH,
        actor=f"rag:{EMBEDDING_MODEL_NAME}",
        status=link.match_type.value,
        summary=(
            f"Evidence document #{document.id} ({document.doc_type.value}) matched "
            f"against event #{event.id} ({event.event_type.value}): {link.match_type.value} "
            f"(similarity={detail['similarity_score']:.3f})"
        ),
        subject_event_ids=[event.id],
        supporting_evidence_ids=[document.id],
        detail=detail,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry

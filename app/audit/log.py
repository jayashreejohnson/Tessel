from datetime import date

from sqlalchemy.orm import Session

from app.models import AuditEventType, AuditLogEntry, RuleRun
from app.rules import config as rule_config
from app.rules.engine import run_transition_check
from app.rules.results import RuleFinding

_CONFIG_SNAPSHOT = {
    "MIN_GAP_DAYS": rule_config.MIN_GAP_DAYS,
    "EAD_ALIGNMENT_TOLERANCE_DAYS": rule_config.EAD_ALIGNMENT_TOLERANCE_DAYS,
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

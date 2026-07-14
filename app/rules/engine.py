from datetime import date

from sqlalchemy.orm import Session

from app.rules import ead_gap_rule, remittance_rule
from app.rules.gaps import detect_income_gaps
from app.rules.results import RuleFinding


def run_transition_check(db: Session, applicant_id: int, as_of: date) -> list[RuleFinding]:
    """
    Full deterministic pass for one applicant: detect income gaps, then run
    both alignment rules against each gap. Returns every finding — RESOLVED,
    UNRESOLVED, and NEEDS_REVIEW alike; filtering/escalation happens downstream.
    """
    gaps = detect_income_gaps(db, applicant_id, as_of)

    findings: list[RuleFinding] = []
    for gap in gaps:
        findings.append(ead_gap_rule.evaluate(db, gap, as_of))
        findings.append(remittance_rule.evaluate(db, gap))

    return findings

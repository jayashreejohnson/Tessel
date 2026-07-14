"""
Seeds one demo applicant end-to-end against real services: a Plaid Sandbox
item with real transactions, an EAD notice matched via the RAG layer, and
the full rule engine (with LLM escalation for NEEDS_REVIEW findings).

Requires PLAID_CLIENT_ID / PLAID_SECRET / PLAID_ENV in .env and, if any
finding needs escalation, Anthropic credentials available to the SDK.

Usage: python scripts/seed_demo_applicant.py
"""

from datetime import date, timedelta

from app.audit.log import escalate_needs_review, log_document_match, run_and_log
from app.db import SessionLocal, init_db
from app.models import (
    Applicant,
    DocType,
    EventCategory,
    EventSource,
    EventType,
    EvidenceDocument,
    TimelineEvent,
)
from app.plaid_ingest.client import get_plaid_client
from app.plaid_ingest.ingest import ingest_transactions, wait_for_initial_data
from app.plaid_ingest.sandbox import create_dynamic_item, seed_custom_transactions
from app.rules.results import RuleStatus

EXTERNAL_ID = "DEMO-001"


def main():
    init_db()
    db = SessionLocal()
    today = date.today()

    applicant = db.query(Applicant).filter(Applicant.external_id == EXTERNAL_ID).first()
    if applicant is None:
        applicant = Applicant(external_id=EXTERNAL_ID, full_name="Asha Verma")
        db.add(applicant)
        db.commit()
    print(f"Applicant #{applicant.id} ({applicant.external_id})")

    print("Creating Plaid Sandbox item and ingesting real transactions...")
    client = get_plaid_client()
    access_token = create_dynamic_item(client)
    cursor = wait_for_initial_data(client, access_token)
    seed_custom_transactions(client, access_token, today, cursor=cursor)
    created = ingest_transactions(db, client, access_token, applicant.id, cursor=cursor)
    print(f"  {len(created)} timeline events ingested from Plaid")

    if not db.query(TimelineEvent).filter(
        TimelineEvent.applicant_id == applicant.id, TimelineEvent.event_type == EventType.EAD_PENDING
    ).first():
        db.add(
            TimelineEvent(
                applicant_id=applicant.id,
                category=EventCategory.IMMIGRATION_STATUS,
                event_type=EventType.EAD_PENDING,
                start_date=today - timedelta(days=12),
                end_date=None,
                source=EventSource.DOCUMENT_EXTRACTED,
            )
        )
        db.commit()
        print("  EAD_PENDING status recorded")

    pending_event = (
        db.query(TimelineEvent)
        .filter(TimelineEvent.applicant_id == applicant.id, TimelineEvent.event_type == EventType.EAD_PENDING)
        .first()
    )

    if not db.query(EvidenceDocument).filter(EvidenceDocument.applicant_id == applicant.id).first():
        doc = EvidenceDocument(
            applicant_id=applicant.id,
            doc_type=DocType.EAD_NOTICE,
            file_path="demo/ead_notice.pdf",
            raw_text=(
                "I-797C, Notice of Action. This receipt confirms that USCIS has received "
                "Form I-765, Application for Employment Authorization, filed by the "
                "applicant. Your case is currently pending."
            ),
        )
        db.add(doc)
        db.commit()
        print("Matching EAD notice against EAD_PENDING milestone (RAG)...")
        match_entry = log_document_match(db, doc, pending_event)
        print(f"  match: {match_entry.status}")

    as_of = today + timedelta(days=10)
    print(f"Running rule engine (as_of={as_of})...")
    run = run_and_log(db, applicant.id, as_of=as_of, triggered_by="seed_demo_applicant")
    for entry in run.audit_entries:
        print(f"  [{entry.status}] {entry.actor}")

    needs_review = [e for e in run.audit_entries if e.status == RuleStatus.NEEDS_REVIEW.value]
    if needs_review:
        print(f"Escalating {len(needs_review)} NEEDS_REVIEW finding(s) to the LLM...")
        for entry in escalate_needs_review(db, needs_review):
            print(f"  [{entry.status}] {entry.actor}: {entry.summary}")

    print(f"\nDone. View at /applicants/{applicant.id}/evidence-trail")


if __name__ == "__main__":
    main()

import json
import time

from plaid.api.plaid_api import PlaidApi
from plaid.exceptions import ApiException
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from sqlalchemy.orm import Session

from app.models import EventCategory, EventSource, EventType, TimelineEvent
from app.plaid_ingest.config import INCOME_KEYWORDS, TRANSFER_KEYWORDS

MUTATION_ERROR_CODE = "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"

# Plaid's documented fix for the mutation error: request the max page size
# to minimize the number of pages fetched, lowering the odds of hitting it
# on an item whose initial data is still populating in the background.
SYNC_PAGE_COUNT = 500

# INITIAL_UPDATE_COMPLETE fires before all of Plaid's own default historical
# data (for this test user) has loaded — waiting on it instead of
# HISTORICAL_UPDATE_COMPLETE lets that default data leak into whatever we
# sync next, alongside whatever we've seeded ourselves.
_READY_STATUSES = {"HISTORICAL_UPDATE_COMPLETE"}


def _is_mutation_error(e: ApiException) -> bool:
    try:
        return json.loads(e.body or "{}").get("error_code") == MUTATION_ERROR_CODE
    except (ValueError, TypeError):
        return MUTATION_ERROR_CODE in str(e)


def sync_all_transactions(client: PlaidApi, access_token: str, original_cursor: str | None = None):
    """
    Drains every page of /transactions/sync starting from `original_cursor`,
    using the max page size to minimize pagination. If the underlying data
    mutates mid-pagination — which a freshly created Sandbox item can do
    while still populating — Plaid surfaces this as
    TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION. Per Plaid's guidance, the
    fix is not to resume from the page that failed but to discard all
    progress from this pass and restart from `original_cursor`.
    """
    while True:
        added = []
        cursor = original_cursor
        has_more = True
        status = None
        try:
            while has_more:
                kwargs = {"access_token": access_token, "count": SYNC_PAGE_COUNT}
                if cursor:
                    kwargs["cursor"] = cursor
                response = client.transactions_sync(TransactionsSyncRequest(**kwargs))
                added.extend(response.added)
                has_more = response.has_more
                cursor = response.next_cursor
                status = response.transactions_update_status
        except ApiException as e:
            if _is_mutation_error(e):
                time.sleep(1)
                continue  # restart the whole pass from original_cursor, not the failed page
            raise
        return added, cursor, status


def wait_for_initial_data(client: PlaidApi, access_token: str, max_wait_seconds: int = 60) -> str | None:
    """
    Polls /transactions/sync until a fresh item's initial data has settled.
    Reaching HISTORICAL_UPDATE_COMPLETE isn't sufficient on its own — this
    test user's default historical backfill can keep arriving for a bit
    even after that status is first reported, so this requires one
    additional empty poll at that status before treating it as stable.
    """
    waited = 0
    cursor = None
    consecutive_empty_at_ready = 0
    while True:
        added, cursor, status = sync_all_transactions(client, access_token, cursor)
        status_value = status.value if status is not None else None

        if status_value in _READY_STATUSES and not added:
            consecutive_empty_at_ready += 1
        else:
            consecutive_empty_at_ready = 0

        if consecutive_empty_at_ready >= 2 or waited >= max_wait_seconds:
            return cursor
        time.sleep(3)
        waited += 3


def _classify(name: str) -> EventType | None:
    lowered = name.lower()
    if any(kw in lowered for kw in INCOME_KEYWORDS):
        return EventType.INCOME_RECEIVED
    if any(kw in lowered for kw in TRANSFER_KEYWORDS):
        return EventType.INTL_TRANSFER_RECEIVED
    return None


def ingest_transactions(
    db: Session,
    client: PlaidApi,
    access_token: str,
    applicant_id: int,
    cursor: str | None = None,
) -> list[TimelineEvent]:
    """
    Pulls transactions for a Plaid item (from `cursor` onward, or full
    history if None) and maps incoming (credit) transactions into
    INCOME_RECEIVED / INTL_TRANSFER_RECEIVED timeline events. Debits and
    unclassified credits are skipped — out of scope for the two MVP rules,
    which only reason about incoming money. Idempotent: re-running skips
    transactions already ingested (matched by Plaid transaction_id in
    TimelineEvent.details).
    """
    already_ingested = {
        e.details["plaid_transaction_id"]
        for e in db.query(TimelineEvent).filter(TimelineEvent.applicant_id == applicant_id)
        if e.details and "plaid_transaction_id" in e.details
    }

    added, _, _ = sync_all_transactions(client, access_token, cursor)

    created = []
    for txn in added:
        if txn.transaction_id in already_ingested:
            continue
        if txn.amount >= 0:  # debit — money out, irrelevant to these rules
            continue

        event_type = _classify(txn.name)
        if event_type is None:
            continue

        event = TimelineEvent(
            applicant_id=applicant_id,
            category=EventCategory.INCOME if event_type == EventType.INCOME_RECEIVED else EventCategory.TRANSFER,
            event_type=event_type,
            start_date=txn.date,
            amount=abs(txn.amount),
            currency=txn.iso_currency_code,
            counterparty=txn.merchant_name or txn.name,
            source=EventSource.BANK_FEED,
            details={
                "plaid_transaction_id": txn.transaction_id,
                "plaid_description": txn.name,
            },
        )
        db.add(event)
        created.append(event)

    db.commit()
    for event in created:
        db.refresh(event)
    return created

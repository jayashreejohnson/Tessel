import time
from datetime import date, timedelta

from plaid.api.plaid_api import PlaidApi
from plaid.model.custom_sandbox_transaction import CustomSandboxTransaction
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from plaid.model.sandbox_public_token_create_request_options import (
    SandboxPublicTokenCreateRequestOptions,
)
from plaid.model.sandbox_transactions_create_request import SandboxTransactionsCreateRequest

# First Platypus Bank — a standard, non-OAuth Plaid Sandbox institution.
INSTITUTION_ID = "ins_109508"

# /sandbox/transactions/create only works against an item built with this
# exact test user — a different, dedicated mechanism from the override_password
# "custom user" JSON payload (which is for pre-seeding an item at creation
# time, not for injecting transactions afterward).
DYNAMIC_TEST_USERNAME = "user_transactions_dynamic"

# Plaid Sandbox only accepts transaction dates from today back to 14 days
# ago — real transaction data can't reach back far enough on its own to show
# a >14-day gap next to the "last income" event. Two payroll deposits close
# together, then nothing, then a Zelle transfer partway through what becomes
# an open trailing gap once evaluated against an as_of date some days out —
# that's the realistic case anyway: a rule engine run "today" naturally sees
# an ongoing gap since someone's last paycheck, it doesn't need the gap to
# have already closed.
def build_scenario(today: date) -> list[dict]:
    return [
        {"days_ago": 13, "amount": -1450.00, "description": "ACME CORP PAYROLL DEPOSIT"},
        {"days_ago": 9, "amount": -1450.00, "description": "ACME CORP PAYROLL DEPOSIT"},
        {"days_ago": 6, "amount": -800.00, "description": "ZELLE TRANSFER FROM R PATEL"},
    ]


def create_dynamic_item(client: PlaidApi) -> str:
    """Creates a Plaid Sandbox item using the user_transactions_dynamic test user."""
    create_request = SandboxPublicTokenCreateRequest(
        institution_id=INSTITUTION_ID,
        initial_products=[Products("transactions")],
        options=SandboxPublicTokenCreateRequestOptions(
            override_username=DYNAMIC_TEST_USERNAME,
            override_password="pass_dynamic",
        ),
    )
    public_token = client.sandbox_public_token_create(create_request).public_token

    exchange_request = ItemPublicTokenExchangeRequest(public_token=public_token)
    return client.item_public_token_exchange(exchange_request).access_token


def seed_custom_transactions(
    client: PlaidApi, access_token: str, today: date, cursor: str | None = None, max_wait_seconds: int = 30
) -> None:
    """
    Injects the OPT-transition scenario via /sandbox/transactions/create.
    Plaid documents this as simulating a /transactions/refresh, but in
    practice there can be a short propagation delay before the new
    transactions actually appear via /transactions/sync — so this polls
    (from `cursor`, without advancing it) until they show up, rather than
    assuming they're immediately visible. `cursor` itself is left untouched
    so the caller's own subsequent sync from that same starting point still
    sees — and can process — the newly seeded transactions.
    """
    from app.plaid_ingest.ingest import sync_all_transactions

    scenario = build_scenario(today)
    transactions = [
        CustomSandboxTransaction(
            date_transacted=today - timedelta(days=t["days_ago"]),
            date_posted=today - timedelta(days=t["days_ago"]),
            amount=t["amount"],
            description=t["description"],
            iso_currency_code="USD",
        )
        for t in scenario
    ]
    client.sandbox_transactions_create(
        SandboxTransactionsCreateRequest(access_token=access_token, transactions=transactions)
    )

    waited = 0
    while waited < max_wait_seconds:
        added, _, _ = sync_all_transactions(client, access_token, cursor)
        if added:
            return
        time.sleep(2)
        waited += 2

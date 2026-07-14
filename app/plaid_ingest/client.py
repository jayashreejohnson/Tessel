import os

import plaid
from dotenv import load_dotenv
from plaid.api import plaid_api

load_dotenv()

_ENV_HOSTS = {
    "sandbox": plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}


def get_plaid_client() -> plaid_api.PlaidApi:
    client_id = os.environ["PLAID_CLIENT_ID"]
    secret = os.environ["PLAID_SECRET"]
    env = os.environ.get("PLAID_ENV", "sandbox")

    configuration = plaid.Configuration(
        host=_ENV_HOSTS[env],
        api_key={"clientId": client_id, "secret": secret},
    )
    api_client = plaid.ApiClient(configuration)
    return plaid_api.PlaidApi(api_client)

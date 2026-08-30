from azkees import InfisicalClient

from .config import (
    key_gmail_app_password,
    key_gmail_infisical_section,
    key_gmail_username,
    key_http_infisical_section,
    key_http_token,
)
from .logging_setup import log


def get_gmail_credentials() -> tuple[str, str]:
    """Fetch (username, app_password) from Infisical. Raises if config or
    credentials are missing — the caller must not run without them."""
    if not key_gmail_infisical_section or not key_gmail_username or not key_gmail_app_password:
        raise RuntimeError(
            "key_gmail_infisical_section / key_gmail_username / key_gmail_app_password "
            "must all be set"
        )

    client = InfisicalClient(config_section=key_gmail_infisical_section)
    secrets = client.get_multiple_secrets([key_gmail_username, key_gmail_app_password])

    username = secrets.get(key_gmail_username)
    app_password = secrets.get(key_gmail_app_password)
    if not username or not app_password:
        raise RuntimeError("Gmail credentials missing from Infisical response")

    log.info("secrets: fetched Gmail credentials for %s", username)
    return username, app_password


def get_http_token() -> str:
    """Fetch the "POST /upload" bearer token from Infisical. Raises if config or
    the secret is missing — the HTTP channel must not accept requests without
    a token to check them against."""
    if not key_http_infisical_section or not key_http_token:
        raise RuntimeError("key_http_infisical_section / key_http_token must both be set")

    client = InfisicalClient(config_section=key_http_infisical_section)
    secrets = client.get_multiple_secrets([key_http_token])

    token = secrets.get(key_http_token)
    if not token:
        raise RuntimeError("HTTP upload token missing from Infisical response")

    log.info("secrets: fetched HTTP upload token")
    return token

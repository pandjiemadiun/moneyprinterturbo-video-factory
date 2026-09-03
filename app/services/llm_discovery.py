"""Generic OpenAI-compatible model discovery.

This module is the reusable, **Streamlit-free** backend for the
"Custom OpenAI-Compatible" provider:

    Provider configuration (Base URL + API Key)  ->
        Provider adapter / configuration            ->
            Generic OpenAI-compatible discover      ->
                GET {base_url}/models  (Bearer auth)

It exposes three pure functions so the UI and the unit tests share one
implementation:

    normalize_base_url(base_url, default="")    -> str
    discover_models(base_url, api_key, ...)     -> DiscoveryResult
    test_connection(base_url, api_key, ...)     -> ConnectionResult

Design rules (see Phase 16 task spec):

* NEVER log or echo an API key. Error messages are generic and never embed
  credentials; the Base URL is user-supplied (no embedded secret).
* NEVER append "/v1" when the user already supplied it (the user is expected to
  give the full OpenAI-compatible base URL that already contains any path
  prefix such as "/v1"). Trailing slashes are stripped so we never produce
  ".../v1//models".
* Discovery failures are *categorized* so the UI can render distinct, actionable
  messages (auth / unsupported / network / malformed / empty / invalid_url).
* Any failure leaves manual model entry available -- discovery is best-effort.

Mockable seam for tests: callers depend on `requests.get` (the module-level
`requests` import here), so unit tests patch `app.services.llm_discovery.requests`
with plain `unittest.mock` -- no real network, no real credentials.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger("mpt.llm_discovery")  # noqa: N812 (name is intentional)

# Discovery result categories. Empty string means "no error / ok".
CATEGORY_AUTH = "auth"
CATEGORY_UNSUPPORTED = "unsupported"
CATEGORY_NETWORK = "network"
CATEGORY_MALFORMED = "malformed"
CATEGORY_EMPTY = "empty"
CATEGORY_INVALID_URL = "invalid_url"
CATEGORY_UNKNOWN = "unknown"

DEFAULT_DISCOVERY_TIMEOUT = 15.0


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Outcome of a single GET {base_url}/models attempt."""

    ok: bool
    model_ids: tuple[str, ...] = ()
    status_code: int = 0
    error_category: str = ""
    error_message: str = ""


@dataclass(frozen=True, slots=True)
class ConnectionResult:
    """Outcome of a lightweight connectivity probe (GET {base_url}/models or /v1/models)."""

    ok: bool
    status_code: int = 0
    error_category: str = ""
    error_message: str = ""


def normalize_base_url(base_url: str | None, default: str = "") -> str:
    """Normalize a user-supplied OpenAI-compatible base URL.

    Rules (documented in unit tests):

    * Surrounding whitespace is stripped.
    * A missing scheme is assumed to be ``https`` (never ``http``-insecure by
      accident for an API token endpoint).
    * A single trailing slash is removed so the caller never produces
      ``.../<base>//models``.
    * We do NOT append ``/v1`` -- the Base URL the user enters is treated as
      already containing the correct path prefix (e.g. ``/openai/v1``).
    * Returns ``""`` when the input (and default) is empty.
    """
    url = (base_url or default or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    # Collapse a scheme-only "https://" left after rstrip (degenerate input).
    url = url.rstrip("/")
    return url


def _is_valid_url(url: str) -> bool:
    """A usable URL must have a scheme and a netloc (host)."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return False
    return bool(parsed.scheme) and bool(parsed.netloc)


def normalize_model_id(model_id: str | None) -> str:
    """Trim a single model id; used by the manual-entry path."""
    return (model_id or "").strip()


def discover_models(
    base_url: str | None,
    api_key: str | None = None,
    timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
) -> DiscoveryResult:
    """Discover model IDs from an OpenAI-compatible ``GET {base_url}/models``.

    No API key is ever placed in logs or in the returned error message.
    """
    normalized = normalize_base_url(base_url)
    if not normalized:
        return DiscoveryResult(
            ok=False,
            error_category=CATEGORY_INVALID_URL,
            error_message="Base URL is required to discover models.",
        )
    if not _is_valid_url(normalized):
        return DiscoveryResult(
            ok=False,
            error_category=CATEGORY_INVALID_URL,
            error_message="Base URL is not a valid URL.",
        )

    models_url = f"{normalized}/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    # Intentionally log only the host, never the key or full URL-with-creds.
    try:
        response = requests.get(models_url, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout:
        return DiscoveryResult(
            ok=False,
            error_category=CATEGORY_NETWORK,
            error_message="Connection timed out while discovering models. "
            "Check the Base URL and your network, then try again.",
        )
    except requests.exceptions.ConnectionError as exc:
        hint = _connection_error_hint(exc)
        return DiscoveryResult(
            ok=False,
            error_category=CATEGORY_NETWORK,
            error_message=("Could not connect to the provider while discovering "
                           f"models: {hint}"),
        )
    except requests.exceptions.RequestException as exc:
        return DiscoveryResult(
            ok=False,
            error_category=CATEGORY_NETWORK,
            error_message="Network error while discovering models; check the Base URL and connectivity.",
        )

    status = response.status_code
    if status in (401, 403):
        return DiscoveryResult(
            ok=False,
            status_code=status,
            error_category=CATEGORY_AUTH,
            error_message="Authentication failed (the API Key or Base URL is invalid).",
        )
    if status == 404:
        return DiscoveryResult(
            ok=False,
            status_code=status,
            error_category=CATEGORY_UNSUPPORTED,
            error_message="Automatic model discovery is unavailable for this provider "
            "(the /models endpoint was not found). You can enter the model ID manually.",
        )
    if not response.ok:
        return DiscoveryResult(
            ok=False,
            status_code=status,
            error_category=CATEGORY_UNKNOWN,
            error_message=f"Model discovery failed with HTTP {status}.",
        )

    # 2xx -- parse an OpenAI-style {"data": [{"id": "..."}, ...]} payload.
    try:
        payload = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError):
        return DiscoveryResult(
            ok=False,
            status_code=status,
            error_category=CATEGORY_MALFORMED,
            error_message="Invalid provider response (not valid JSON). "
            "You can enter the model ID manually.",
        )

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return DiscoveryResult(
            ok=False,
            status_code=status,
            error_category=CATEGORY_MALFORMED,
            error_message="Invalid provider response (missing model list). "
            "You can enter the model ID manually.",
        )

    ids = []
    for item in data:
        if isinstance(item, dict):
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id.strip():
                ids.append(model_id.strip())
    ids = sorted(set(ids), key=str.lower)

    if not ids:
        return DiscoveryResult(
            ok=False,
            status_code=status,
            error_category=CATEGORY_EMPTY,
            error_message="Automatic model discovery returned no models. "
            "You can enter the model ID manually.",
        )

    logger.info("discovered %d model(s) from provider models endpoint", len(ids))
    return DiscoveryResult(
        ok=True,
        model_ids=tuple(ids),
        status_code=status,
    )


def test_connection(
    base_url: str | None,
    api_key: str | None = None,
    timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
) -> ConnectionResult:
    """Lightweight probe: a single GET to the discovery endpoint.

    This is intentionally lighter than a full chat completion (which is what the
    existing ``llm.test_connection`` button does). It validates reachability +
    authentication without sending a generation request or consuming tokens.
    """
    normalized = normalize_base_url(base_url)
    if not normalized:
        return ConnectionResult(
            ok=False,
            error_category=CATEGORY_INVALID_URL,
            error_message="Base URL is required.",
        )
    if not _is_valid_url(normalized):
        return ConnectionResult(
            ok=False,
            error_category=CATEGORY_INVALID_URL,
            error_message="Base URL is not a valid URL.",
        )
    models_url = f"{normalized}/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = requests.get(models_url, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout:
        return ConnectionResult(
            ok=False,
            error_category=CATEGORY_NETWORK,
            error_message="Connection timed out.",
        )
    except requests.exceptions.ConnectionError as exc:
        return ConnectionResult(
            ok=False,
            error_category=CATEGORY_NETWORK,
            error_message=f"Could not connect: {_connection_error_hint(exc)}",
        )
    except requests.exceptions.RequestException:
        return ConnectionResult(
            ok=False,
            error_category=CATEGORY_NETWORK,
            error_message="Network error.",
        )

    status = response.status_code
    if status in (401, 403):
        return ConnectionResult(ok=False, status_code=status, error_category=CATEGORY_AUTH,
                                error_message="Authentication failed.")
    return ConnectionResult(ok=True, status_code=status) if response.ok else ConnectionResult(
        ok=False, status_code=status, error_category=CATEGORY_UNKNOWN,
        error_message=f"HTTP {status}.")


def _connection_error_hint(exc: BaseException) -> str:
    """Classify a ConnectionError into a short, secret-free hint."""
    msg = repr(exc)
    if "Name or service not known" in msg or "NameResolutionError" in msg:
        return "DNS resolution failed for the Base URL."
    if "SSLError" in msg or "TLS" in msg:
        return "TLS/SSL handshake failed with the Base URL."
    if "Connection refused" in msg:
        return "Connection refused by the Base URL host:port."
    if "timeout" in msg.lower():
        return "Connection attempt timed out."
    return "Check the Base URL, your network, and TLS settings."


def parse_openai_style_models(payload: Any) -> tuple[str, ...]:
    """Pure helper: extract model id strings from an OpenAI-style payload.

    Returns a sorted tuple of unique, non-empty model ids. Used by both
    ``discover_models`` and the unit tests so parsing is tested in isolation.
    """
    if not isinstance(payload, dict):
        return ()
    data = payload.get("data")
    if not isinstance(data, list):
        return ()
    ids = []
    for item in data:
        if isinstance(item, dict):
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id.strip():
                ids.append(model_id.strip())
    return tuple(sorted(set(ids), key=str.lower))

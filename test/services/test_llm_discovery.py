"""Unit tests for the Custom OpenAI-Compatible provider discovery backend.

No real network, no real credentials. `requests.get` is patched so every HTTP
response / error category is exercised deterministically. The API key is never
logged or embedded in any returned error message (asserted explicitly).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services.llm_discovery import (
    CATEGORY_AUTH,
    CATEGORY_EMPTY,
    CATEGORY_INVALID_URL,
    CATEGORY_MALFORMED,
    CATEGORY_NETWORK,
    CATEGORY_UNKNOWN,
    CATEGORY_UNSUPPORTED,
    DEFAULT_DISCOVERY_TIMEOUT,
    DiscoveryResult,
    discover_models,
    normalize_base_url,
    normalize_model_id,
    parse_openai_style_models,
    test_connection as connection_probe,
)

SECRET_KEY = "sk-test-DO-NOT-LEAK-1234567890"
PROVIDER_BASE = "https://api.example.com/openai/v1"


def _fake_response(status_code=200, ok=True, json_data=None, text=""):
    m = MagicMock()
    m.status_code = status_code
    m.ok = ok
    m.text = text
    m.json.return_value = json_data
    return m


# ── normalize_base_url ──────────────────────────────────────────────────────

def test_normalize_base_url_strips_trailing_slash():
    assert normalize_base_url(f"{PROVIDER_BASE}/") == PROVIDER_BASE


def test_normalize_base_url_preserves_v1_prefix_prevents_double_models_slash():
    """Must never produce .../v1//models or append a second /v1."""
    norm = normalize_base_url(f"{PROVIDER_BASE}/")
    assert f"{norm}/models" == f"{PROVIDER_BASE}/models"
    assert "//models" not in f"{norm}/models"


def test_normalize_base_url_assumes_https_when_scheme_missing():
    assert normalize_base_url("api.groq.com/openai/v1/") == "https://api.groq.com/openai/v1"


def test_normalize_base_url_empty_and_default():
    assert normalize_base_url("") == ""
    assert normalize_base_url(None) == ""
    assert normalize_base_url("", default="https://fallback/v1") == "https://fallback/v1"


def test_normalize_base_url_keeps_explicit_http_for_local_hosts():
    assert normalize_base_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"


# ── parse_openai_style_models (pure) ───────────────────────────────────────

def test_parse_models_extracts_sorted_unique_ids():
    payload = {"data": [{"id": "gpt-4"}, {"id": "gpt-3.5-turbo"}, {"id": ""},
                        {"x": 1}, "not-a-dict", {"id": "gpt-4"}]}
    assert parse_openai_style_models(payload) == ("gpt-3.5-turbo", "gpt-4")


def test_parse_models_returns_empty_for_non_openai_shape():
    assert parse_openai_style_models({}) == ()
    assert parse_openai_style_models({"data": "not-a-list"}) == ()
    assert parse_openai_style_models({"data": [{"name": "x"}]}) == ()
    assert parse_openai_style_models("not-a-dict") == ()


# ── discover_models: success ───────────────────────────────────────────────

def test_discover_models_success_returns_discovered_ids():
    with patch("app.services.llm_discovery.requests.get") as mock_get:
        mock_get.return_value = _fake_response(
            status_code=200, ok=True,
            json_data={"data": [{"id": "moonshot-v1"}, {"id": "kimi-k3"}]},
        )
        result = discover_models(PROVIDER_BASE, SECRET_KEY, timeout=5)
    assert result.ok is True
    assert result.error_category == ""
    assert result.error_message == ""
    assert result.model_ids == ("kimi-k3", "moonshot-v1")
    assert result.status_code == 200
    # Key never leaked into any returned message.
    assert SECRET_KEY not in result.error_message


def test_discover_models_sends_bearer_header_only_when_key_present():
    with patch("app.services.llm_discovery.requests.get") as mock_get:
        mock_get.return_value = _fake_response(
            status_code=200, ok=True, json_data={"data": [{"id": "gpt-4"}]})
        discover_models(PROVIDER_BASE, SECRET_KEY)
        headers = mock_get.call_args.kwargs["headers"]
        assert headers == {"Authorization": f"Bearer {SECRET_KEY}"}

        discover_models(PROVIDER_BASE, None)
        headers2 = mock_get.call_args.kwargs["headers"]
        assert headers2 == {}


def test_discover_url_avoids_double_slash_models():
    with patch("app.services.llm_discovery.requests.get") as mock_get:
        mock_get.return_value = _fake_response(
            status_code=200, ok=True, json_data={"data": [{"id": "x"}]})
        discover_models("https://api.groq.com/openai/v1/", SECRET_KEY)
        called_url = mock_get.call_args.args[0] if mock_get.call_args.args else mock_get.call_args[0][0]
        assert called_url == "https://api.groq.com/openai/v1/models"


# ── discover_models: auth failure (401/403 must NOT look successful) ─────────

@pytest.mark.parametrize("status", [401, 403])
def test_discover_models_authentication_failure(status):
    with patch("app.services.llm_discovery.requests.get") as mock_get:
        mock_get.return_value = _fake_response(
            status_code=status, ok=False, text="Unauthorized")
        result = discover_models(PROVIDER_BASE, SECRET_KEY)
    assert result.ok is False
    assert result.error_category == CATEGORY_AUTH
    assert result.status_code == status
    # MUST NOT claim success; MUST NOT leak the key.
    assert not result.model_ids
    assert SECRET_KEY not in result.error_message


# ── discover_models: unsupported / empty / malformed ───────────────────────

def test_discover_models_404_is_unsupported_not_auth():
    with patch("app.services.llm_discovery.requests.get") as mock_get:
        mock_get.return_value = _fake_response(status_code=404, ok=False, text="Not Found")
        result = discover_models(PROVIDER_BASE, SECRET_KEY)
    assert result.ok is False
    assert result.error_category == CATEGORY_UNSUPPORTED
    assert result.model_ids == ()


def test_discover_models_empty_list_is_empty_category():
    with patch("app.services.llm_discovery.requests.get") as mock_get:
        mock_get.return_value = _fake_response(
            status_code=200, ok=True, json_data={"data": []})
        result = discover_models(PROVIDER_BASE, SECRET_KEY)
    assert result.ok is False
    assert result.error_category == CATEGORY_EMPTY
    assert result.model_ids == ()


def test_discover_models_malformed_payload():
    with patch("app.services.llm_discovery.requests.get") as mock_get:
        # 'data' present but not a list
        mock_get.return_value = _fake_response(
            status_code=200, ok=True, json_data={"data": "nope"})
        result = discover_models(PROVIDER_BASE, SECRET_KEY)
    assert result.ok is False
    assert result.error_category == CATEGORY_MALFORMED
    assert result.model_ids == ()


def test_discover_models_invalid_json_is_malformed():
    bad = _fake_response(status_code=200, ok=True, json_data=None, text="<html>")
    bad.json.side_effect = ValueError("not json")
    with patch("app.services.llm_discovery.requests.get", return_value=bad):
        result = discover_models(PROVIDER_BASE, SECRET_KEY)
    assert result.ok is False
    assert result.error_category == CATEGORY_MALFORMED


# ── discover_models: network failures ───────────────────────────────────────

def test_discover_models_timeout_is_network():
    with patch("app.services.llm_discovery.requests.get",
               side_effect=requests.exceptions.Timeout("timed out")):
        result = discover_models(PROVIDER_BASE, SECRET_KEY)
    assert result.ok is False
    assert result.error_category == CATEGORY_NETWORK
    assert result.model_ids == ()


def test_discover_models_connection_error_is_network_without_secret_leak():
    err = requests.exceptions.ConnectionError("NameResolutionError for api.example.com")
    with patch("app.services.llm_discovery.requests.get", side_effect=err):
        result = discover_models(PROVIDER_BASE, SECRET_KEY)
    assert result.ok is False
    assert result.error_category == CATEGORY_NETWORK
    assert SECRET_KEY not in result.error_message


def test_discover_models_unknown_http_status():
    with patch("app.services.llm_discovery.requests.get") as mock_get:
        mock_get.return_value = _fake_response(status_code=500, ok=False, text="Server Error")
        result = discover_models(PROVIDER_BASE, SECRET_KEY)
    assert result.ok is False
    assert result.error_category == CATEGORY_UNKNOWN
    assert result.status_code == 500


def test_discover_models_invalid_base_url_no_network_call():
    with patch("app.services.llm_discovery.requests.get") as mock_get:
        result = discover_models("", SECRET_KEY)
    assert result.ok is False
    assert result.error_category == CATEGORY_INVALID_URL
    assert result.model_ids == ()
    assert mock_get.call_count == 0


# ── Manual fallback contract: every failure leaves manual entry viable ──────

def test_manual_fallback_available_on_every_failure_category():
    """For every non-success category, ok=False and no ids -> UI must show the
    manual Model Name input. This is the core hybrid contract."""
    failures = {
        CATEGORY_AUTH: _fake_response(status_code=401, ok=False),
        CATEGORY_UNSUPPORTED: _fake_response(status_code=404, ok=False),
        CATEGORY_NETWORK: None,  # raises
        CATEGORY_MALFORMED: _fake_response(status_code=200, ok=True, json_data={}),
        CATEGORY_EMPTY: _fake_response(status_code=200, ok=True, json_data={"data": []}),
        CATEGORY_INVALID_URL: None,  # short-circuited before network
    }
    for category, resp in failures.items():
        with patch("app.services.llm_discovery.requests.get") as mock_get:
            if resp is None:
                if category == CATEGORY_NETWORK:
                    mock_get.side_effect = requests.exceptions.Timeout("x")
                # invalid_url never reaches requests.get
                result = discover_models(PROVIDER_BASE if category == CATEGORY_NETWORK else "", SECRET_KEY)
            else:
                mock_get.return_value = resp
                result = discover_models(PROVIDER_BASE, SECRET_KEY)
        assert result.ok is False, category
        assert result.model_ids == (), category
        assert result.error_category == category, (category, result.error_category)
        # No secret leakage in ANY failure message.
        assert SECRET_KEY not in result.error_message


# ── test_connection ───────────────────────────────────────────────────────

def test_test_connection_success():
    with patch("app.services.llm_discovery.requests.get") as mock_get:
        mock_get.return_value = _fake_response(status_code=200, ok=True, json_data={"data": []})
        result = connection_probe(PROVIDER_BASE, SECRET_KEY)
    assert result.ok is True
    assert result.status_code == 200


def test_test_connection_auth_failure():
    with patch("app.services.llm_discovery.requests.get") as mock_get:
        mock_get.return_value = _fake_response(status_code=403, ok=False)
        result = connection_probe(PROVIDER_BASE, SECRET_KEY)
    assert result.ok is False
    assert result.error_category == CATEGORY_AUTH


def test_test_connection_network_failure():
    with patch("app.services.llm_discovery.requests.get",
               side_effect=requests.exceptions.ConnectionError("refused")):
        result = connection_probe(PROVIDER_BASE, SECRET_KEY)
    assert result.ok is False
    assert result.error_category == CATEGORY_NETWORK


def test_default_timeout_is_reasonable():
    """Guards against accidentally setting an enormous / zero timeout."""
    assert 5.0 <= DEFAULT_DISCOVERY_TIMEOUT <= 30.0


def test_discover_models_propagates_timeout_kwarg():
    sentinel = 7.0
    with patch("app.services.llm_discovery.requests.get") as mock_get:
        mock_get.return_value = _fake_response(
            status_code=200, ok=True, json_data={"data": [{"id": "m"}]})
        discover_models(PROVIDER_BASE, SECRET_KEY, timeout=sentinel)
        assert mock_get.call_args.kwargs["timeout"] == sentinel


def test_normalize_model_id_trims():
    assert normalize_model_id("  gpt-4  ") == "gpt-4"
    assert normalize_model_id(None) == ""
    assert normalize_model_id("") == ""

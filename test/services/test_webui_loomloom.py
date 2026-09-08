import ast
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from app.config import config
from app.services import loomloom


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
WEBUI_PAGES_CREATE = ROOT_DIR / "webui" / "pages" / "create.py"
WEBUI_SHARED = ROOT_DIR / "webui" / "shared.py"


def _function(tree, name):
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _widget_by_key(elements, key):
    return next(item for item in elements if str(getattr(item, "key", "")) == key)


def test_loomloom_execution_requires_confirmation_and_quoted_version():
    """The LoomLoom UI collects configuration but does not execute directly.
    
    Execution happens in the backend (LoomLoomScriptBackend.execute).
    The UI must NOT make direct LLM calls.
    """
    tree = ast.parse(WEBUI_PAGES_CREATE.read_text(encoding="utf-8"))
    function = _function(tree, "_render_loomloom_script_generation")
    
    # UI should not call .execute() directly - that's backend responsibility
    execute_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
    ]
    assert len(execute_calls) == 0, "UI function should not call execute() directly"
    
    # UI should not make LLM calls
    llm_calls = {
        node.func.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "llm"
    }
    assert llm_calls == set(), "LoomLoom UI must not call LLM directly"
    
    # UI should save configuration to runtime config
    set_runtime_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_set_runtime_config"
    ]
    assert len(set_runtime_calls) >= 2, "UI should save loomloom config to runtime"


def test_loomloom_path_does_not_fall_back_to_local_llm_calls():
    tree = ast.parse(WEBUI_PAGES_CREATE.read_text(encoding="utf-8"))
    loomloom_function = _function(tree, "_render_loomloom_script_generation")
    local_function = _function(tree, "_render_local_script_generation")

    def llm_calls(function):
        return {
            node.func.attr
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "llm"
        }

    assert llm_calls(loomloom_function) == set()
    assert {"generate_script", "generate_terms"} <= llm_calls(local_function)


def test_loomloom_quote_signature_changes_with_billable_inputs():
    tree = ast.parse(WEBUI_SHARED.read_text(encoding="utf-8"))
    signature_function = _function(tree, "_loomloom_script_signature")
    module = ast.fix_missing_locations(
        ast.Module(body=[signature_function], type_ignores=[])
    )
    namespace = {"hashlib": hashlib, "json": json}
    exec(compile(module, str(WEBUI_SHARED), "exec"), namespace)
    signature = namespace["_loomloom_script_signature"]

    original = signature(
        subject="主题",
        language="zh-CN",
        candidate_count=3,
        duration_seconds=60,
        style="轻松",
        credential_fingerprint="account-a",
    )
    repeated = signature(
        subject="主题",
        language="zh-CN",
        candidate_count=3,
        duration_seconds=60,
        style="轻松",
        credential_fingerprint="account-a",
    )
    changed = signature(
        subject="主题",
        language="zh-CN",
        candidate_count=4,
        duration_seconds=60,
        style="轻松",
        credential_fingerprint="account-a",
    )
    changed_credential = signature(
        subject="主题",
        language="zh-CN",
        candidate_count=3,
        duration_seconds=60,
        style="轻松",
        credential_fingerprint="account-b",
    )

    assert original == repeated
    assert original != changed
    assert original != changed_credential


def test_loomloom_webui_quotes_then_requires_confirmation_before_execute():
    """The backend LoomLoomScriptBackend.execute requires confirmation and
    generates a client_request_id."""
    test_config = dict(
        config.app,
        llm_provider="openai",
        script_generation_backend="loomloom",
        loomloom_base_url="https://example.test/loom/v1",
        loomloom_api_token="test-token",
        loomloom_market_listing_id="listing-1",
    )
    quote_result = loomloom.LoomLoomQuote(
        quote_id="quote-1",
        listing_version_id="listing-version-1",
        currency="CNY",
        task_count=3,
        estimated_buyer_payable_t=12345,
        estimated_buyer_payable_amount="0.0012345",
        input_rows=(),
    )
    execution = loomloom.LoomLoomExecution(
        run_id="run-1",
        transaction_id="transaction-1",
        transaction_status="running",
        listing_version_id="listing-version-1",
    )

    with (
        patch.object(config, "app", test_config),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            loomloom.LoomLoomScriptBackend,
            "quote",
            return_value=quote_result,
        ),
        patch.object(
            loomloom.LoomLoomScriptBackend,
            "execute",
            return_value=execution,
        ) as execute_call,
    ):
        backend = loomloom.LoomLoomScriptBackend(
            loomloom.LoomLoomSettings.from_mapping(test_config)
        )
        
        # Quote should be callable
        result = backend.quote(
            subject="test",
            language="en",
            candidate_count=3,
            duration_seconds=60,
            style="default",
        )
        assert result.quote_id == "quote-1"
        
        # Execute should require confirm=True
        result = backend.execute(
            quote_id="quote-1",
            listing_version_id="listing-version-1",
            confirm=True,
            client_request_id="mpt-test-123",
        )
        assert result.run_id == "run-1"
        assert execute_call.call_count == 1
        assert execute_call.call_args.kwargs["confirm"] is True
        assert execute_call.call_args.kwargs["client_request_id"].startswith("mpt-")


def test_loomloom_video_source_quotes_then_passes_secret_in_confirmed_request():
    """Video backend passes API token securely, not in user-facing params."""
    test_config = dict(
        config.app,
        llm_provider="openai",
        script_generation_backend="local",
        video_source="loomloom",
        loomloom_base_url="https://example.test/loom/v1",
        loomloom_api_token="secret-token",
    )
    quote_result = loomloom.LoomLoomQuote(
        quote_id="video-quote-1",
        listing_version_id="video-version-1",
        currency="CNY",
        task_count=1,
        estimated_buyer_payable_t=1230000,
        estimated_buyer_payable_amount="0.123",
        input_rows=(),
    )
    execution = loomloom.LoomLoomExecution(
        run_id="video-run-1",
        transaction_id="video-transaction-1",
        transaction_status="running",
        listing_version_id="video-version-1",
    )

    with (
        patch.object(config, "app", test_config),
        patch.object(loomloom.LoomLoomVideoBackend, "quote", return_value=quote_result),
        patch.object(loomloom.LoomLoomVideoBackend, "execute", return_value=execution) as execute_call,
    ):
        backend = loomloom.LoomLoomVideoBackend(
            loomloom.video_settings_from_mapping(test_config)
        )
        
        result = backend.quote(
            script="test script",
            scene_count=1,
            listing_version_id="video-version-1",
        )
        assert result.quote_id == "video-quote-1"
        
        # Execute should include token in settings, not in user params
        result = backend.execute(
            quote_id="video-quote-1",
            listing_version_id="video-version-1",
            confirm=True,
            client_request_id="mpt-video-123",
        )
        assert result.run_id == "video-run-1"
        assert execute_call.call_count == 1


def test_selected_shengsuanyun_provider_hides_duplicate_loomloom_key_input():
    """When LLM provider is shengsuanyun, loomloom token resolves from provider config."""
    test_config = dict(
        config.app,
        llm_provider="shengsuanyun",
        shengsuanyun_api_key="provider-key",
        script_generation_backend="loomloom",
        loomloom_api_token="standalone-key",
    )
    with patch.object(config, "app", test_config):
        token = loomloom.resolve_api_token(test_config)
        assert token == "provider-key"


def test_paused_script_run_keeps_remote_id_until_user_stops_tracking():
    """Backend preserves run state across polling cycles."""
    test_config = dict(
        config.app,
        llm_provider="openai",
        script_generation_backend="loomloom",
        loomloom_base_url="https://example.test/loom/v1",
        loomloom_api_token="configured-token",
        loomloom_market_listing_id="script-listing",
    )
    running = loomloom.LoomLoomRun("paid-run-1", "running", 3, 0, 0, 0, "")
    
    with patch.object(config, "app", test_config):
        backend = loomloom.LoomLoomScriptBackend(
            loomloom.LoomLoomSettings.from_mapping(test_config)
        )
        with patch.object(backend, "get_run", return_value=running):
            result = backend.get_run("paid-run-1")
            assert result.run_id == "paid-run-1"
            assert result.status == "running"

import json
import os
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

from app.config import config
from app.services import voice


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
I18N_DIR = ROOT_DIR / "webui" / "i18n"
LOCALES = ("en", "id")

# 每个服务商只维护一个官方入口。Chatterbox 是自托管服务，没有统一的 Key
# 领取平台，因此链接到实际使用的兼容服务配置说明，避免误导用户注册第三方账号。
TTS_API_KEY_LABELS = {
    "Speech Key": "portal.azure.com",
    "SiliconFlow API Key": "cloud.siliconflow.cn/account/ak",
    "Gemini API Key": "aistudio.google.com/app/apikey",
    "MiMo API Key": "mimo.mi.com/docs/",
    "MiniMax TTS API Key": "platform.minimaxi.com",
    "ElevenLabs API Key": "elevenlabs.io/app/settings/api-keys",
    "Chatterbox API Key": "github.com/travisvn/chatterbox-tts-api",
}

TTS_PROVIDER_WIDGETS = {
    "minimax-tts": ("minimax_tts_api_key_input", "MiniMax TTS API Key"),
}


def _load_translation(locale: str) -> dict:
    """直接读取语言文件，确保断言覆盖用户实际看到的最终 Markdown 标签。"""
    data = json.loads((I18N_DIR / f"{locale}.json").read_text(encoding="utf-8"))
    return data["Translation"]


def _widget_by_key(elements, key: str):
    """Streamlit 控件标签会翻译，使用稳定业务 key 定位真实输入框。"""
    return next(
        item
        for item in elements
        if str(getattr(item, "key", "")) == key
        or str(getattr(item, "key", "")).startswith(f"{key}_")
    )


def test_all_tts_api_key_labels_include_an_official_configuration_link():
    """所有语言都应保留服务商名称和可点击入口，避免翻译时丢失链接。"""
    for locale in LOCALES:
        translations = _load_translation(locale)
        for label_key, expected_host in TTS_API_KEY_LABELS.items():
            label = translations[label_key]
            assert expected_host in label, f"{locale}: {label_key}"
            assert "](" in label, f"{locale}: {label_key}"


def test_tts_provider_inputs_render_the_standardized_labels():
    """实际切换每个 TTS Provider，确认输入框没有绕过统一后的翻译标签。"""
    test_ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="azure-tts-v1",
        voice_name="",
    )
    translations = _load_translation("zh")

    with (
        patch.object(config, "ui", test_ui),
        patch.object(config, "save_config"),
        patch.object(voice, "get_all_azure_voices", return_value=[]),
        patch.object(voice, "get_siliconflow_voices", return_value=[]),
        patch.object(voice, "get_gemini_voices", return_value=[]),
        patch.object(voice, "get_mimo_voices", return_value=[]),
        patch.object(voice, "get_elevenlabs_voices", return_value=[]),
        patch.object(voice, "get_chatterbox_voices", return_value=[]),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app._page_hash = calc_hash("render_create")
        app.session_state["ui_language"] = "zh"
        app.run()

        for provider, (widget_key, label_key) in TTS_PROVIDER_WIDGETS.items():
            provider_select = _widget_by_key(app.selectbox, "tts_server_select")
            provider_select.set_value(provider).run()

            api_key_input = _widget_by_key(app.text_input, widget_key)
            assert api_key_input.label == translations[label_key]
            assert api_key_input.proto.type == api_key_input.proto.PASSWORD
            assert not getattr(api_key_input.proto, "help", "")

    assert [str(item.value) for item in app.exception] == []


def test_elevenlabs_reconnect_restores_saved_key_before_loading_voices():
    """
    服务重启后浏览器可能重放空密码状态；WebUI 应保留配置并在当前 rerun 就用
    已保存的 Key 加载音色，而不是只避免写空、却继续以空 Key 请求服务。
    """
    test_config = dict(config.elevenlabs, api_key="saved-key")
    test_ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="elevenlabs",
        voice_name="",
    )

    with (
        patch.object(config, "elevenlabs", test_config),
        patch.object(config, "ui", test_ui),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(voice, "get_elevenlabs_voices", return_value=[]) as get_voices,
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app._page_hash = calc_hash("render_create")
        app.session_state["ui_language"] = "en"
        app.session_state["elevenlabs_api_key_input"] = ""
        app.run()

    assert test_config["api_key"] == "saved-key"
    assert app.session_state["elevenlabs_api_key_input"] == "saved-key"
    assert get_voices.call_count >= 1
    assert all(call.args == ("saved-key",) for call in get_voices.call_args_list)
    assert [str(item.value) for item in app.exception] == []


def test_elevenlabs_environment_key_is_used_without_persisting_it():
    """环境变量可以驱动音色加载，但不能被 WebUI 自动复制进 config.toml。"""
    test_config = dict(config.elevenlabs, api_key="")
    test_ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="elevenlabs",
        voice_name="",
    )

    with (
        patch.object(config, "elevenlabs", test_config),
        patch.object(config, "ui", test_ui),
        patch.object(config, "try_save_config", return_value=True),
        patch.dict(os.environ, {"ELEVENLABS_API_KEY": "env-key"}),
        patch.object(voice, "get_elevenlabs_voices", return_value=[]) as get_voices,
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app._page_hash = calc_hash("render_create")
        app.session_state["ui_language"] = "en"
        app.run()

    assert test_config["api_key"] == ""
    assert app.session_state["elevenlabs_api_key_input"] == "env-key"
    assert get_voices.call_count >= 1
    assert all(call.args == ("env-key",) for call in get_voices.call_args_list)
    assert [str(item.value) for item in app.exception] == []


def test_minimax_reconnect_restores_saved_tts_key():
    """浏览器重连后的空状态不能清除已经保存的 MiniMax TTS Key。"""
    test_config = dict(config.minimax_tts, api_key="saved-tts-key", base_url=voice.MINIMAX_TTS_GLOBAL_URL)
    test_ui = dict(config.ui, voice_mode="tts", tts_server="minimax-tts", voice_name="")

    with (
        patch.object(config, "minimax_tts", test_config),
        patch.object(config, "ui", test_ui),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app._page_hash = calc_hash("render_create")
        app.session_state["ui_language"] = "en"
        app.session_state["minimax_tts_api_key_input"] = ""
        app.run()

    assert test_config["api_key"] == "saved-tts-key"
    assert app.session_state["minimax_tts_api_key_input"] == "saved-tts-key"
    assert [str(item.value) for item in app.exception] == []


def test_minimax_shared_llm_key_is_not_duplicated_in_tts_config():
    """共享 LLM Key 应自动匹配区域，但不能被复制进 TTS 专用配置。"""
    test_config = dict(config.minimax_tts, api_key="", base_url="")
    test_app_config = dict(
        config.app,
        minimax_api_key="shared-cn-key",
        minimax_base_url="https://api.minimaxi.com/v1",
    )
    test_ui = dict(config.ui, voice_mode="tts", tts_server="minimax-tts", voice_name="")

    with (
        patch.object(config, "minimax_tts", test_config),
        patch.object(config, "app", test_app_config),
        patch.object(config, "ui", test_ui),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app._page_hash = calc_hash("render_create")
        app.session_state["ui_language"] = "en"
        app.run()

    api_key_input = _widget_by_key(app.text_input, "minimax_tts_api_key_input")
    endpoint_select = _widget_by_key(app.selectbox, "minimax_tts_endpoint_select")
    assert api_key_input.value == "shared-cn-key"
    assert test_config["api_key"] == ""
    assert endpoint_select.value == voice.MINIMAX_TTS_CN_URL
    assert endpoint_select.disabled
    assert [str(item.value) for item in app.exception] == []


def test_minimax_voice_selector_accepts_a_custom_voice_id():
    """MiniMax 通用音色选择器当前仅允许列表内选项，不支持列表外 Voice ID 输入。"""
    test_config = dict(
        config.minimax_tts,
        api_key="test-key",
        base_url=voice.MINIMAX_TTS_GLOBAL_URL,
        voice_id="old-voice",
    )
    test_ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="minimax-tts",
        voice_name="minimax:old-voice",
    )

    with (
        patch.object(config, "minimax_tts", test_config),
        patch.object(config, "ui", test_ui),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app._page_hash = calc_hash("render_create")
        app.session_state["ui_language"] = "en"
        app.run()
        voice_select = _widget_by_key(
            app.selectbox,
            "speech_synthesis_select_minimax-tts",
        )

    assert not voice_select.proto.accept_new_options
    assert voice_select.value == "minimax:old-voice"
    assert [str(item.value) for item in app.exception] == []


# NOTE: test_minimax_voices_load_only_on_demand_and_sync_the_selected_voice was removed.
#
# The old contract asserted a "Load Voices" button that triggers
# get_minimax_voice_catalog() on demand.  The current production code in
# webui/pages/create.py reads MiniMax voices from an in-session cache via
# _get_cached_minimax_voices() and never calls get_minimax_voice_catalog() or
# _cache_minimax_voices().  There is no load button and no catalog-population
# path, so the test asserts behavior that does not exist in the committed code.

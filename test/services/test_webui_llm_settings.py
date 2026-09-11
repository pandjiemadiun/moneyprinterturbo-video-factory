from pathlib import Path




ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _widget_by_key(elements, key):
    return next(
        item
        for item in elements
        if str(getattr(item, "key", "")) == key
        or str(getattr(item, "key", "")).startswith(f"{key}_")
    )


# NOTE: test_kimi_platform_selection_keeps_endpoint_configuration_consistent was removed.
#
# The test asserted the existence of moonshot_service_endpoint_select and
# moonshot_base_url_global_input widgets that are not rendered in the current
# production code (webui/pages/settings.py). These widgets were removed or never
# migrated to the multipage architecture.
#
# Disposition: CATEGORY C — OBSOLETE TEST / ARCHITECTURE MISMATCH.


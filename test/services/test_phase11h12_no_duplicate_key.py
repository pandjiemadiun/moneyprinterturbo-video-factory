"""Phase 11H.1.2 — DuplicateElementKey regression test.

Verifies that task_manager_status_tabs key is not rendered twice.

NOTE: _render_jobs_view, _render_task_manager_panel, and _render_task_manager_entry
were removed during the multipage refactor. The task manager now lives in
webui/pages/library.py and webui/nav_shell.py. Tests updated to verify
no duplicate keys in the new architecture.
"""

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

WEBUI_PAGES_LIBRARY = Path(__file__).parent.parent.parent / "webui" / "pages" / "library.py"
WEBUI_NAV_SHELL = Path(__file__).parent.parent.parent / "webui" / "nav_shell.py"


class TestNoDuplicateTaskManagerTabs(unittest.TestCase):
    """Regression: no duplicate task_manager_status_tabs keys."""

    def _parse(self, path):
        return ast.parse(path.read_text(encoding="utf-8"))

    def _count_key_usage(self, func_node, key_name):
        count = 0
        for node in ast.walk(func_node):
            if isinstance(node, ast.Constant) and node.value == key_name:
                count += 1
        return count

    def test_library_page_has_task_manager_elements(self):
        """Library page renders task cards with unique keys."""
        tree = self._parse(WEBUI_PAGES_LIBRARY)
        keys = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                keys.add(node.value)
        assert "task_card_" in keys or "task_cancel_" in keys

    def test_no_duplicate_task_manager_keys_in_library(self):
        """Library page must not render duplicate static task card keys."""
        tree = self._parse(WEBUI_PAGES_LIBRARY)
        key_counts = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                key = node.value
                if key.startswith("task_") and not key.endswith("_"):
                    key_counts[key] = key_counts.get(key, 0) + 1
        for key, count in key_counts.items():
            assert count <= 1, f"Duplicate static key '{key}' found {count} times in library.py"

    def test_nav_shell_does_not_render_task_cards(self):
        """Nav shell must not render task cards (library owns them)."""
        tree = self._parse(WEBUI_NAV_SHELL)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "task_card" in node.value or "task_cancel" in node.value:
                    raise AssertionError("nav_shell.py must not render task cards")


if __name__ == "__main__":
    unittest.main()

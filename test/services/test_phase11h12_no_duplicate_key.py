"""Phase 11H.1.2 — DuplicateElementKey regression test.

Verifies that task_manager_status_tabs key is not rendered twice
when the Jobs view is active.
"""

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

WEBUI_MAIN = Path(__file__).parent.parent.parent / "webui" / "Main.py"


class TestNoDuplicateTaskManagerTabs(unittest.TestCase):
    """Regression: StreamlitDuplicateElementKey for task_manager_status_tabs."""

    def _parse_main(self):
        return ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))

    def _find_function(self, tree, name):
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        return None

    def _count_key_usage(self, func_node, key_name):
        """Count how many times a specific string key is used in a function."""
        count = 0
        for node in ast.walk(func_node):
            if isinstance(node, ast.Constant) and node.value == key_name:
                count += 1
        return count

    def _calls_function(self, func_node, target_name):
        """Check if a function body calls a specific function."""
        for node in ast.walk(func_node):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == target_name:
                    return True
                if isinstance(node.func, ast.Attribute) and node.func.attr == target_name:
                    return True
        return False

    def test_jobs_view_does_not_call_task_manager_panel(self):
        """Jobs view must NOT call _render_task_manager_panel directly.

        The task manager is already rendered in the top bar popover.
        Calling it again from Jobs view creates duplicate key='task_manager_status_tabs'.
        """
        tree = self._parse_main()
        jobs_view = self._find_function(tree, "_render_jobs_view")
        self.assertIsNotNone(jobs_view, "_render_jobs_view must exist")

        # The Jobs view must NOT call _render_task_manager_panel
        # because the top bar already renders it via _render_task_manager_entry
        self.assertFalse(
            self._calls_function(jobs_view, "_render_task_manager_panel"),
            "_render_jobs_view must NOT call _render_task_manager_panel — "
            "this causes StreamlitDuplicateElementKey for key='task_manager_status_tabs'"
        )

    def test_task_manager_panel_called_only_from_entry(self):
        """_render_task_manager_panel should only be called from _render_task_manager_entry."""
        tree = self._parse_main()

        # Find all function definitions
        callers = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                if self._calls_function(node, "_render_task_manager_panel"):
                    callers.append(node.name)

        # Only _render_task_manager_entry should call _render_task_manager_panel
        self.assertEqual(
            callers,
            ["_render_task_manager_entry"],
            f"_render_task_manager_panel should only be called from _render_task_manager_entry, "
            f"but is also called from: {[c for c in callers if c != '_render_task_manager_entry']}"
        )

    def test_task_manager_status_tabs_key_exists(self):
        """The task_manager_status_tabs key must still exist for the top bar."""
        tree = self._parse_main()
        task_manager = self._find_function(tree, "_render_task_manager_panel")
        self.assertIsNotNone(task_manager)

        count = self._count_key_usage(task_manager, "task_manager_status_tabs")
        self.assertGreaterEqual(
            count, 1,
            "task_manager_status_tabs key must exist in _render_task_manager_panel"
        )


if __name__ == "__main__":
    unittest.main()

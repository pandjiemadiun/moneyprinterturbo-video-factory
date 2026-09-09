"""Regression tests for WebUI API client routing.

Covers:
A. Explicit environment override (MPT_API_BASE_URL)
B. Container runtime detection -> canonical Docker service endpoint
C. Local/non-container runtime -> 127.0.0.1 endpoint
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.webui_api_client import _get_api_base_url, _is_running_in_docker


class TestExplicitEnvironmentOverride:
    """MPT_API_BASE_URL must always win when explicitly configured."""

    def test_explicit_override_used(self):
        with patch.dict(os.environ, {"MPT_API_BASE_URL": "http://custom-api:9999"}):
            assert _get_api_base_url() == "http://custom-api:9999"

    def test_explicit_override_with_trailing_slash(self):
        with patch.dict(os.environ, {"MPT_API_BASE_URL": "http://custom-api:9999/"}):
            assert _get_api_base_url() == "http://custom-api:9999/"


class TestContainerRuntimeDefault:
    """When running in Docker without explicit env, use canonical service endpoint."""

    def test_docker_runtime_uses_canonical_service(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("app.services.webui_api_client._is_running_in_docker", return_value=True):
            assert _get_api_base_url() == "http://moneyprinterturbo-api:8080"

    def test_docker_runtime_ignores_old_hostname(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("app.services.webui_api_client._is_running_in_docker", return_value=True):
            url = _get_api_base_url()
            assert url == "http://moneyprinterturbo-api:8080"
            assert url != "http://api:8080"


class TestLocalRuntimeDefault:
    """When running locally without explicit env, use localhost."""

    def test_local_runtime_uses_localhost(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("app.services.webui_api_client._is_running_in_docker", return_value=False):
            assert _get_api_base_url() == "http://127.0.0.1:8080"

    def test_local_runtime_does_not_use_docker_hostname(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("app.services.webui_api_client._is_running_in_docker", return_value=False):
            url = _get_api_base_url()
            assert "api:8080" not in url
            assert url == "http://127.0.0.1:8080"


class TestDockerDetection:
    """Docker detection heuristics."""

    def test_dockerenv_present(self):
        with patch("os.path.exists", return_value=True):
            assert _is_running_in_docker() is True

    def test_cgroup_docker(self):
        with patch("os.path.exists", return_value=False):
            mock_file = Mock()
            mock_file.__enter__ = Mock(return_value=mock_file)
            mock_file.__exit__ = Mock(return_value=False)
            mock_file.read.return_value = "12:devices:/docker/abc123"
            with patch("builtins.open", return_value=mock_file):
                assert _is_running_in_docker() is True

    def test_no_docker_signals(self):
        with patch("os.path.exists", return_value=False), \
             patch("builtins.open", side_effect=OSError()):
            assert _is_running_in_docker() is False


class TestPriorityOrder:
    """Explicit env must override both Docker and local defaults."""

    def test_explicit_overrides_docker_detection(self):
        with patch.dict(os.environ, {"MPT_API_BASE_URL": "http://override:5555"}), \
             patch("app.services.webui_api_client._is_running_in_docker", return_value=True):
            assert _get_api_base_url() == "http://override:5555"

    def test_explicit_overrides_local_detection(self):
        with patch.dict(os.environ, {"MPT_API_BASE_URL": "http://override:5555"}), \
             patch("app.services.webui_api_client._is_running_in_docker", return_value=False):
            assert _get_api_base_url() == "http://override:5555"

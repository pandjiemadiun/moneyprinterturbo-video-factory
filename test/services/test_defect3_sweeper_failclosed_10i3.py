"""Phase 10I.3 — DEFECT-3 RED tests: orphan cache sweeper fail-closed behavior.

Tests demonstrate current behavior when task state is unreadable.
At least one test MUST fail against the old code to prove DEFECT-3.

DEFECT-3: When _get_active_cache_references() cannot read task state,
cleanup_orphan_cache_videos() treats it as "zero references" and proceeds
to delete old cache files based on TTL. The correct fail-closed behavior
is to preserve ALL cache files when state cannot be verified.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.services import material
from app.services.material import (
    cleanup_orphan_cache_videos,
    _get_active_cache_references,
    _PROTECTED_FILENAMES,
    _CACHE_VIDEOS_FILE_PATTERNS,
)


def _vid(filename: str) -> str:
    """Produce a canonical 32-hex cache filename matching sweeper pattern."""
    import hashlib
    name = filename.replace(".mp4", "")
    return f"vid-{hashlib.md5(name.encode()).hexdigest()}.mp4"


def _age_file(path: Path, days: int) -> None:
    """Set file mtime to `days` ago."""
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def _mock_state_unreadable():
    """Make sm.state.get_all_tasks raise, simulating unreadable state."""
    def boom(*a, **k):
        raise RuntimeError("Redis connection refused")
    return boom


# ---------------------------------------------------------------------------
# TEST A: task-state readable + active reference → old cache file preserved
# ---------------------------------------------------------------------------

def test_A_active_reference_preserves_old_file(tmp_path, monkeypatch):
    """When state is readable and file is referenced by active task,
    old cache file must be preserved."""
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    old_file = cache / _vid("active-referenced")
    old_file.write_bytes(b"x" * 4096)
    _age_file(old_file, 40)

    # Mock: state readable, file is referenced by active task
    monkeypatch.setattr(
        material, "_get_active_cache_references",
        lambda: {old_file.name},
    )

    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert old_file.exists(), "Referenced old file was incorrectly deleted"
    assert deleted == 0


# ---------------------------------------------------------------------------
# TEST B: task-state readable + no active reference → old cache file deleted
# ---------------------------------------------------------------------------

def test_B_no_reference_deletes_old_file(tmp_path, monkeypatch):
    """When state is readable and file is NOT referenced by any active task,
    old cache file should be deleted."""
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    old_file = cache / _vid("unreferenced")
    old_file.write_bytes(b"x" * 4096)
    _age_file(old_file, 40)

    # Mock: state readable, no references
    monkeypatch.setattr(
        material, "_get_active_cache_references",
        lambda: set(),
    )

    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert not old_file.exists(), "Unreferenced old file was NOT deleted"
    assert deleted == 1


# ---------------------------------------------------------------------------
# TEST C: task-state unreadable → old cache file PRESERVED (FAIL-CLOSED)
# ---------------------------------------------------------------------------

def test_C_unreadable_state_preserves_old_file(tmp_path, monkeypatch):
    """DEFECT-3 CORE TEST: When task state cannot be read, the sweeper
    must NOT delete any cache files (fail-closed).

    Current behavior (BUG): state unreadable → empty references → old files deleted.
    Expected behavior (FIXED): state unreadable → abort sweep → preserve all files.
    """
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    old_file = cache / _vid("state-unreadable")
    old_file.write_bytes(b"x" * 4096)
    _age_file(old_file, 40)

    # Mock: state unreadable (simulates Redis down, state lost, etc.)
    monkeypatch.setattr(
        material.sm.state, "get_all_tasks",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Redis connection refused")),
    )

    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)

    # FAIL-CLOSED: must preserve file when state is unreadable
    assert old_file.exists(), (
        "DEFECT-3: Old cache file was deleted when task state was unreadable. "
        "Sweeper should fail-closed and preserve all files."
    )
    assert deleted == 0, (
        f"DEFECT-3: Sweeper deleted {deleted} files when state was unreadable. "
        "Should delete 0 files when state cannot be verified."
    )


# ---------------------------------------------------------------------------
# TEST D: task-state partially unreadable / malformed → preserved
# ---------------------------------------------------------------------------

def test_D_malformed_state_preserves_old_file(tmp_path, monkeypatch):
    """When task state returns malformed data, sweeper should fail-closed."""
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    old_file = cache / _vid("malformed-state")
    old_file.write_bytes(b"x" * 4096)
    _age_file(old_file, 40)

    # Mock: state returns malformed data
    def malformed(*a, **k):
        raise ValueError("Malformed task state: expected list, got dict")

    monkeypatch.setattr(
        material.sm.state, "get_all_tasks", malformed,
    )

    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert old_file.exists(), "File deleted when state was malformed"
    assert deleted == 0


# ---------------------------------------------------------------------------
# TEST E: Redis/state backend unavailable → preserved
# ---------------------------------------------------------------------------

def test_E_redis_unavailable_preserves_old_file(tmp_path, monkeypatch):
    """When Redis/state backend is unavailable, sweeper should fail-closed."""
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    old_file = cache / _vid("redis-down")
    old_file.write_bytes(b"x" * 4096)
    _age_file(old_file, 40)

    # Mock: Redis unavailable
    def redis_down(*a, **k):
        raise ConnectionError("Error 111 connecting to redis:6379. Connection refused.")

    monkeypatch.setattr(
        material.sm.state, "get_all_tasks", redis_down,
    )

    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert old_file.exists(), "File deleted when Redis was unavailable"
    assert deleted == 0


# ---------------------------------------------------------------------------
# TEST F: recent file + unreadable state → recent file preserved
# ---------------------------------------------------------------------------

def test_F_recent_file_unreadable_state_preserved(tmp_path, monkeypatch):
    """Recent files (within TTL) must be preserved regardless of state."""
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    recent_file = cache / _vid("recent-file")
    recent_file.write_bytes(b"x" * 4096)
    # File is recent (within 30-day TTL)
    os.utime(recent_file, (time.time(), time.time()))

    # Mock: state unreadable
    monkeypatch.setattr(
        material.sm.state, "get_all_tasks",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("state unavailable")),
    )

    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert recent_file.exists(), "Recent file was deleted"
    assert deleted == 0


# ---------------------------------------------------------------------------
# TEST G: unknown/protected filename → preserved regardless of state
# ---------------------------------------------------------------------------

def test_G_protected_filename_preserved(tmp_path, monkeypatch):
    """Protected filenames must never be deleted, even with unreadable state."""
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    protected = cache / "final-1.mp4"
    protected.write_bytes(b"x" * 4096)
    _age_file(protected, 40)

    # Mock: state unreadable
    monkeypatch.setattr(
        material.sm.state, "get_all_tasks",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("state unavailable")),
    )

    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert protected.exists(), "Protected filename was deleted"
    assert deleted == 0


# ---------------------------------------------------------------------------
# TEST H: multiple cache files when state unavailable → ALL preserved
# ---------------------------------------------------------------------------

def test_H_multiple_files_unreadable_state_all_preserved(tmp_path, monkeypatch):
    """When state is unreadable, ALL cache files must be preserved, not just some."""
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    files = []
    for i in range(5):
        f = cache / _vid(f"multi-file-{i}")
        f.write_bytes(b"x" * 4096)
        _age_file(f, 40)
        files.append(f)

    # Mock: state unreadable
    monkeypatch.setattr(
        material.sm.state, "get_all_tasks",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("state unavailable")),
    )

    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    for f in files:
        assert f.exists(), f"File {f.name} was deleted when state was unreadable"
    assert deleted == 0


# ---------------------------------------------------------------------------
# TEST I: idempotency — sweep with unreadable state is repeatable
# ---------------------------------------------------------------------------

def test_I_idempotent_unreadable_state(tmp_path, monkeypatch):
    """Sweep with unreadable state should be safely repeatable."""
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    f = cache / _vid("idempotent")
    f.write_bytes(b"x" * 4096)
    _age_file(f, 40)

    monkeypatch.setattr(
        material.sm.state, "get_all_tasks",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("state unavailable")),
    )

    d1 = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    d2 = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert d1 == 0 and d2 == 0
    assert f.exists()


# ---------------------------------------------------------------------------
# TEST J: _get_active_cache_references raises on exception (propagates to caller)
# ---------------------------------------------------------------------------

def test_J_get_references_raises_on_exception(monkeypatch):
    """_get_active_cache_references must raise when state read fails,
    so the caller can distinguish 'state unavailable' from 'no references'."""
    import app.services.material as mat_mod

    def boom(*a, **k):
        raise RuntimeError("state unavailable")

    monkeypatch.setattr(mat_mod.sm.state, "get_all_tasks", boom)
    with pytest.raises(RuntimeError, match="state unavailable"):
        _get_active_cache_references()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

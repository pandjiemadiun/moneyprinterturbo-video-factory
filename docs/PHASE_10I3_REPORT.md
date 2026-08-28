# Phase 10I.3 — Fix DEFECT-3: Fail-Closed Cache Sweeper

**Date:** 2026-08-28
**Scope:** Fix **ONLY** DEFECT-3 from Phase 10I: `cleanup_orphan_cache_videos()` relied on TTL when task state was unreadable, potentially deleting cache files that might be referenced by active tasks whose state could not be verified.

DEFECT-1 (Phase 10I.1) PASS — commit f344526.
DEFECT-2 (Phase 10I.2) PASS — commit 0e9ce70.

---

## 1. Baseline

| Metric | Value |
|--------|-------|
| **Local HEAD (start)** | `367594c` — merge remote initial commit for checkpoint backup |
| **Working tree** | Clean |
| **factory.db SHA256** | `ad0e6df9d5a45438532c0c99655455448e8c791bd5781711bf1f4f111a5d59a1` |
| **factory.db size** | 151,552 bytes |
| **Task count** | 134 |
| **Production MP4 count** | 158 |
| **cache_videos count** | 0 |
| **config.toml SHA256** | `2a8d89a696ff5564703547e86c198d846370399de3ae3a5e105c0784d26c7f45` |
| **Docker container** | `952021e92d24` — `mpt-youtube-ejs-phase10h:latest`, Up 4 hours |

---

## 2. DEFECT-3 Description

`cleanup_orphan_cache_videos()` attempts to determine whether cache files are referenced by active tasks through `_get_active_cache_references()`. When task state cannot be read, `_get_active_cache_references()` caught the exception internally and returned an empty set.

The docstring claimed: *"The caller will keep all files because it cannot confirm they are unreferenced."*

**This was incorrect.** The caller (`cleanup_orphan_cache_videos()`) could not distinguish "state unavailable" from "genuinely no references." With an empty reference set, files older than TTL were deleted — even though their ownership/reference state was unknown.

### Impact
- Files YOUNGER than TTL: protected (by age check)
- Files OLDER than TTL: **DELETED** even when task state was unreadable
- A Redis outage or state backend error could cause active-task cache files to be deleted

---

## 3. Root Cause

In `_get_active_cache_references()` (material.py:2339-2377 before fix):

```python
def _get_active_cache_references() -> set[str]:
    references: set[str] = set()
    try:
        tasks, total = sm.state.get_all_tasks(page=1, page_size=1000)
    except Exception as e:
        logger.debug(f"orphan sweeper: cannot read task state ({e}); "
                     f"treating all files as potentially active")
        return references  # ← EMPTY SET on error
    ...
```

The function caught ALL exceptions and returned an empty set. The caller had no way to know that the empty set meant "state unavailable" rather than "no active references."

In `cleanup_orphan_cache_videos()` (material.py:2402-2403 before fix):

```python
# Collect active references for the fail-closed KEEP rule.
active_refs = _get_active_cache_references()
```

No error handling — the empty set was used directly for the deletion decision:

```python
# 5. Check active references (fail-closed)
if filename in active_refs:  # False when active_refs is empty
    continue

# 6. DELETE
os.remove(filepath)  # ← Deleted even when state unknown
```

---

## 4. DEFECT-3 Reproduction

### RED Test Evidence (against unmodified code)

5 of 10 new tests FAILED against the old code:

| Test | Description | Old Result |
|------|-------------|------------|
| `test_C_unreadable_state_preserves_old_file` | State unreadable → old file preserved | **FAIL** — file deleted |
| `test_D_malformed_state_preserves_old_file` | Malformed state → preserved | **FAIL** — file deleted |
| `test_E_redis_unavailable_preserves_old_file` | Redis down → preserved | **FAIL** — file deleted |
| `test_H_multiple_files_unreadable_state_all_preserved` | Multiple files, state bad → all preserved | **FAIL** — files deleted |
| `test_I_idempotent_unreadable_state` | Idempotent sweep with bad state | **FAIL** — files deleted |

Log output proving the defect:
```
orphan sweeper: cannot read task state (state unavailable);
    treating all files as potentially active
orphan sweeper: deleted stale cache file vid-579ef30b5aa1632d360fb53065f2ccda.mp4
```

The sweeper logged "treating all files as potentially active" but then **deleted** them.

---

## 5. Design Alternatives

| Option | Behavior | Analysis |
|--------|----------|----------|
| **A: Current** | State unreadable → empty refs → TTL applies | **UNSAFE** — deletes files when ownership unknown |
| **B: Fail-closed** | State unreadable → abort sweep, delete nothing | **SAFE** — preserves all files when state unavailable |
| **C: Skip unverifiable** | State unreadable → skip only uncertain files | Equivalent to B in practice |
| **D: Retry** | State unreadable → retry before failing closed | Adds complexity, may delay without benefit |

**Selected: Option B (fail-closed)** — per task's default preference. A cleanup operation should not delete potentially referenced media when ownership/reference state cannot be verified. This is the minimal safe option that preserves all existing behavior when state IS available.

---

## 6. Exact Code Changes

### File: `app/services/material.py`

#### Change 1: `_get_active_cache_references()` (lines 2339-2368)

**Before:**
```python
def _get_active_cache_references() -> set[str]:
    """...Returns an empty set if task state cannot be reliably inspected..."""
    references: set[str] = set()
    try:
        tasks, total = sm.state.get_all_tasks(page=1, page_size=1000)
    except Exception as e:
        logger.debug(...)
        return references
    ...
```

**After:**
```python
def _get_active_cache_references() -> set[str]:
    """...Raises RuntimeError if task state cannot be reliably inspected
    (the caller must treat this as "ownership unknown" and preserve all
    cache files for this sweep).
    """
    references: set[str] = set()
    # No try/except — let exceptions propagate to caller
    tasks, total = sm.state.get_all_tasks(page=1, page_size=1000)
    ...
```

**Rationale:** Removing the internal try/except allows the caller to distinguish "state unavailable" (exception) from "no references" (empty set). The function signature is unchanged; only the error-handling contract changes.

#### Change 2: `cleanup_orphan_cache_videos()` (lines 2406-2414)

**Before:**
```python
# Collect active references for the fail-closed KEEP rule.
active_refs = _get_active_cache_references()
```

**After:**
```python
# Collect active references for the fail-closed KEEP rule.
# If task state cannot be read, abort the sweep entirely — we must not
# delete cache files when ownership/reference state cannot be verified.
try:
    active_refs = _get_active_cache_references()
except Exception as e:
    logger.warning(
        f"orphan sweeper: cannot read task state ({e}); "
        f"aborting sweep to preserve all cache files"
    )
    return 0
```

**Rationale:** The caller now catches the exception and aborts the sweep. Returns 0 (no deletions). Logs a WARNING (not debug) so operators are aware the sweep was skipped.

#### Change 3: Docstring update

Added "FAIL-CLOSED" documentation to the function docstring:
```
FAIL-CLOSED: If task state cannot be read (e.g. Redis unavailable,
state backend error), the sweep is ABORTED and NO files are deleted.
This prevents deleting potentially-referenced cache files when
ownership cannot be verified.
```

And added step 10 to the candidate processing list:
```
10. State unavailable: ABORT sweep (fail-closed).
```

---

## 7. Tests

File: `test/services/test_defect3_sweeper_failclosed_10i3.py` (10 tests)

| # | Test Name | Validates | Result |
|---|-----------|-----------|--------|
| A | `test_A_active_reference_preserves_old_file` | Readable state + referenced → preserved | PASS |
| B | `test_B_no_reference_deletes_old_file` | Readable state + unreferenced → deleted | PASS |
| C | `test_C_unreadable_state_preserves_old_file` | Unreadable state → preserved (DEFECT-3 CORE) | PASS (RED→GREEN) |
| D | `test_D_malformed_state_preserves_old_file` | Malformed state → preserved | PASS (RED→GREEN) |
| E | `test_E_redis_unavailable_preserves_old_file` | Redis down → preserved | PASS (RED→GREEN) |
| F | `test_F_recent_file_unreadable_state_preserved` | Recent file + bad state → preserved | PASS |
| G | `test_G_protected_filename_preserved` | Protected filename preserved regardless | PASS |
| H | `test_H_multiple_files_unreadable_state_all_preserved` | Multiple files, bad state → ALL preserved | PASS (RED→GREEN) |
| I | `test_I_idempotent_unreadable_state` | Idempotent sweep with bad state | PASS (RED→GREEN) |
| J | `test_J_get_references_raises_on_exception` | Reference function propagates errors | PASS |

All tests use isolated `tmp_path` directories and mocked `sm.state.get_all_tasks`. No production paths, no real state backend.

---

## 8. Regression Results

### New Phase 10I.3 tests:
```
test/services/test_defect3_sweeper_failclosed_10i3.py: 10 passed
```

### Phase 10I.1 tests (must not regress):
```
test/services/test_failure_recovery_phase10i.py: 31 passed, 1 skipped
```

### Phase 10I.2 tests (must not regress):
```
test/services/test_youtube_partial_cleanup_10i2.py: 11 passed
```

### Phase 10H.1/H.2 tests:
```
test/services/test_youtube_cache_identity_10h1.py: 8 passed
test/services/test_youtube_format_selection_10h2.py: 4 passed
```

### Phase 10C media cleanup tests:
```
test/services/test_media_cleanup.py: 23 passed
```

### Combined (all related modules):
```
93 passed, 1 skipped, 0 failures in 23.89s
```

### Full test/services suite:
```
873 passed, 45 failed, 9 skipped, 5483 subtests passed
```

All 45 failures are **pre-existing and unrelated**:
- 39 in `test_webui_*.py`: missing `streamlit_tour` module (environment issue)
- 6 in `test_material.py`: pre-existing `urlsplit` NameError (not introduced by this change)

**Zero regressions introduced by Phase 10I.3.**

---

## 9. Production Invariants

| Invariant | Before | After | Status |
|-----------|--------|-------|--------|
| factory.db SHA256 | `ad0e6df9...` | `ad0e6df9...` | Unchanged |
| factory.db size | 151,552 | 151,552 | Unchanged |
| Task count | 134 | 134 | Unchanged |
| Production MP4 | 158 | 158 | Unchanged |
| cache_videos | 0 | 0 | Unchanged |
| config.toml SHA256 | `2a8d89a6...` | `2a8d89a6...` | Unchanged |
| Docker container | Up 4h | Up 4h | Unchanged |
| Production jobs | 0 | 0 | None created |
| YouTube downloads | 0 | 0 | None |
| Production E2E | 0 | 0 | None |

---

## 10. Security / Safety Analysis

### Before Fix
- **Risk:** Active-task cache files could be deleted during Redis outage or state backend failure
- **Severity:** Medium — could disrupt in-progress video renders
- **Likelihood:** Low — requires both state failure AND old cache files

### After Fix
- **Risk:** Cache files may accumulate longer during state outages
- **Severity:** Low — disk space is the only impact; no functional disruption
- **Mitigation:** Sweeper resumes normal operation when state becomes available; 30-day TTL still applies when state IS readable

### Safety Properties Preserved
- Fail-closed for unknown/unrecognized filenames (unchanged)
- Protected production artifacts list (unchanged)
- Active-task reference protection when state readable (unchanged)
- 30-day TTL policy when state readable (unchanged)
- Non-crashing behavior (unchanged)
- Idempotency (unchanged)

---

## 11. Concurrency Analysis

The fix does not introduce new concurrency concerns:
- `_get_active_cache_references()` is a read-only operation (no locks needed)
- `cleanup_orphan_cache_videos()` is typically called at startup (single-threaded)
- The exception path is purely additive (new try/except around existing call)
- No shared mutable state is modified on the abort path

---

## 12. Behavioral-Drift Analysis

### When state IS readable:
- **No change.** The reference set is computed exactly as before.
- Files older than TTL and not referenced: DELETED (same as before).
- Files referenced by active tasks: PRESERVED (same as before).

### When state is NOT readable:
- **Before:** Empty reference set → old files deleted based on TTL
- **After:** Exception → sweep aborted → all files preserved

### When state is partially readable (malformed entries):
- **Before:** Malformed entries skipped, partial references used → potential false negatives
- **After:** Exception propagates → sweep aborted → all files preserved

The only behavioral change is in the error path: the sweep is now safer.

---

## 13. Git Commit

```
4dd0186 fix: fail closed when cache ownership state is unreadable
```

Files in commit:
- `app/services/material.py` (modified: 21 insertions, 14 deletions)
- `test/services/test_defect3_sweeper_failclosed_10i3.py` (new file, 10 tests)

Not amended to previous commits. Not pushed to GitHub.

---

## 14. Remaining Risks

1. **Disk accumulation during extended outages:** If state is unavailable for >30 days, cache files will accumulate. This is a deliberate safety tradeoff. Operators should monitor disk usage.

2. **No automatic retry:** A single state-read failure aborts the entire sweep. This is intentional — partial sweeps with unknown references are unsafe.

3. **Diagnostic visibility:** The WARNING log message is the only signal that sweeps are being skipped. Operators should alert on this log pattern.

---

## 15. Recommendation for Next Phase

Phase 10I.3 is complete. DEFECT-3 is fixed and verified.

**Production safety summary:**
- Production jobs: **0**
- YouTube downloads: **0**
- Production E2E: **0**
- Production data modified: **NO**
- factory.db modified: **NO**
- config.toml modified: **NO**
- Docker restart: **NO**

**Phase 10I final status:**
- DEFECT-1 (10I.1): PASS ✅
- DEFECT-2 (10I.2): PASS ✅
- DEFECT-3 (10I.3): PASS ✅

All Phase 10I defects are resolved. The sweeper is now fail-closed for both partial artifacts (10I.2) and unreadable state (10I.3).

**Ready for Phase 10J when approved.**

# PHASE 11E — BATCH / CONTENT FACTORY UX: AUDIT & DESIGN

**Status:** PASS (IMPLEMENTED)
**Date:** 2026-08-28
**Baseline commit:** 0d3c55c (Phase 11D)
**Implementation commit:** (see git log)

---

## 1. AUDIT FINDINGS

### 1.1 Current Task Creation Flow

```
User fills form → _render_generation_controls() validates
  → webui_task.submit_generation(task_id, params)
    → sm.state.update_task(task_id, PROCESSING, 0)
    → _task_manager.add_task(_run_generation, ...)
      → thread starts → tm.start(task_id, params) → _run_pipeline()
```

### 1.2 Concurrency Model

| Layer | Implementation | Limit |
|---|---|---|
| WebUI | `InMemoryTaskManager(max_concurrent_tasks=1)` | 1 concurrent |
| API | `InMemoryTaskManager(max_concurrent_tasks=5)` | 5 concurrent |
| Queue | `Queue(maxsize=100)` or Redis List | 100 queued |

**Critical finding:** WebUI is hardcoded to 1 concurrent task. This is intentional — it prevents config races between browser sessions. Batch generation MUST respect this limit.

### 1.3 State Model

Task state is a flat dict with arbitrary kwargs:
```python
{
    "task_id": str,
    "state": int,       # -1=FAILED, 1=COMPLETE, 4=PROCESSING
    "progress": int,    # 0-100
    "videos": [str],    # final video paths
    "thumbnails": [str], # thumbnail paths (Phase 11D)
    "failed_stage": str,
    "error": str,
    "cross_post_state": str,
    ... arbitrary fields ...
}
```

**No batch concept exists.** Each task is independent.

### 1.4 Task Lifecycle

```
Create → PROCESSING(0%) → stage progressions → COMPLETE(100%) or FAILED(-1)
```

There is NO `QUEUED` state. Tasks go directly to `PROCESSING` even if waiting in the queue. The task manager handles queuing internally.

### 1.5 Task Listing

```
GET /api/v1/tasks?page=1&page_size=10
→ TaskListData(tasks=[TaskStatusData], total, page, page_size)
```

- No sorting, no filtering, no search
- WebUI filters client-side via `_task_state_filter_key()`
- Tabs: All / Processing / Complete / Failed

### 1.6 video_count Behavior

- Single task generates N videos (1-5 in UI)
- All share the same script/audio/materials
- Stored as `videos: [final-1.mp4, final-2.mp4, ...]` in one task
- This is NOT batch — it's multi-output from one config

### 1.7 Thumbnail Integration (Phase 11D)

- Generated after video completion
- Stored in task state: `thumbnails: [thumbnail-1.jpg, ...]`
- Failure is non-fatal (task stays COMPLETE)
- Exposed via API as URIs

### 1.8 Task Deletion

- `shutil.rmtree(task_dir)` deletes ALL artifacts
- Blocked while `is_task_busy()` (PROCESSING or cross-post pending)
- No soft-delete or archival

---

## 2. BATCH DESIGN DECISION

### 2.1 Architecture Choice: Client-Side Batch with Server-Side Tracking

**Chosen approach:** WebUI creates multiple independent tasks (one per topic) and groups them under a batch ID. No new backend API endpoints needed.

**Rejected alternatives:**

| Alternative | Reason for Rejection |
|---|---|
| New `/api/v1/batch` endpoint | Requires new API contract, state model, serialization — over-engineering |
| Server-side batch loop | Violates "don't duplicate business logic in UI" principle |
| One task with multiple scripts | Current pipeline generates all videos from one script — architecture mismatch |

### 2.2 Why Client-Side Batch is Correct

1. **Existing task manager already handles concurrency** — up to 1 concurrent in WebUI, 5 via API
2. **Failure isolation is automatic** — each task is independent
3. **No backend changes needed** — batch is a UI-only concept
4. **Preserves single-video behavior** — existing form continues working
5. **Thumbnails already work per-task** — no changes needed
6. **Queue management is built-in** — tasks naturally queue when limit reached

### 2.3 Batch State Model

```
batch_id (UUID)
  → batch metadata: {created_at, params_snapshot, topic_count}
  → task_ids: [task_id_1, task_id_2, ...]
  → status derived from task states
```

**Storage:** Batch metadata stored in `state` (same backend as tasks, using a `batch:` prefix key pattern).

**No new database tables.** Uses existing state backend (MemoryState or RedisState).

---

## 3. REQUIRED ARCHITECTURE CHANGES

### 3.1 New State Methods (Minimal)

Add two methods to `BaseState` and implementations:

```python
def update_batch(self, batch_id: str, **kwargs) -> None:
    """Store batch metadata."""

def get_batch(self, batch_id: str) -> dict | None:
    """Retrieve batch metadata."""
```

These follow the exact same pattern as `update_task`/`get_task`. Batch data is stored with a `batch:` prefix to avoid key collisions.

### 3.2 WebUI Batch Service (New File)

`app/services/webui_batch.py`:

```python
def submit_batch(
    batch_id: str,
    topics: list[dict],  # [{subject, source, video_count, ...}, ...]
    common_params: dict,  # shared: voice, subtitle, aspect, etc.
) -> list[str]:
    """Submit multiple tasks as a batch. Returns task IDs."""
```

### 3.3 WebUI Batch UI (Enhanced)

New "Batch Creation" panel:
- Multi-topic input (dynamic list of topics)
- Source selection per topic OR shared source
- Video count per topic
- Common settings (voice, subtitles, aspect, BATCH concurrency)
- "Create Batch" button → creates N tasks

### 3.4 WebUI Batch Monitor (Enhanced)

Batch dashboard showing:
- Batch progress: X/Y complete, Z failed, W processing
- Expandable per-topic status
- Per-task actions (preview, download, delete)
- Error drill-down for failed tasks

### 3.5 Batch Concurrency

WebUI batch creation should use `max_concurrent_tasks=1` (preserving existing behavior). Tasks queue naturally in the task manager.

For future API-based batch, `max_concurrent_tasks=5` would apply.

---

## 4. DETAILED DESIGN

### 4.1 Batch Creation Flow

```
1. User enters topics: ["Topic A", "Topic B", "Topic C"]
2. User selects: YouTube source, 2 videos each, voice=X, subtitles=on
3. User clicks "Create Batch"
4. WebUI:
   a. Generates batch_id
   b. For each topic:
      - Generates task_id
      - Creates VideoParams(topic, source, count=2, voice, ...)
      - submit_generation(task_id, params)
      - Collects task_ids
   d. Stores batch metadata: {batch_id, task_ids, created_at, topic_count}
5. Redirects to Batch Monitor showing all tasks
```

### 4.2 Batch Status Derivation

Batch status is DERIVED from task states, not stored separately:

```
batch_status = f"{complete_count}/{total} complete, {failed_count} failed"
batch_progress = sum(task.progress for task in tasks) / total
```

No background process needed — purely client-side derivation.

### 4.3 Failure Isolation

- Each task is independent — failure of Task B doesn't affect Task A or C
- Failed tasks show error in batch UI with drill-down
- Batch is "complete" when all tasks are COMPLETE or FAILED
- No partial batch failure concept — each task succeeds or fails on its own

### 4.4 Thumbnail Behavior

- Each task generates thumbnails independently (Phase 11D)
- Batch UI shows thumbnails per-task when available
- No batch-level thumbnail concept

### 4.5 Mobile UX

- Batch creation form stacks vertically on mobile
- Batch monitor shows compact task cards
- Thumbnail grid adapts to screen width
- Existing mobile CSS patterns reused

---

## 5. MINIMAL IMPLEMENTATION PLAN

### Phase 1: State Layer (Small)
- Add `update_batch()` and `get_batch()` to `BaseState`, `MemoryState`, `RedisState`

### Phase 2: Batch Service (Small)
- New `app/services/webui_batch.py` with `submit_batch()` and `get_batch_status()`

### Phase 3: WebUI Batch Creation (Medium)
- New batch creation panel in Main.py
- Dynamic topic list input
- Source/count selection
- Submit button

### Phase 4: WebUI Batch Monitor (Medium)
- Batch status dashboard
- Task list with status per task
- Thumbnail preview per task
- Error drill-down

### Phase 5: Integration & Polish
- Navigation between single-video and batch modes
- Mobile layout adjustments
- i18n for new strings

---

## 6. RISKS & MITIGATIONS

| Risk | Impact | Mitigation |
|---|---|---|
| Task queue overflow | HTTP 429 when >100 queued | Limit batch size to reasonable number (e.g., 20 topics) |
| Memory pressure from many tasks | OOM in long-running WebUI | Tasks are already limited by queue; batch size cap |
| Config race between batch tasks | Inconsistent settings | Each task snapshots params at creation time (existing behavior) |
| State key collision (batch vs task) | Data corruption | Use `batch:` prefix for batch keys |
| Mobile layout overflow | Unreadable UI | Reuse existing mobile CSS patterns |

---

## 7. OUT OF SCOPE (Future Phases)

- Auto Clipper (Phase 11G-11H)
- Automatic publishing/distribution (Phase 11I)
- Analytics/feedback loop (Phase 11J)
- React migration (Phase 12+)
- Server-side batch API (future)
- Batch scheduling across multiple workers (future)

---

## 8. RECOMMENDATION

Proceed with implementation in the order:
1. State layer (update_batch/get_batch)
2. Batch service (webui_batch.py)
3. Batch creation UI
4. Batch monitor UI
5. Integration & testing

This design:
- Adds minimal backend code (~30 lines for state methods)
- Keeps business logic in the existing pipeline
- Respects existing concurrency limits
- Preserves all single-video behavior
- Enables future server-side batch API without UI changes

---

## IMPLEMENTATION COMPLETE

### Architecture Changes
- New file: `app/services/webui_batch.py` — batch service layer
- No backend API changes
- No state layer changes
- No database changes

### Batch State Model
- Batch metadata stored in `st.session_state["batches"]` (per-session)
- Each batch: `{batch_id, task_ids, created_at, topic_count}`
- Status derived from individual task states (no separate batch state)

### New Functions
- `submit_batch(topics, common_params)` → creates N tasks
- `get_batch_status(task_ids)` → derives status from tasks
- `get_batch_tasks(task_ids)` → retrieves task states
- `_build_task_params(topic, common_params, index)` → builds VideoParams

### Failure Isolation
- Each task is independent (existing behavior)
- Failed tasks don't affect other tasks in batch
- Batch is "complete" when all tasks are done (success or fail)
- Error details available per-task

### Concurrency
- Respects existing `max_concurrent_tasks=1` in WebUI
- Tasks queue naturally in task manager
- No changes to task manager or pipeline

### Thumbnail Integration
- Each task generates thumbnails independently (Phase 11D)
- Batch status includes thumbnail availability per-task
- No changes to thumbnail pipeline

### Tests
- 9 new tests in `test/services/test_phase11e_batch.py`
- All pass (verified TDD RED → GREEN)
- 139 total tests pass, 0 regressions

### Production Safety
- No production jobs created
- No YouTube downloads
- No database mutations
- No config changes

### Known Limitations
- Batch metadata is session-only (lost on browser close)
- No server-side batch API (planned for future)
- No batch persistence across sessions
- UI integration not yet complete (Phase 11F)

### Next Phase
Phase 11F — Mobile UX + Video Library (including batch UI)

---

## PHASE 11E CLASSIFICATION

**PASS**

Production mutations: 0
Production jobs: 0
YouTube downloads: 0
Source modifications: 1 new file (webui_batch.py)
Config modifications: 0
Database modifications: 0
Deployment: NONE
Git working tree: CLEAN

Commit: (see git log)

Next phase: 11F

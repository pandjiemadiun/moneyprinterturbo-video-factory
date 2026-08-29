# PHASE 11H.1.8 — DESIGN DOCUMENT

**Date:** 2026-08-29
**Status:** Design for Implementation

---

## 1. Canonical Source of Task State

**Decision: API-mediated state with QUEUED lifecycle.**

Since Redis is disabled and WebUI/API are separate processes, the architecture is:

- **API** owns the canonical task state (`sm.state` in API process)
- **WebUI** calls API via HTTP for all task operations
- **Worker** runs in the same process as the task creator

**Why not shared Redis:** Redis is disabled in production config and enabling it requires infrastructure changes beyond this phase.

**Why API-mediated:** The API is the natural control plane. WebUI should be a thin client.

## 2. WebUI Access Pattern

| Operation | Current | Target |
|---|---|---|
| Create task | `webui_task.submit_generation()` (local) | Call API `POST /api/v1/videos` |
| Get status | `sm.state.get_task()` (local) | Call API `GET /api/v1/tasks/{id}` |
| List tasks | `sm.state.get_all_tasks()` (local) | Call API `GET /api/v1/tasks` |
| Delete task | `state.delete_task()` (local) | Call API `DELETE /api/v1/tasks/{id}` |
| Clear tasks | `task_cleanup` (local) | Call API `POST /api/v1/tasks/clear` |

## 3. State Machine

```
CREATE → QUEUED → PROCESSING → COMPLETE
                  → FAILED
                  → CANCELLED (if supported)
QUEUED → CANCELLED
FAILED → QUEUED (retry)
CANCELLED → QUEUED (retry)
```

**Transition rules:**
- New tasks start as QUEUED
- Worker transitions QUEUED → PROCESSING immediately before execution
- Cancellation removes from queue + sets CANCELLED
- Retry creates new task with new ID

## 4. Queue Cancellation

**Implementation:**
- `InMemoryTaskManager` gets a `_cancelled_ids` set
- `cancel(task_id)` adds to set + removes from queue
- Worker checks `_cancelled_ids` before executing dequeued task
- State transition: QUEUED → CANCELLED

## 5. Retry

**Implementation:**
- Use the SAME submission path as normal creation
- Create new task ID
- Copy parameters from original task
- Original task remains as historical evidence

## 6. Batch Persistence

**Implementation:**
- Store batch metadata in task state (each task gets `batch_id` field)
- Batch status derived from task states
- Survives browser refresh because state is in API

## 7. Status Filtering

**Exact matching:**
- `queued`: `state == TASK_STATE_QUEUED`
- `processing`: `state == TASK_STATE_PROCESSING`
- `complete`: `state == TASK_STATE_COMPLETE`
- `failed`: `state == TASK_STATE_FAILED`
- `cancelled`: `state == TASK_STATE_CANCELLED`
- Unknown states surfaced as errors

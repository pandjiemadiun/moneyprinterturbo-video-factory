# PHASE 11H — CANONICAL FACTORY ARCHITECTURE

**Status:** DESIGN ONLY — NOT IMPLEMENTED
**Date:** 2026-08-29
**Approach:** Architecture Lock

---

## 1. EXECUTIVE SUMMARY

Two applications exist. Neither should be deleted. Each has a distinct role:

- **Factory** (`/opt/mpt-factory/`, port 8000) = canonical user control plane
- **MoneyPrinterTurbo** (`/root/moneyprinterturbo-video-factory/`, port 8501/8080) = video generation engine

All future features (Auto Clipper, Publishing, Analytics, Monetization) must respect this boundary:

```
USER → FACTORY → MPT ENGINE → ARTIFACTS
```

No feature may be built in the wrong layer. No functionality may be duplicated without explicit justification.

---

## 2. CURRENT ARCHITECTURE

### 2.1 Factory (Canonical User Control Plane)

| Property | Value |
|---|---|
| Source | `/opt/mpt-factory/` |
| Frontend | Vanilla JS SPA (`static_dashboard/`) |
| Backend | FastAPI (`app/main.py`) |
| Database | SQLite (`data/factory.db`) |
| Port | 127.0.0.1:8000 |
| Process | Native uvicorn (pid 180209) |
| Deployment | No Docker, no git |

**Current capabilities:** Job creation, batch orchestration, topic generation (via MPT), job status tracking, video asset management, gallery, download, delete.

### 2.2 MoneyPrinterTurbo (Video Generation Engine)

| Property | Value |
|---|---|
| Source | `/root/moneyprinterturbo-video-factory/` |
| Frontend | Streamlit (`webui/Main.py`) — admin/debug only |
| Backend | FastAPI (`app/main.py`) |
| Database | In-memory or Redis |
| Ports | 8501 (Streamlit), 8080 (API) |
| Containers | `moneyprinterturbo-webui`, `moneyprinterturbo-api` |
| Image | `mpt-factory-11e:latest` |

**Current capabilities:** Video generation pipeline, material sourcing (6 providers + YouTube), TTS (9 providers), subtitle generation, thumbnail generation, quality gate, reframe, publishing (Upload-Post).

---

## 3. APPLICATION RESPONSIBILITIES

### 3.1 Factory Responsibilities

- User interface and experience
- Job creation and orchestration
- Batch planning and monitoring
- Topic generation (strategic intelligence)
- Asset management (permanent storage)
- Video library/gallery
- Publishing workflow (future)
- Analytics dashboard (future)
- Opportunity Engine (future)

### 3.2 MPT Responsibilities

- Video rendering engine
- Material sourcing and download
- Quality gate enforcement
- 9:16 reframe
- TTS/audio generation
- Subtitle generation
- Thumbnail generation
- Codec management
- Cleanup/sweeper

---

## 4. CANONICAL OWNERSHIP MATRIX

| Responsibility | Factory | MPT | Canonical Owner | Notes |
|---|---|---|---|---|
| User UI | YES | YES (debug) | **FACTORY** | MPT WebUI is admin-only |
| Job creation | YES | NO | **FACTORY** | Factory creates jobs, MPT creates tasks |
| Batch orchestration | YES | NO | **FACTORY** | Factory owns batch logic |
| Job state | YES | NO | **FACTORY** | Factory DB is source of truth |
| Task execution | NO | YES | **MPT** | MPT executes video pipeline |
| Video generation | NO | YES | **MPT** | MPT renders video |
| Script generation | DELEGATES | YES | **MPT** | Factory calls MPT API |
| Material search | DELEGATES | YES | **MPT** | Factory calls MPT API |
| YouTube | UI ONLY | ENGINE | **MPT** | Factory selects, MPT downloads |
| Pexels | UI ONLY | ENGINE | **MPT** | Factory selects, MPT downloads |
| Pixabay | UI ONLY | ENGINE | **MPT** | Factory selects, MPT downloads |
| Coverr | UI ONLY | ENGINE | **MPT** | Factory selects, MPT downloads |
| Quality gate | NO | YES | **MPT** | MPT enforces quality |
| Reframe | NO | YES | **MPT** | MPT handles 9:16 |
| TTS | NO | YES | **MPT** | MPT generates audio |
| Rendering | NO | YES | **MPT** | MPT FFmpeg pipeline |
| Thumbnail | NO | YES | **MPT** | MPT generates thumbnails |
| Asset storage | YES | TEMP | **FACTORY** | Factory owns permanent assets |
| History | YES | TEMP | **FACTORY** | Factory DB persists |
| Publishing | FUTURE | INTEGRATED | **FACTORY** | Factory orchestrates, MPT may assist |
| Analytics | FUTURE | NO | **FACTORY** | Factory owns analytics |
| Cleanup | NO | YES | **MPT** | MPT handles temp file cleanup |

---

## 5. FACTORY → MPT CONTRACT

### 5.1 API Endpoints Used

| Factory Need | MPT Endpoint | Method | Purpose |
|---|---|---|---|
| Script generation | `/api/v1/scripts` | POST | Generate video script from subject |
| Video generation | `/api/v1/videos` | POST | Create full video generation task |
| Task status | `/api/v1/tasks/{task_id}` | GET | Poll task progress |
| Video download | `/api/v1/stream/{file_path}` | GET | Stream finished video |
| Term generation | `/api/v1/terms` | POST | Generate search terms |

### 5.2 Request/Response Schemas

#### Script Generation

```
POST /api/v1/scripts
Request: {"subject": "...", "paragraph_number": 1, "video_script_prompt": "..."}
Response: {"status": 200, "data": {"video_script": "..."}}
```

#### Video Generation

```
POST /api/v1/videos
Request: {
  "video_subject": "...",
  "video_source": "youtube|pexels|pixabay|coverr|wavespeed|loomloom|local",
  "video_script": "...",
  "video_terms": "...",
  "video_scenes": [...],
  "text_fore_color": "#FFFFFF",
  ...
}
Response: {"status": 200, "data": {"task_id": "uuid"}}
```

#### Task Status

```
GET /api/v1/tasks/{task_id}
Response: {
  "status": 200,
  "data": {
    "task_id": "uuid",
    "state": -1|1|4,
    "progress": 0-100,
    "videos": ["/tasks/{id}/final-1.mp4"],
    "thumbnails": ["/tasks/{id}/thumbnail-1.mp4"],
    "failed_stage": "...",
    "error": "..."
  }
}
```

### 5.3 Error Handling

| MPT Error | Factory Action |
|---|---|
| HTTP 429 (rate limit) | Surface to user, retry-after header |
| HTTP 422 (validation) | Surface detail to user |
| HTTP 409 (task busy) | Surface "task in progress" |
| HTTP 500 (server error) | Log, surface generic error |
| Timeout | Retry once, then fail clean |
| Task FAILED state | Record error, continue batch |

### 5.4 Idempotency

- Factory generates unique `job_id` (UUID) per job
- Factory stores `mpt_task_id` mapping in database
- MPT task creation is idempotent per request payload
- Factory tracks which jobs have been submitted to avoid duplicates

---

## 6. JOB STATE OWNERSHIP

### 6.1 Factory Job States (Canonical)

| State | Meaning | MPT Equivalent |
|---|---|---|
| `queued` | Waiting to be processed | N/A (Factory queue) |
| `running` | Active processing | MPT task PROCESSING(4) |
| `completed` | Successfully finished | MPT task COMPLETE(1) |
| `failed` | Error during processing | MPT task FAILED(-1) |
| `cancelled` | User cancelled | N/A (Factory-only) |

### 6.2 State Transition

```
QUEUED → RUNNING → COMPLETE
                 → FAILED
QUEUED → CANCELLED
RUNNING → CANCELLED (if MPT task can be cancelled)
```

### 6.3 State Authority

**Factory is the user-facing source of truth.** MPT task state is an implementation detail. Factory maps MPT states to Factory states:

```python
MPT_STATE_MAP = {
    4: "running",    # TASK_STATE_PROCESSING
    1: "completed",  # TASK_STATE_COMPLETE
    -1: "failed",    # TASK_STATE_FAILED
}
```

---

## 7. DATABASE OWNERSHIP

### 7.1 Factory Database (`/opt/mpt-factory/data/factory.db`)

**Owns:**
- Jobs (id, niche, topic, provider, status, mpt_task_id, script, terms, error, timestamps)
- Assets (id, job_id, filename, path, size_bytes, created_at, deleted_at)
- Job history (all terminal states preserved)

**Does NOT own:**
- Temporary MPT processing files
- MPT task state (transient)
- Video cache (MPT owns cache_videos/)

### 7.2 MPT Storage (`/opt/MoneyPrinterTurbo/storage/`)

**Owns:**
- Per-task artifacts (`tasks/{task_id}/final-*.mp4`, `combined-*.mp4`, etc.)
- Material cache (`cache_videos/`)
- BGM uploads (`bgm/`)
- Local video materials (`local_videos/`)

**Does NOT own:**
- Job metadata (Factory owns this)
- Permanent asset records (Factory owns this)

### 7.3 Boundary Rule

**Factory assets are permanent. MPT artifacts are ephemeral.**

When MPT completes a task, Factory downloads the finished video to its own storage (`/opt/mpt-factory/data/videos/`) and records it as an asset. MPT's copy is considered cache and may be cleaned up by Phase 10 sweeper rules.

---

## 8. ARTIFACT OWNERSHIP

| Artifact | Owner | Location | Lifetime |
|---|---|---|---|
| Source footage | MPT | `storage/cache_videos/` | Cache (sweeper-safe) |
| Temporary downloads | MPT | `storage/cache_videos/` | Cache (sweeper-safe) |
| Rendered MP4 | MPT | `storage/tasks/{id}/final-*.mp4` | Ephemeral (transferred to Factory) |
| Final MP4 | **FACTORY** | `data/videos/{id}/` | **PERMANENT** |
| Subtitles | MPT | `storage/tasks/{id}/subtitle.srt` | Ephemeral |
| Audio | MPT | `storage/tasks/{id}/audio.mp3` | Ephemeral |
| Script | **FACTORY** | `factory.db.jobs.script` | **PERMANENT** |
| Thumbnail | MPT generates, **FACTORY stores** | `data/videos/{id}/thumbnail-*.jpg` | **PERMANENT** |
| Cache | MPT | `storage/cache_videos/` | Sweeper-safe |
| Metadata | **FACTORY** | `factory.db` | **PERMANENT** |

---

## 9. YOUTUBE ARCHITECTURE

### 9.1 Flow

```
Factory UI (user selects YouTube)
  → Factory BatchPlanner (records provider="youtube")
    → Factory JobWorker.run_job()
      → MPTClient.create_video(source="youtube", terms="...")
        → MPT POST /api/v1/videos
          → material.search_videos_youtube()
          → material.save_video_youtube() (yt-dlp)
          → quality gate (Phase 10F)
          → format selector (Phase 10H.2)
          → cache identity (Phase 10H.1)
          → reframe (Phase 10)
          → final MP4
      ← MPT returns task_id
    ← Factory polls MPT for completion
  ← Factory downloads finished video to permanent storage
```

### 9.2 Key Integration Points

| Step | Owner | Evidence |
|---|---|---|
| YouTube provider selection | Factory UI | `index.html` (needs YouTube checkbox) |
| YouTube search terms | Factory UI | New input field when YouTube selected |
| YouTube download engine | MPT | `material.py:623-720` |
| Quality gate | MPT | `material.py:1182-1242` |
| Format selector | MPT | `material.py:1451-1457` |
| Cache identity | MPT | `material.py:1282+` |

---

## 10. THUMBNAIL ARCHITECTURE

### 10.1 Flow

```
MPT video generation completes
  → task._generate_task_thumbnails()
    → video._extract_thumbnail_frame() (FFmpeg)
    → thumbnail-{index}.jpg in task directory
  → API response includes thumbnails: ["/tasks/{id}/thumbnail-1.jpg"]
Factory receives task completion
  → Downloads thumbnail from MPT
  → Stores in Factory asset directory
  → Serves via Factory gallery API
```

### 10.2 Ownership

| Phase | Owner |
|---|---|
| Generation | MPT (Phase 11D) |
| Storage | Factory (permanent) |
| Serving | Factory (gallery API) |
| Fallback | Factory (placeholder if missing) |

---

## 11. BATCH ARCHITECTURE

### 11.1 Flow

```
User: Factory → New Batch → niche + count + providers
  → POST /api/batches
    → BatchPlanner.create_batch()
      → TopicPlanner.generate_topics() (calls MPT /api/v1/scripts)
      → For each topic:
        → JobStore.create_job()
        → QueueRunner.enqueue()
      → Returns job_ids
ProductionRunner (background)
  → Dequeues jobs
  → JobWorker.run_job()
    → MPTClient.create_video()
    → Polls MPT until complete
    → Downloads video to Factory storage
    → Updates job status
```

### 11.2 Concurrency

- Factory `ProductionRunner` processes jobs sequentially or with limited concurrency
- MPT handles up to 5 concurrent tasks (API) or 1 (WebUI)
- Factory should respect MPT's concurrency limits

### 11.3 Failure Isolation

- Each job is independent
- One job failure does NOT stop the batch
- Failed jobs are recorded with error details
- Batch is "complete" when all jobs are terminal (completed/failed/cancelled)

---

## 12. TOPIC / OPPORTUNITY ARCHITECTURE

### 12.1 Current State

Factory's `TopicPlanner` generates topics by:
1. Checking curated templates (offline, deterministic)
2. Calling MPT's `/api/v1/scripts` endpoint with a steering prompt
3. Parsing the response into concrete topic titles

### 12.2 Future Evolution

```
Trend/Opportunity Engine (future)
  → Generates niches + topics
  → Factory BatchPlanner consumes topics
  → MPT renders videos
```

### 12.3 Placement Decision

**Topic generation belongs to Factory (or a future Opportunity Engine), NOT MPT.**

Reasoning:
- Topic generation is strategic intelligence, not video rendering
- Future Opportunity Engine will use trends, analytics, monetization data
- MPT should remain a pure rendering engine
- Factory is the control plane that orchestrates work

---

## 13. AUTO CLIPPER COMPATIBILITY

### 13.1 Future Flow

```
Source video (long-form)
  → Auto Clipper service
    → Transcription (MPT Whisper)
    → Scene detection (new)
    → Highlight scoring (new)
    → Clip selection (new)
    → 9:16 reframe (MPT existing)
    → Captions (MPT existing)
    → Thumbnail (MPT existing)
  → Multiple short videos
  → Factory batch of clips
```

### 13.2 Placement

| Component | Owner |
|---|---|
| Auto Clipper orchestration | **FACTORY** (new module) |
| Transcription | MPT (existing Whisper) |
| Scene detection | New service or MPT |
| Highlight scoring | New service or Factory |
| Clip selection | Factory |
| Reframe | MPT (existing) |
| Captions | MPT (existing) |
| Thumbnail | MPT (existing) |

---

## 14. PUBLISHING COMPATIBILITY

### 14.1 Future Flow

```
Factory (completed video)
  → Publisher module (new)
    → Upload-Post API (MPT existing)
    → TikTok / Instagram / YouTube Shorts
  → Platform metrics (future)
  → Factory analytics
```

### 14.2 Placement

| Component | Owner |
|---|---|
| Publishing workflow | **FACTORY** |
| Platform integration | MPT (Upload-Post) |
| Publishing metadata | Factory |
| Schedule/queue | Factory |

---

## 15. ANALYTICS COMPATIBILITY

### 15.1 Future Flow

```
Publisher → platform metrics
  → Factory analytics dashboard
    → Winner detection
    → New batch decisions
    → Opportunity Engine
```

### 15.2 Placement

| Component | Owner |
|---|---|
| Analytics dashboard | **FACTORY** |
| Metrics storage | Factory DB |
| Winner detection | Factory |
| Opportunity Engine | Factory (future) |

---

## 16. DUPLICATION ANALYSIS

| Subsystem | Current State | Action |
|---|---|---|
| Job creation | Factory only | KEEP FACTORY |
| Task execution | MPT only | KEEP MPT |
| Video storage | **DUPLICATED** (MPT tasks + Factory assets) | Factory owns permanent, MPT owns temp |
| Provider selection | **DIVERGED** (Factory 3, MPT 7) | Add YouTube to Factory |
| Batch orchestration | Factory only | KEEP FACTORY |
| History | Factory only (MPT loses on restart) | KEEP FACTORY |
| Cleanup | MPT only | KEEP MPT |
| Thumbnail | MPT generates, Factory doesn't display | ADD Factory display |
| User UI | **DUPLICATED** (Factory + MPT Streamlit) | Factory = primary, MPT = admin |

---

## 17. DEPLOYMENT ARCHITECTURE

### 17.1 Current Deployment

```
nginx (goldtrader.website:80/443)
  → Factory (127.0.0.1:8000) [NOT CONFIGURED IN NGINX]
  → MPT WebUI (127.0.0.1:8501) [CONFIGURED IN NGINX]

Docker:
  - moneyprinterturbo-webui (mpt-factory-11e, port 8501)
  - moneyprinterturbo-api (mpt-factory-11e, port 8080)

Native:
  - uvicorn Factory (pid 180209, port 8000)
```

### 17.2 Target Deployment

```
nginx (goldtrader.website:80/443)
  → Factory (port 8000) [PRIMARY]
  → MPT API (port 8080) [INTERNAL ONLY]

Docker:
  - mpt-api (port 8080, internal)
  - mpt-webui (port 8501, admin only, optional public)

Native or Docker:
  - Factory (port 8000, primary UI)
```

### 17.3 Minimum Containers

| Service | Container | Port | Public |
|---|---|---|---|
| Factory | Docker (future) | 8000 | YES |
| MPT API | Docker | 8080 | NO (internal) |
| MPT WebUI | Docker | 8501 | OPTIONAL |

---

## 18. SECURITY BOUNDARIES

### 18.1 Public Surface

| Endpoint | Auth | Purpose |
|---|---|---|
| Factory UI (port 8000) | Future: user auth | Primary user interface |
| Factory API | Future: user auth | Programmatic access |

### 18.2 Internal Surface

| Endpoint | Auth | Purpose |
|---|---|---|
| MPT API (port 8080) | API key | Factory → MPT communication |
| MPT WebUI (port 8501) | API key | Admin/debug interface |

### 18.3 Secret Ownership

| Secret | Owner | Storage |
|---|---|---|
| MPT API keys | MPT | config.toml |
| Factory DB encryption | Factory | Future |
| Publishing credentials | Factory | Future |
| LLM API keys | MPT | config.toml |

### 18.4 Database Access

| Database | Owner | Access |
|---|---|---|
| factory.db | Factory | Factory process only |
| MPT state | MPT | MPT process only |

---

## 19. MIGRATION STRATEGY

### 19.1 Phase 1: Backup (Non-Destructive)

1. Back up `/opt/mpt-factory/` source code
2. Back up `/opt/mpt-factory/data/factory.db`
3. Back up `/opt/mpt-factory/data/videos/`
4. Initialize git repo in `/opt/mpt-factory/`

### 19.2 Phase 2: Factory Stabilization

1. Fix topic generation (transient issue)
2. Add YouTube to provider list
3. Add thumbnail display
4. Add mobile CSS breakpoints

### 19.3 Phase 3: Contract Hardening

1. Formalize Factory → MPT API contract
2. Add error handling and retry logic
3. Add idempotency guarantees

### 19.4 Phase 4: Engine Integration

1. Ensure MPT API is stable for Factory use
2. Add health checks
3. Add monitoring

### 19.5 Phase 5: Future Features

1. Auto Clipper
2. Publishing
3. Analytics
4. Opportunity Engine

---

## 20. FINAL ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────┐
│                        USERS                                 │
│                          ↓                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ FACTORY (Canonical User Control Plane)                │   │
│  │  - User UI (port 8000)                               │   │
│  │  - Job/Batch orchestration                           │   │
│  │  - Topic generation                                  │   │
│  │  - Asset management                                  │   │
│  │  - Video library                                     │   │
│  │  - Publishing workflow (future)                      │   │
│  │  - Analytics (future)                                │   │
│  │  - Opportunity Engine (future)                       │   │
│  │  - Database: factory.db (permanent)                  │   │
│  └───────────────────────┬──────────────────────────────┘   │
│                          │ API calls                        │
│  ┌───────────────────────↓──────────────────────────────┐   │
│  │ MPT ENGINE (Video Generation Engine)                 │   │
│  │  - Video rendering pipeline                          │   │
│  │  - Material sourcing (6 providers + YouTube)          │   │
│  │  - Quality gate                                       │   │
│  │  - 9:16 reframe                                      │   │
│  │  - TTS (9 providers)                                 │   │
│  │  - Subtitle generation                               │   │
│  │  - Thumbnail generation                              │   │
│  │  - Publishing integration (Upload-Post)               │   │
│  │  - API: port 8080 (internal)                         │   │
│  │  - WebUI: port 8501 (admin only)                     │   │
│  │  - State: in-memory/Redis (ephemeral)                │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ ARTIFACTS                                             │   │
│  │  Factory: data/videos/{id}/ (permanent)               │   │
│  │  MPT: storage/tasks/{id}/ (ephemeral)                 │   │
│  │  MPT: storage/cache_videos/ (sweeper-safe)            │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 21. IMPLEMENTATION SEQUENCE

| Phase | Description | Owner | Dependencies |
|---|---|---|---|
| 11H.1 | Factory source backup + git init | Human | None |
| 11H.2 | Factory topic generation repair | Factory | MPT API stable |
| 11H.3 | Factory YouTube integration | Factory | 11H.2 |
| 11H.4 | Factory thumbnail display | Factory | MPT thumbnails |
| 11H.5 | Factory → MPT contract hardening | Both | 11H.3 |
| 11H.6 | Mobile CSS for Factory | Factory | 11H.3 |
| 11H.7 | Production stability validation | Both | All above |

---

## 22. TEST STRATEGY

### 22.1 Test Levels

| Level | What | How |
|---|---|---|
| SOURCE VERIFIED | Code exists, parses, unit tests pass | Static analysis, pytest |
| RUNTIME VERIFIED | Running container serves correct code | Docker inspect, file hash comparison |
| REAL E2E VERIFIED | Complete flow works end-to-end | Integration test with real MPT |

### 22.2 Required Tests

| Test | Level | Purpose |
|---|---|---|
| Factory YouTube provider appears in UI | SOURCE + RUNTIME | HTML contains YouTube checkbox |
| Factory batch with YouTube creates MPT task | REAL E2E | Job created, MPT task created |
| MPT YouTube download succeeds | REAL E2E | Video material downloaded |
| Quality gate rejects low-res YouTube | REAL E2E | Phase 10F gate enforced |
| Thumbnail generated and served | REAL E2E | Thumbnail in Factory gallery |
| Batch partial failure isolation | REAL E2E | One failure doesn't stop batch |
| Job state survives Factory restart | REAL E2E | SQLite persistence |
| MPT restart doesn't lose Factory jobs | REAL E2E | Factory DB independent |
| Duplicate batch submission prevented | REAL E2E | Idempotency |
| Cancel batch stops remaining jobs | REAL E2E | Cancellation propagation |

---

## 23. RISKS

| Risk | Severity | Mitigation |
|---|---|---|
| Factory has no version control | **CRITICAL** | Initialize git immediately |
| Factory topic generation intermittent | MEDIUM | Add retry + fallback |
| MPT API instability affects Factory | MEDIUM | Health checks + circuit breaker |
| Two UIs confuse users | LOW | Document MPT as admin-only |
| Factory DB corruption | LOW | Regular backups |
| MPT cleanup deletes Factory assets | **HIGH** | Clear artifact ownership boundary |

---

## 24. FINAL RECOMMENDATION

### Architecture: LOCKED

| Role | Application | Port | Access |
|---|---|---|---|
| **Canonical User UI** | Factory | 8000 | Public |
| **Video Engine** | MPT | 8080 | Internal |
| **Admin/Debug UI** | MPT WebUI | 8501 | Optional |

### Key Principles

1. **Factory owns the user experience.** All user-facing features go in Factory.
2. **MPT owns video rendering.** All media processing goes in MPT.
3. **Factory delegates to MPT via API.** No code duplication.
4. **Factory DB is permanent.** MPT state is ephemeral.
5. **No feature is built in the wrong layer.**

### Immediate Next Steps

1. Back up Factory source and database
2. Initialize git in `/opt/mpt-factory/`
3. Fix topic generation
4. Add YouTube to Factory
5. Add thumbnail display

### DO NOT

- Delete either application
- Duplicate MPT video logic in Factory
- Duplicate Factory job logic in MPT
- Build Auto Clipper before this architecture is stable
- Proceed to Phase 11I+ without human approval

---

## PHASE 11H CLASSIFICATION

**PASS WITH FINDINGS**

Architecture is locked. Implementation sequence is defined. No coding performed.

Next: Await human approval before implementation.

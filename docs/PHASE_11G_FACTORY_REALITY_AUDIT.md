# PHASE 11G — FACTORY REALITY & STABILITY AUDIT

**Status:** FAIL — CRITICAL
**Date:** 2026-08-29
**Auditor:** Kilo (automated forensic audit)
**Baseline commit:** da2b8be (Phase 11F)

---

## 1. EXECUTIVE SUMMARY

**ROOT CAUSE FOUND:** The human has been looking at a COMPLETELY DIFFERENT APPLICATION than the one I have been modifying for 11 phases.

There are TWO separate applications deployed on this server:

1. **MoneyPrinterTurbo** (Streamlit UI, port 8501) — the application I have been modifying
2. **MPT Factory** (FastAPI + HTML dashboard, port 8000) — a SEPARATE application the human actually uses

The MPT Factory has:
- Its OWN frontend (`/opt/mpt-factory/static_dashboard/index.html`)
- Its OWN backend (`/opt/mpt-factory/app/main.py`)
- Its OWN database (`/opt/mpt-factory/data/factory.db`)
- Its OWN provider list hardcoded in HTML: **ONLY Pixabay, Pexels, Coverr**
- **NO YouTube support**
- **NO thumbnail support**
- **NO connection to my Phase 11A-11F changes**

All my Phase 11A-11F "PASS" reports were about the WRONG APPLICATION.

---

## 2. PREVIOUS CLAIMS vs VERIFIED REALITY

| Phase | Claimed | Reality |
|---|---|---|
| 11B | YouTube in UI dropdown | TRUE for MPT Streamlit, FALSE for Factory |
| 11C | YouTube first-class UX | TRUE for MPT Streamlit, FALSE for Factory |
| 11F | Batch UI with YouTube | FALSE — Factory has NO YouTube, MPT batch never tested by human |
| 11F | Thumbnails in UI | FALSE — Factory has no thumbnail support |
| 11F | Mobile UX works | FALSE — Factory has separate CSS, never audited |

**Every previous PASS claim must be re-evaluated in the context of which UI the human actually uses.**

---

## 3. UI INVENTORY

| UI | Entry Point | Port | Container | Image | Source |
|---|---|---|---|---|---|
| **MPT Original** | `webui/Main.py` (Streamlit) | 127.0.0.1:8501 | moneyprinterturbo-webui | mpt-factory-11e:latest | `/root/moneyprinterturbo-video-factory/` |
| **MPT Factory** | `app/main.py` (FastAPI) | 127.0.0.1:8000 | NATIVE PROCESS (uvicorn) | N/A | `/opt/mpt-factory/` |
| **MPT API** | `main.py` (FastAPI) | 127.0.0.1:8080 | moneyprinterturbo-api | mpt-factory-11e:latest | `/root/moneyprinterturbo-video-factory/` |
| **Legacy MPT** | `main.py` (FastAPI) | 0.0.0.0:8090 | mpt-7b-9090 | ghcr.io/harry0703/moneyprinterturbo:latest | upstream |

---

## 4. SCREENSHOT → CODE TRACE

The human screenshot shows:

```
FACTORY
Overview | Jobs | History | Videos | New Batch
Niche: [____]
Count: [____]
Providers: [x] Pixabay [x] Pexels [x] Coverr
[Queue batch]
```

**This maps to:** `/opt/mpt-factory/static_dashboard/index.html` lines 130-135:

```html
<div class="provider-list" id="provider-selector">
  <label><input type="checkbox" name="provider" value="pixabay" checked> Pixabay</label>
  <label><input type="checkbox" name="provider" value="pexels" checked> Pexels</label>
  <label><input type="checkbox" name="provider" value="coverr" checked> Coverr</label>
</div>
```

**NOT** `webui/Main.py` (which has 7 providers including YouTube).

---

## 5. ORIGINAL MPT UI TRACE

| Property | Value |
|---|---|
| Entry point | `webui/Main.py` |
| Container | moneyprinterturbo-webui |
| Port | 127.0.0.1:8501 |
| Image | mpt-factory-11e:latest (built 2026-08-29) |
| Source | `/root/moneyprinterturbo-video-factory/webui/Main.py` |
| YouTube | YES (since Phase 11B) |
| Batch UI | YES (Phase 11F, untested by human) |

---

## 6. FACTORY UI TRACE

| Property | Value |
|---|---|
| Entry point | `app/main.py` (FastAPI) |
| Process | uvicorn pid 180209 |
| Port | 127.0.0.1:8000 |
| Source | `/opt/mpt-factory/` |
| YouTube | **NO** |
| Batch UI | YES (but no YouTube) |
| Thumbnails | **NO** |

---

## 7. SOURCE/API/CONTAINER/UI MATRIX

| Feature | Source | API | Container | Actual UI | Real E2E | Status |
|---|---|---|---|---|---|---|
| YouTube (MPT) | YES | YES | mpt-factory-11e | YES (Streamlit) | NOT VERIFIED | NOT VERIFIED |
| YouTube (Factory) | NO | N/A | uvicorn:8000 | NO | NO | NOT AVAILABLE |
| Pexels | YES | YES | BOTH | YES | VERIFIED | VERIFIED |
| Pixabay | YES | YES | BOTH | YES | VERIFIED | VERIFIED |
| Coverr | YES | YES | BOTH | YES | VERIFIED | VERIFIED |
| Batch creation (MPT) | YES | YES | mpt-factory-11e | YES (code) | NOT VERIFIED | NOT VERIFIED |
| Batch creation (Factory) | YES | YES | uvicorn:8000 | YES | PARTIAL (topic gen fails) | PARTIAL |
| Batch monitoring (MPT) | YES | YES | mpt-factory-11e | YES (code) | NOT VERIFIED | NOT VERIFIED |
| Batch monitoring (Factory) | YES | YES | uvicorn:8000 | YES | VERIFIED | VERIFIED |
| Thumbnail generation (MPT) | YES | YES | mpt-factory-11e | NO (display) | NOT VERIFIED | NOT VERIFIED |
| Thumbnail display (Factory) | NO | N/A | N/A | NO | NO | NOT AVAILABLE |
| Play | YES | YES | BOTH | YES | VERIFIED | VERIFIED |
| Download | YES | YES | BOTH | YES | VERIFIED | VERIFIED |
| Delete | YES | YES | BOTH | YES | VERIFIED | VERIFIED |
| 9:16 reframe | YES | YES | MPT | YES (backend) | VERIFIED | VERIFIED |
| Quality gate 250 | YES | YES | MPT | YES (backend) | VERIFIED | VERIFIED |
| YouTube 720p | YES | YES | MPT | YES (backend) | VERIFIED | VERIFIED |
| YT cache identity | YES | YES | MPT | YES (backend) | VERIFIED | VERIFIED |
| Failure cleanup | YES | YES | MPT | YES (backend) | VERIFIED | VERIFIED |

---

## 8. BATCH FLOW

### 8.1 Factory Batch Flow (Human's Actual UI)

```
User clicks "Queue batch" (Factory HTML)
  → POST /api/batches {"niche":"...", "providers":["pixabay","pexels","coverr"]}
    → BatchPlanner.create_batch()
      → TopicPlanner.generate_topics() (calls MPT POST /api/v1/scripts)
      → For each topic:
        → JobWorker.run_job()
          → MPTClient.create_video() (calls MPT POST /api/v1/videos)
          → Polls MPT GET /api/v1/tasks/{id}
          → AssetLibrary.download_asset() (downloads finished MP4)
          → VideoValidator.validate()
      → Returns job_ids
```

### 8.2 Verdict

- **Functional:** YES (43 completed jobs in database)
- **YouTube capable:** NO (provider list hardcoded, no YouTube in UI)
- **Failure isolation:** YES (per-job status tracking)
- **State persistence:** YES (SQLite database survives restart)
- **Browser refresh safe:** YES (state in DB + API)
- **Container restart safe:** YES (data in /opt/mpt-factory/data/)

### 8.3 Known Issue

```json
{"status":"error","message":"Queue gagal: topic generation tidak berhasil."}
```

Topic generation currently fails. This may be an MPT API issue (the topic planner calls MPT's `/api/v1/scripts` endpoint).

---

## 9. THUMBNAIL FLOW

### 9.1 MPT Thumbnail Flow (Phase 11D)

```
Video COMPLETE → _generate_task_thumbnails() → FFmpeg frame extraction
  → thumbnail-{index}.jpg in task directory
  → API response: thumbnails: ["/tasks/{id}/thumbnail-1.jpg"]
  → UI: st.image(thumbnails[i]) above video player
```

**Status:** Backend works, UI code exists but never tested by human.

### 9.2 Factory Thumbnail Flow

**Does not exist.** Factory has no thumbnail generation or display.

---

## 10. YOUTUBE FLOW

### 10.1 MPT YouTube Flow

```
User selects YouTube → video_source="youtube"
  → download_videos() → search_videos_youtube()
  → save_video_youtube() (yt-dlp)
  → quality gate (Phase 10F)
  → format selector (Phase 10H.2)
  → cache identity (Phase 10H.1)
```

**Status:** Fully implemented in MPT (Phase 10H + 11B/11C).

### 10.2 Factory YouTube Flow

**Does not exist.** Factory's provider list is hardcoded in HTML without YouTube.

---

## 11. DEPLOYMENT VERSION AUDIT

### 11.1 Git HEAD vs Running Containers

| Component | Git HEAD | Image | Container | Match? |
|---|---|---|---|---|
| MPT Streamlit | da2b8be | mpt-factory-11e (0229057121d9) | moneyprinterturbo-webui | YES |
| MPT API | da2b8be | mpt-factory-11e (0229057121d9) | moneyprinterturbo-api | YES |
| Factory | N/A (separate repo) | N/A (native uvicorn) | pid 180209 | N/A |

### 11.2 Factory Deployment

| Property | Value |
|---|---|
| Source location | `/opt/mpt-factory/` |
| Git repo | Unknown (no .git directory found) |
| Deployed | Aug 24 02:48 (5+ days ago) |
| Process | uvicorn pid 180209 |
| Restart policy | systemd or manual |
| Last code change | Aug 27 16:46 (.pytest_cache) |

---

## 12. API CONTRACT AUDIT

### 12.1 Factory API Endpoints

| Method | Path | Purpose | Status |
|---|---|---|---|
| GET | /health | Health check | WORKING |
| POST | /api/batches | Create batch | PARTIAL (topic gen fails) |
| GET | /api/jobs | List jobs | WORKING |
| GET | /api/production/status | Production status | WORKING |
| POST | /api/production/start | Start runner | WORKING |
| POST | /api/production/stop | Stop runner | WORKING |
| GET | /api/videos | List videos | WORKING |
| GET | /api/videos/{id}/file | Download video | WORKING |
| DELETE | /api/videos/{id}/file | Delete video | WORKING |

### 12.2 Factory → MPT Integration

| Call | Endpoint | Status |
|---|---|---|
| generate_script() | POST /api/v1/scripts | FAILING (topic gen error) |
| create_video() | POST /api/v1/videos | WORKING (past data) |
| get_task() | GET /api/v1/tasks/{id} | WORKING |

---

## 13. MOBILE UX AUDIT

### 13.1 Factory Mobile CSS

The Factory has its own CSS at `/opt/mpt-factory/static_dashboard/app.css`. Key observations:

- `provider-list` uses `display: inline-flex; gap: 8px; flex-wrap: wrap` — wraps on mobile
- Cards layout not explicitly responsive
- No `@media` queries found in app.css for mobile breakpoints
- Touch targets: `padding: 8px 12px` on provider labels — adequate

### 13.2 Verdict

Factory mobile UX is **not optimized** but may be usable due to flex-wrap.

---

## 14. STABILITY THREAT MODEL

### P0 (Critical)

| Threat | Evidence |
|---|---|
| **Data loss** | Factory shares conceptually with MPT but uses separate DB. No cross-deletion risk. |
| **Topic generation failure** | Factory's batch creation currently fails: "topic generation tidak berhasil" |
| **Job stuck in running** | If Factory process restarts mid-job, jobs may stay "running" forever. No heartbeat timeout found. |

### P1 (High)

| Threat | Evidence |
|---|---|
| **Factory has no YouTube** | Provider list hardcoded without YouTube |
| **Factory has no thumbnails** | No thumbnail generation or display |
| **Factory topic gen fails** | Cannot create new batches |
| **MPT batch UI untested** | Phase 11F batch UI was never tested by human |

### P2 (Medium)

| Threat | Evidence |
|---|---|
| **Two UIs diverge** | MPT and Factory have different features |
| **Factory not in Docker** | Native process, no container isolation |
| **No Factory CI/CD** | No git history, no automated deployment |

### INFO

| Observation | Impact |
|---|---|
| Factory has 26 test files, 203 passing tests | Well-tested codebase |
| Factory has its own job store | Separate from MPT task system |
| Factory uses MPT as rendering engine | Correct architecture |

---

## 15. FACTORY vs ORIGINAL UI DECISION

### Option A — KEEP FACTORY UI

**Pros:**
- Factory has its own job management, batch queue, video library
- Factory has 203 passing tests
- Factory is actually functional (43 completed videos)
- Factory has better information architecture (tabs: Overview/Jobs/History/Videos/Batch)

**Cons:**
- No YouTube support (hardcoded provider list)
- No thumbnail support
- Topic generation currently failing
- Separate codebase to maintain
- Not connected to Phase 11 improvements

### Option B — SIMPLIFY FACTORY

Keep Factory but:
- Add YouTube to provider list
- Add thumbnail display
- Fix topic generation
- Integrate Phase 11 improvements

### Option C — REMOVE FACTORY UI

Use MPT Original UI as canonical frontend.

**Pros:**
- Single codebase to maintain
- All Phase 11 improvements already implemented
- YouTube already works

**Cons:**
- Loses Factory's job management features
- Loses Factory's information architecture
- Streamlit is less flexible than custom HTML

---

## 16. EVIDENCE

### 16.1 Factory Provider List (HTML)

File: `/opt/mpt-factory/static_dashboard/index.html:133-135`
```html
<label><input type="checkbox" name="provider" value="pixabay" checked> Pixabay</label>
<label><input type="checkbox" name="provider" value="pexels" checked> Pexels</label>
<label><input type="checkbox" name="provider" value="coverr" checked> Coverr</label>
```

### 16.2 Factory Process

```
root  180209  uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 16.3 Factory Database

```
/opt/mpt-factory/data/factory.db
SHA256: ad0e6df9d5a45438532c0c99655455448e8c791bd5781711bf1f4f111a5d59a1
Size: 151552 bytes
Jobs: 171 (43 completed, 29 failed, 90 cancelled, 9 queued)
Providers: pixabay (120), pexels (27), coverr (24)
Assets: 43 videos
```

### 16.4 Factory Batch Failure

```bash
$ curl -X POST http://127.0.0.1:8000/api/batches \
    -H "Content-Type: application/json" \
    -d '{"niche":"test","count":1,"providers":["pexels"]}'
{"status":"error","message":"Queue gagal: topic generation tidak berhasil.",
 "reason":"topic generation failed","rate_limited":false}
```

### 16.5 MPT Provider List (Python)

File: `/root/moneyprinterturbo-video-factory/webui/Main.py:3662-3669`
```python
video_sources = [
    (tr("Pexels"), "pexels"),
    (tr("Pixabay"), "pixabay"),
    (tr("Coverr"), "coverr"),
    (tr("YouTube"), "youtube"),
    (tr("WaveSpeed AI Video"), "wavespeed"),
    (tr("Shengsuan Cloud AI Video"), "loomloom"),
    (tr("Local file"), "local"),
]
```

---

## 17. PRODUCTION SAFETY

### 17.1 Invariants (Audit Only — No Changes)

| Invariant | Value |
|---|---|
| Factory DB SHA256 | ad0e6df9d5a45438532c0c99655455448e8c791bd5781711bf1f4f111a5d59a1 |
| Factory DB size | 151552 |
| MPT DB SHA256 | ad0e6df9d5a45438532c0c99655455448e8c791bd5781711bf1f4f111a5d59a1 |
| MPT config.toml SHA | 2a8d89a696ff5564703547e86c198d846370399de3ae3a5e105c0784d26c7f45 |
| Factory jobs | 171 |
| Factory assets | 43 |
| MPT tasks | 136 |
| MPT MP4s | 158 |

### 17.2 Audit Actions

- Production jobs: 0
- YouTube downloads: 0
- Production E2E: 0
- Database mutation: NO
- Config mutation: NO
- Source modification: NO

---

## 18. LIMITATIONS

1. Factory repository has no `.git` directory — version history unknown
2. Topic generation failure not root-caused (may be MPT API issue or Gemini quota)
3. Factory mobile CSS not fully audited (no responsive breakpoints found)
4. Factory test coverage for batch creation with YouTube: N/A (no YouTube support)
5. MPT batch UI (Phase 11F) never tested by human

---

## 19. RECOMMENDATION

### OPTION B — SIMPLIFY FACTORY (RECOMMENDED)

**Rationale:**
1. Factory is the human's actual UI — removing it would disrupt workflow
2. Factory has better information architecture than MPT Streamlit
3. Factory already works (43 completed videos, 203 passing tests)
4. Adding YouTube + thumbnails is a small change
5. Fixing topic generation unblocks batch creation

**Required Changes to Factory:**
1. Add YouTube checkbox to `static_dashboard/index.html`
2. Add YouTube search terms input (when YouTube selected)
3. Add thumbnail display in video cards
4. Fix topic generation (debug MPT API call)
5. Add responsive mobile CSS

**DO NOT proceed to Phase 11G (Auto Clipper) until this is resolved.**

---

## 20. NEXT PHASE

**Phase 11G (Auto Clipper) should NOT proceed.**

The immediate next step should be:
1. Fix Factory to support YouTube (the human's actual UI)
2. Fix Factory topic generation
3. Add Factory thumbnail support
4. Verify Factory batch creation end-to-end
5. THEN consider Auto Clipper architecture

---

## PHASE 11G CLASSIFICATION

**FAIL — CRITICAL**

Previous Phase 11A-11F reports were about the wrong application.
The human uses MPT Factory (port 8000), not MPT Streamlit (port 8501).
MPT Factory lacks YouTube, thumbnails, and working batch creation.

**Root cause:** Two separate applications exist. All Phase 11 modifications were made to MoneyPrinterTurbo (the wrong app). The Factory app at `/opt/mpt-factory/` is a completely separate codebase with its own frontend, backend, database, and provider list.

**Production mutations:** 0
**Source modifications during audit:** 0
**Deployment:** NONE

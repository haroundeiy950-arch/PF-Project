# Sentinel AI — AI Smart Security Camera System

A complete, working perimeter-protection platform: AI threat detection, transparent
risk scoring, false-alarm verification, a full alarm/emergency chain, bilingual
English/Arabic voice warnings, evidence recording, playback, reports, and a dark
"perimeter control center" web console.

By default the project runs in **live security camera mode**: a physical webcam
is opened directly (DirectShow first on Windows, then MSMF), its picture is
streamed to the dashboard immediately, and disconnected devices are retried
automatically. No synthetic video or demo history is used.

A real security camera also preserves everything, not just alarms. Continuous
MP4 segments are written to `storage/clips/continuous`, while ordinary
motion/person/vehicle events get JPEG snapshots and verified incidents get a
snapshot plus a short pre/post-event clip in `storage/snapshots` and
`storage/clips`. Set `CONTINUOUS_RECORDING_ENABLED=false` and
`EVIDENCE_ENABLED=false` only if you explicitly want a live-only view with
nothing saved.

- **Backend:** Python 3.11 · FastAPI · SQLAlchemy 2 · SQLite (PostgreSQL-compatible)
- **Frontend:** React 18 · TypeScript · Vite · custom dark CSS · MJPEG · WebSockets
- **AI:** OpenCV demo renderer + motion detector by default; optional YOLOv8 + InsightFace
- **Security:** PBKDF2-HMAC-SHA256 passwords, HS256 JWTs, 12-permission role matrix, audit log

---

## Quick start (Windows)

Prerequisite: **Python 3.11+** and **Node.js 18+** (npm included).

```powershell
cd "C:\Users\user\OneDrive\Attachments\Desktop\PF project"
.\run.ps1 -Setup
```

`-Setup` creates `.venv`, installs the Python and npm dependencies, compiles the
dashboard, then starts the combined server. Open **http://127.0.0.1:8000/** —
the **Live security camera** panel at the top of the dashboard shows your real
camera immediately. If the sensor is blank, click **Find live camera** in that
panel (or **Devices → Auto-detect live camera**) to switch to the first device
that actually produces an image. Continuous segments appear in **Playback** as
they are finalised. Use **Audit files** or **Repair files** in that page to verify
that every archive entry points to a valid, decodable file.

On later runs just start it again:

```powershell
.\run.ps1
```

Rebuild only the UI after editing TypeScript/CSS:

```powershell
.\run.ps1 -Build
```

### Manual start (any OS)

```bash
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
npm run build
cd ..

python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Then browse to `http://127.0.0.1:8000/`. The API documentation is at
`http://127.0.0.1:8000/docs`.

### Development mode (hot reload)

Terminal 1 — API:

```bash
python -m uvicorn backend.main:app --reload --port 8000
```

Terminal 2 — Vite dev server (proxies `/api`, `/media` and WebSockets to port 8000):

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173/`.

---

## Demo accounts

The database is seeded on first start. **Change these accounts and `SECRET_KEY`
before using the system for anything real.**

| Username | Password | Role | Access |
| -------- | -------- | ---- | ------ |
| `admin` | `admin123` | Administrator | Everything, including users, settings and audit |
| `operator` | `operator123` | Security Operator | Live view, alarms, incidents, reports, exports |
| `viewer` | `viewer123` | Viewer | Read-only live view and recordings |

In live mode the only seeded camera is `CAM-01` Live Security Camera, pointed at
the local webcam. Demo cameras and synthetic incidents appear only when live mode
is disabled.

---

## Live camera mode (default)

`.env` is preconfigured for direct monitoring:

| Setting | Value | Effect |
| ------- | ----- | ------ |
| `LIVE_ONLY` | `true` | Real webcam source; hide inactive camera inputs; no synthetic scenes/demo incidents |
| `EVIDENCE_ENABLED` | `true` | Run the detector/recorder worker so real events save evidence |
| `LIVE_CAMERA_INDEX` | `0` | Preferred webcam index; startup probes and can replace it if blank |
| `WEBCAM_BACKEND` | `auto` | DirectShow first on Windows, then MSMF; `dshow`/`msmf` force one |
| `WEBCAM_SWITCH_SECONDS` | `6` | How long a blank/frozen device is tried before another is opened |
| `DEMO_MODE` / `DEMO_AUTOTRIGGER` | `false` | Synthetic scenes and fake alarms are off |
| `RECORDING_ENABLED` | `true` | Write a short MP4 clip for each verified incident |
| `CONTINUOUS_RECORDING_ENABLED` | `true` | Write non-stop segmented video for every camera |
| `CONTINUOUS_SEGMENT_SECONDS` | `300` | Length of each continuous MP4 segment |
| `SAVE_MOTION_SNAPSHOTS` | `true` | JPEG for ordinary motion/person/vehicle events |
| `SEED_DEMO_DATA` | `false` | Database starts with accounts, one real camera and one monitoring zone |

The dashboard opens on the live picture. The worker keeps retrying if the device
drops, and a connected-but-black sensor is shown as `NO IMAGE FROM DEVICE` while
the stream stays open for instant recovery. **Devices → Live camera devices**
shows every webcam that currently produces an image, with its backend and signal
state. In `LIVE_ONLY=true` mode, inactive inputs are hidden and the panel subtitle
reports how many were hidden; **Auto-detect live camera** selects only live
devices and restarts the stream. Set `LIVE_ONLY=false` to show all inputs for
troubleshooting.

Recording is layered:

- `storage/clips/continuous` — every streamed frame, in 5-minute MP4 segments.
- `storage/snapshots` — JPEG for normal events plus one for each verified incident.
- `storage/clips` — annotated pre/post-event MP4 for each verified incident.

All three types are listed in **Playback**, filterable by camera and file type,
and pruned by `RETENTION_DAYS`. Snapshot rows display **Still image** rather than
`0s`. The current continuous segment is still being written, so it is expected
until it is finalised. **Audit files** checks every database reference and media
folder without changing anything (`POST /api/recordings/audit`); **Repair files**
also removes invalid or orphaned files (requires `delete_recordings`,
`POST /api/recordings/audit?repair=true`). Use
`CONTINUOUS_RECORDING_ENABLED=false` and/or `EVIDENCE_ENABLED=false` to disable
the corresponding layers.

If your camera shows `NO IMAGE FROM DEVICE`, it is connected but producing a
blank image (disabled device, privacy shutter, driver error or a virtual
camera). Check **Device Manager → Cameras**, allow *Camera access* and *Let
desktop apps access your camera* in Windows privacy settings, close apps that
reserve it, then rescan or auto-detect.

---

## The ten core modules

| # | Module | Implementation | Where in the UI |
| - | ------ | -------------- | --------------- |
| 1 | Camera & device management | `backend/routers/cameras.py`, `backend/ai/supervisor.py` | Devices |
| 2 | Live AI detection & tracking | `backend/ai/source.py`, `demo.py`, `detector.py`, `tracker.py`, `pipeline.py` | Dashboard, Threat Screen |
| 3 | Risk scoring engine | `backend/services/risk.py` | Threat Screen, Automations |
| 4 | Event verification (anti-false-alarm) | `backend/services/verification.py`, `backend/services/zones.py` | Threat Screen |
| 5 | Alarm & emergency chain | `backend/services/alarm.py`, `siren.py`, `notifications.py` | Alerts |
| 6 | Bilingual voice warnings | `backend/services/voice.py` + browser `SpeechSynthesis` | Threat Screen, Alerts |
| 7 | Continuous + event recording, snapshots & playback | `backend/ai/continuous.py`, `backend/ai/recorder.py`, `backend/routers/recordings.py` | Playback, Events |
| 8 | Real-time dashboard & WebSocket channel | `backend/routers/dashboard.py`, `backend/realtime.py` | Dashboard |
| 9 | Reports & evidence export | `backend/routers/reports.py` | Reports |
| 10 | Users, roles, permissions & audit | `backend/security.py`, `backend/routers/users.py`, `services/audit.py` | Settings |

Supporting modules: zones and polygon hit-testing (`backend/services/zones.py`),
face enrollment with encrypted embeddings (`backend/ai/face.py`,
`backend/services/crypto.py`), person/vehicle registers, automations and a
storage-retention worker.

### Screens

Dashboard (KPIs, live grid, timeline, active threats) · AI Live Threat Screen
(full-bleed video, bounding boxes, score breakdown, acknowledge/resolve) ·
Events · Alerts (voice queue and acknowledgement) · Playback · People · Vehicles ·
Automations (risk simulator) · Devices (cameras + zone editor) · Reports ·
Settings (users, role matrix, audit, retention) · Login.

---

## How a threat is processed

```
camera frame
   │
   ├─ detector (demo ground truth / YOLOv8 / MOG2 motion)
   ├─ tracker  (stable track IDs, speed and dwell)
   ├─ zone engine (polygon containment, zone type)
   ├─ face recognition (optional, encrypted embeddings)
   │
   ▼
verification ──> risk score ──> siren (optional) ──> webhook notification
   │                                                       │
   ├─ snapshot + annotated MP4 clip                        │
   ├─ incident record + alert + audit entry                │
   ├─ WebSocket push to every open console ────────────────┘
   └─ bilingual voice prompt (EN + AR) until acknowledged
```

### Verification rules (defaults)

| Rule | Default | Purpose |
| ---- | ------- | ------- |
| Consecutive frames | 6 | Ignore one-frame noise |
| Minimum dwell | 2.0 s | Ignore objects passing through |
| Zone cooldown | 90 s | Do not re-alarm the same zone repeatedly |
| Group window | 120 s | Merge related detections into one incident |
| Escalation-only | on | A higher level may break an active cooldown |

Zones can override these values; the seeded zones use a 45-second cooldown,
6 frames and 2 seconds in the verification tab.

### Risk model (weights total 100)

| Factor | Weight | Notes |
| ------ | -----: | ----- |
| Zone sensitivity | 30 | restricted > limited > public |
| Target type | 15 | vehicle > person > animal/unknown |
| Time of day | 15 | outside configured active hours |
| Dwell time | 15 | longer presence increases risk |
| Face status | 5 | unknown face adds points (capped contribution) |
| Repetition | 10 | recent similar events |
| Behavior | 10 | running, loitering, approaching |

| Score | Level |
| ----- | ----- |
| 0–29 | Normal |
| 30–59 | Medium |
| 60–84 | High |
| 85–100 | Critical |

Every incident stores the factor contributions, normalized breakdown and a
human-readable explanation, so an operator can see *why* the system alarmed.
The **Automations** page includes a live simulator for these weights.

---

## Alarm chain & voice

1. Detection is verified and scored.
2. Optional siren hook, then a remote notification/webhook (`WEBHOOK_URL`).
3. Snapshots and an annotated clip are written to `storage/`.
4. An incident + alert record and an audit entry are created.
5. The console receives `incident.created` / `alert.playing` over the WebSocket.
6. The browser speaks the warning in English and Arabic (server-authored text).
7. The operator acknowledges; who/when is stored and the repeating voice stops.
8. The incident is resolved or marked as a false alarm.

Arabic and English templates live in `backend/constants.py` (`VOICE_TEMPLATES`).
Voice output uses the voices installed in the operating system/browser; install
an Arabic text-to-speech voice to hear the Arabic warning.

---

## Roles & permissions

| Permission | Admin | Operator | Viewer |
| ---------- | :---: | :------: | :----: |
| `view_live` | ✓ | ✓ | ✓ |
| `view_recordings` | ✓ | ✓ | ✓ |
| `view_reports` | ✓ | ✓ | |
| `acknowledge_alarms` | ✓ | ✓ | |
| `manage_cameras` | ✓ | | |
| `manage_zones` | ✓ | | |
| `manage_faces` | ✓ | | |
| `manage_users` | ✓ | | |
| `manage_settings` | ✓ | | |
| `view_audit` | ✓ | | |
| `delete_recordings` | ✓ | | |
| `export_data` | ✓ | ✓ | |

Permissions are enforced **server-side** on every route (`backend/deps.py`);
the UI only hides controls as a convenience. `GET /api/roles/matrix` returns the
same matrix for the Settings page.

---

## Configuration

All settings are optional; copy `.env.example` to `.env` and edit what you need.
The database and media directories are created automatically.

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `SECRET_KEY` | dev placeholder | **Change it.** Signs JWTs and derives the face-embedding encryption key |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` | Login lifetime |
| `DATABASE_URL` | `sqlite:///./storage/sentinel.db` | Any SQLAlchemy URL, e.g. PostgreSQL |
| `STORAGE_DIR` | `./storage` | Snapshots, clips, faces, exports, logs |
| `SEED_DEMO_DATA` | `false` | Seed synthetic history (off in live mode) |
| `RESET_DATABASE` | `false` | Drop and re-seed on next start (one-shot) |
| `PIPELINE_ENABLED` | `true` | Start camera workers |
| `LIVE_ONLY` | `true` | Stream the real camera and skip all demo media/history |
| `EVIDENCE_ENABLED` | `true` | Detect real events and save snapshots/clips |
| `LIVE_CAMERA_INDEX` / `LIVE_CAMERA_NAME` / `LIVE_CAMERA_FPS` | `0` / `Live Security Camera` / `15` | Local webcam selection |
| `CAMERA_DISCOVERY_MAX_INDEX` | `5` | How many webcam indices to scan |
| `WEBCAM_BACKEND` | `auto` | `auto` (DirectShow then MSMF on Windows), `dshow` or `msmf` |
| `WEBCAM_SWITCH_SECONDS` | `6` | Retry/rotate interval for blank or frozen webcams |
| `DEMO_MODE` | `false` | Use the synthetic renderer |
| `DEMO_AUTOTRIGGER` | `false` | Generate demo incidents automatically |
| `DETECTOR_MODE` | `auto` | `demo`, `auto` (YOLO → motion fallback) or `yolo` |
| `TARGET_FPS` / `FRAME_WIDTH` / `FRAME_HEIGHT` | `15` / `960` / `540` | Capture settings |
| `YOLO_MODEL` / `YOLO_CONFIDENCE` | `yolov8n.pt` / `0.35` | Ultralytics options |
| `FACE_RECOGNITION_ENABLED` | `false` | Enable InsightFace matching |
| `RECORDING_ENABLED` | `true` | Write short MP4 clips for verified incidents |
| `PRE_EVENT_SECONDS` / `POST_EVENT_SECONDS` | `6` / `3` | Event clip window |
| `CONTINUOUS_RECORDING_ENABLED` | `true` | Write non-stop video segments to `storage/clips/continuous` |
| `CONTINUOUS_SEGMENT_SECONDS` | `300` | Rotate/archive continuous video this often |
| `SAVE_MOTION_SNAPSHOTS` | `true` | Save JPEGs for ordinary motion/person/vehicle events |
| `RETENTION_DAYS` | `14` | Storage retention |
| `VOICE_ENABLED` | `true` | Bilingual alarms |
| `VOICE_REPEAT_SECONDS` | `20` | Repeat interval until acknowledgement |
| `SIREN_ENABLED` | `false` | Local siren hook |
| `WEBHOOK_URL` | empty | Optional JSON webhook for incidents |
| `CORS_ORIGINS` | localhost:5173/8000 | Comma-separated origins |

---

## API surface

Interactive documentation: **`/docs`** (Swagger) and **`/redoc`**.

| Area | Endpoints |
| ---- | --------- |
| Auth | `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/change-password` |
| Cameras | `GET/POST /api/cameras`, `PATCH/DELETE /api/cameras/{id}`, `/stream`, `/snapshot`, `/detections`, `/restart`, `/meta`, `/discover`, `/live-device`, `/auto-device` |
| Zones | `GET/POST /api/zones`, `PATCH/DELETE /api/zones/{id}`, `/meta` |
| Events | `GET /api/events`, `/events/{id}`, `/events/stats` |
| Incidents | `GET /api/incidents`, `/active`, `/summary`, `/{id}`, `/{id}/events`, `/{id}/acknowledge`, `/{id}/resolve`, `/{id}/false-alarm` |
| Alerts | `GET /api/alerts`, `/pending`, `/templates`, `/{id}/play`, `/stop`, `/resend`, `/acknowledge` |
| Dashboard | `GET /api/dashboard`, `/dashboard/health`, `/dashboard/timeline` |
| People / vehicles | `GET/POST /api/persons`, `PATCH/DELETE /api/persons/{id}`, `/reenroll`, `/photo` |
| Recordings | `GET /api/recordings`, `/{id}`, `/stats`, `POST /api/recordings/snapshot/{id}`, `POST /api/recordings/audit?repair={bool}` |
| Reports | `GET /api/reports/overview`, `/incidents.csv`, `/events.csv`, `/export` |
| Settings | `GET/PUT /api/settings`, `/settings/risk`, `POST /settings/risk/preview`, `POST /settings/retention/run` |
| Users & roles | `GET/POST /api/users`, `DELETE /api/users/{id}`, `/roles`, `/roles/matrix`, `/audit-logs`, `/audit-logs/actions` |
| System | `GET /api/system/info`, `/health`, `/levels`, `/ping` |
| Realtime | `WS /api/ws?token=...` |

Media is mounted read-only over HTTP at `/media/{snapshots,clips,faces,exports}`.
The SQLite database and logs are never exposed.

WebSocket topics: `incident.created`, `incident.updated`, `incident.acknowledged`,
`incident.resolved`, `event.created`, `alert.updated`, `alert.playing`,
`camera.status`, `health.updated`, `stats.refresh`.

---

## Project layout

```
PF project/
├─ backend/
│  ├─ main.py                 FastAPI app, lifespan, SPA + media mounts
│  ├─ config.py               environment-driven settings
│  ├─ database.py             engine/session/init
│  ├─ models.py               SQLAlchemy models
│  ├─ schemas.py              Pydantic request/response models
│  ├─ security.py             PBKDF2 passwords + HS256 JWTs
│  ├─ deps.py                 auth/permission dependencies
│  ├─ realtime.py             WebSocket hub
│  ├─ seed.py                 demo users, cameras, zones, history
│  ├─ serializers.py          API serializers
│  ├─ constants.py            permissions, risk weights, voice templates
│  ├─ ai/
│  │  ├─ demo.py              synthetic camera scenes
│  │  ├─ discovery.py         webcam probing, backends, live-image detection
│  │  ├─ source.py            demo / RTSP / file / webcam sources
│  │  ├─ detector.py          YOLOv8 + MOG2 motion fallback
│  │  ├─ tracker.py           track IDs, dwell, behavior
│  │  ├─ face.py              InsightFace wrapper + embeddings
│  │  ├─ pipeline.py          per-camera detect → verify → alarm loop
│  │  ├─ recorder.py          pre/post-event MP4 writer
│  │  ├─ continuous.py        non-stop segmented MP4 writer
│  │  └─ supervisor.py        worker lifecycle + system telemetry
│  ├─ routers/                auth, users, cameras, zones, events, incidents,
│  │                          alerts, dashboard, persons, recordings, reports,
│  │                          settings, system, ws
│  ├─ services/               risk, verification, alarm, voice, siren,
│  │                          notifications, storage, imaging, audit, zones
│  ├─ utils/                  geometry, logging, time helpers
│  └─ tests/                  79 pytest tests
├─ frontend/
│  ├─ src/pages/              Dashboard, ThreatScreen, Events, Alerts, Playback,
│  │                          People, Vehicles, Automations, Devices, Reports,
│  │                          Settings, Login
│  ├─ src/components/         Layout, UI primitives, icon set
│  ├─ src/context/            Auth, Realtime
│  ├─ src/hooks/              data fetching, document title
│  ├─ src/lib/                formatting, voice engine
│  ├─ src/api.ts              typed API client
│  ├─ src/types.ts            shared contracts
│  ├─ src/styles.css          dashboard theme
│  └─ dist/                   compiled bundle served by FastAPI
├─ storage/                   database + evidence (runtime, git-ignored)
├─ run.ps1                    one-command Windows launcher
├─ requirements*.txt          runtime / dev / optional AI dependencies
├─ Dockerfile                 multi-stage build (Node → Python)
├─ docker-compose.yml         single-service deployment
└─ .env.example               documented configuration template
```

---

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest backend/tests -q
```

The suite covers security primitives, the risk model, verification/cooldown
logic, the AI demo pipeline/recorder and the full REST contract, including
permission denials. Current status: **79 passing tests**.

Frontend checks:

```bash
cd frontend
npm run typecheck
npm run build
```

---

## Docker

```bash
docker compose up --build
```

Open `http://localhost:8000/`. Evidence is stored in the named volume
`sentinel-storage`, so it survives container rebuilds. Set a real `SECRET_KEY`
in the environment (or a `.env` file used by Compose) before deploying.

The image builds the frontend with Node 20 and serves the static bundle from the
Python container, so only port 8000 is exposed.

---

## Real cameras and optional AI

The local webcam works out of the box with only `requirements.txt`. On startup the
system probes each device with the available OpenCV backends and prefers one that
returns a real image, so the dashboard opens directly on the camera. Use
**Find live camera** on the dashboard or **Devices → Auto-detect live camera** at
any time; **Rescan devices** shows every index, its backend and a diagnostic note.
An RTSP camera can be used instead by setting its `source_type` to `rtsp` and
putting the stream URL in `rtsp_url`.

Evidence is active by default in live mode:

1. Keep `LIVE_ONLY=true`, `EVIDENCE_ENABLED=true` and
   `CONTINUOUS_RECORDING_ENABLED=true`. The OpenCV motion detector works with
   only `requirements.txt`; it needs no model download.
2. Continuous segments are finalised every `CONTINUOUS_SEGMENT_SECONDS`; they,
   event snapshots and incident clips all appear in **Playback**.
3. For stronger person/vehicle detection, install the optional stack with
   `pip install -r requirements-ai.txt` and use `DETECTOR_MODE=yolo` (or `auto`,
   which falls back to motion detection if Ultralytics is unavailable).
4. Optionally set `FACE_RECOGNITION_ENABLED=true` and enroll people in **People**;
   embeddings are stored encrypted with a key derived from `SECRET_KEY`.
5. Set `CONTINUOUS_RECORDING_ENABLED=false` and `EVIDENCE_ENABLED=false` only for
   a pure live view with no saved files.

---

## Privacy & security notes

- Enrolled face embeddings are encrypted at rest with Fernet (AES-128-CBC +
  HMAC) using a key derived from `SECRET_KEY`; the plaintext embedding is never
  stored.
- The person register records a consent flag and an enrollment timestamp.
- Every privileged action is written to the audit log with user, action, target
  and timestamp.
- JWTs are signed manually with HS256 and verified with constant-time comparison;
  passwords use PBKDF2-HMAC-SHA256 with 240,000 iterations and per-user salts.
- This is a self-hosted single-tenant application. Put it behind HTTPS and a
  reverse proxy if it must be reached over a network, and remove the demo users.

---

## Troubleshooting

| Symptom | Fix |
| ------- | --- |
| `frontend/dist` missing / JSON at `/` | `cd frontend; npm install; npm run build` or `.\run.ps1 -Build` |
| Port 8000 already in use | `.\run.ps1 -Port 8080` (or stop the other process) |
| Live view says `NO IMAGE FROM DEVICE` | The webcam opens but is blank. Enable it in Device Manager, allow desktop camera access, close other apps using it, then click **Find live camera** |
| Dashboard says `NO CAMERA SIGNAL` | No frames are arriving. Rescan in **Devices**, check the device status in Windows, then restart the camera worker |
| Live camera is the wrong device | In **Devices → Live camera devices**, choose the device with "Live image detected" and click **Use live**, or click **Auto-detect live camera** |
| Continuous video is missing | Confirm `CONTINUOUS_RECORDING_ENABLED=true`; segments only appear in **Playback** after `CONTINUOUS_SEGMENT_SECONDS` or a worker restart |
| No incidents appear | In live mode this means the camera is blank or no real motion has been verified; check `NO CAMERA SIGNAL` above. No demo alarms are generated |
| Voice is silent | Browser audio requires a user gesture; click the page once, and install an Arabic TTS voice for the Arabic prompt |
| WebSocket disconnects behind a proxy | Enable HTTP/1.1 upgrade and long read timeouts for `/api/ws` |
| OpenCV import/DLL error on Windows | `pip install --force-reinstall opencv-python` (or install the VC++ runtime) |
| Start from a clean database | Delete `storage/sentinel.db*` or run once with `RESET_DATABASE=true` |
| Webhook not delivered | Check `WEBHOOK_URL`, outbound connectivity and the backend log |

---

## Credits

Built from the supplied *AI Smart Security Camera System* requirements document
and the 14 reference dashboard photographs in this folder. All people, vehicles,
plates and incidents in the demo data are fictional and generated locally.

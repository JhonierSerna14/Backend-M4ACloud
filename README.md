# M4A Backend — Mis Materias, Mis Apuntes

REST API built with FastAPI for academic management. Handles authentication, subjects, notes, tasks and files. Audio files are accepted, stored and enqueued for an external worker that runs transcription and AI summarization — results are written back through internal worker endpoints.

## Features

- **JWT authentication** — register, login, access/refresh tokens
- **Materias** — academic subjects with automatic unique color assignment
- **Notas / lienzos** — class canvas: created manually or generated from audio; supports rich HTML content and image attachments
- **Tareas** — academic events (task, exam, quiz, delivery…) with priority, deadline and custom order
- **Archivos** — file attachments per subject (PDF, images, Office docs)
- **Audio intake** — validates, stores (Supabase Storage or Dropbox) and enqueues the file; a separate worker handles transcription and AI summarization
- **WebSocket notifications** — real-time processing progress per note
- **Dashboard** — single-call summary of stats, upcoming events and recent notes
- **Prometheus metrics** — `/metrics` endpoint for monitoring

## System requirements

- Python 3.10+
- PostgreSQL (or Supabase hosted Postgres)

## Project structure

```
app/
  core/
    config.py           # All settings via pydantic-settings / .env
    database.py         # SQLAlchemy engine + session helpers
    auth.py             # JWT Bearer dependencies (access + refresh)
    security.py         # bcrypt hashing and JWT creation
    logging.py          # loguru + coloredlogs setup
    metrics.py          # Prometheus metrics
    ws.py               # WebSocket connection manager (broadcast per note)
  models/
    usuario.py          # User ORM model
    materia.py          # Subject ORM model
    nota.py             # Note/canvas ORM model (+ Adjunto)
    tarea.py            # Academic event ORM model
    archivo.py          # File attachment ORM model
    enums.py            # TareaEstado, EventoTipo enums
  routes/
    auth.py             # /auth — register, login, refresh, /me
    materias.py         # /materias — CRUD + stats
    notas.py            # /notas — CRUD, adjuntos, search, PDF export
    tareas.py           # /tareas — CRUD, filters, bulk reorder
    archivos.py         # /archivos — upload, download, delete
    audio.py            # /notas/audio/upload — audio intake
    dashboard.py        # /dashboard — summary for home screen
    worker.py           # /worker — internal endpoints for local worker
    ws_notifications.py # /ws/notas/{id} — WebSocket progress feed
    uploads.py          # /uploads — adjunto image upload for rich editor
  schemas/              # Pydantic request/response models
  services/
    ai_service.py                   # Groq + Gemini with automatic fallback
    enhanced_transcription_service.py  # Faster-Whisper chunked transcription
    storage_service.py              # Local disk / Supabase Storage backend
    dropbox_audio_service.py        # Dropbox backend for large audio files
  uploads/              # Local file storage (gitignored, .gitkeep tracked)
  main.py               # FastAPI app factory, middleware, router registration
scripts/
  migrate_uploads_to_supabase.py  # One-time utility: bulk-upload local files to Supabase
run_app.py              # Local dev launcher (uvicorn --reload)
requirements-cloud.txt  # Cloud API dependencies (deploy to Render or similar)
requirements.txt        # Full dependencies including ML libs (local/dev use)
```

## Installation and setup

### 1. Clone and create virtual environment

```bash
git clone https://github.com/JhonierSerna14/Backend-M4ACloud.git
cd Backend-M4ACloud
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements-cloud.txt
```

### 3. Environment variables

Create a `.env` file in the project root:

```env
# ── Database ──────────────────────────────────────────────
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/m4a_db

# ── JWT ───────────────────────────────────────────────────
JWT_SECRET=change-me-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# ── Storage: "local" or "supabase" ────────────────────────
STORAGE_BACKEND=supabase
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
SUPABASE_STORAGE_BUCKET=m4a-files

# ── Audio storage: "storage" or "dropbox" ─────────────────
AUDIO_STORAGE_BACKEND=dropbox
DROPBOX_ACCESS_TOKEN=sl.xxx
DROPBOX_AUDIO_ROOT_PATH=/M4A-Audio-Temp

# ── AI summarization (used by the external worker via env) ─
SUMMARY_PROVIDER=gemini        # groq | gemini | disabled
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AIza...

# ── Worker secret (shared with the external worker process) ─
WORKER_SECRET_KEY=change-me-worker-secret

# ── CORS ──────────────────────────────────────────────────
BACKEND_CORS_ORIGINS=*
```

### 4. Database setup

The database schema must already exist (tables were created with Alembic during initial setup and are now managed directly in Supabase). No migration commands are needed.

### 5. Run the API locally

```bash
python run_app.py
# or directly:
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

API docs: http://localhost:8000/docs

## API reference

Interactive docs available at `/docs` (Swagger UI) and `/redoc` once the server is running.

### Authentication — `/api/v1/auth`
| Method | Path | Description |
|--------|------|-------------|
| POST | `/register` | Create account |
| POST | `/login` | Login (returns access + refresh tokens) |
| POST | `/refresh` | Rotate tokens using refresh token |
| GET | `/me` | Current user profile |

### Materias — `/api/v1/materias`
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List subjects (with note/task counters, optional search) |
| POST | `/` | Create subject (auto-assigns unique color) |
| GET | `/{id}` | Subject detail |
| PUT | `/{id}` | Update subject |
| DELETE | `/{id}` | Delete subject and all related data |

### Notas — `/api/v1/notas`
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List notes (filters: materia, text, date range, audio origin) |
| POST | `/` | Create note manually |
| GET | `/recientes` | Last 5 recently updated notes |
| GET | `/stats` | Note statistics |
| GET | `/{id}` | Note detail with attachments |
| PUT | `/{id}` | Update note |
| DELETE | `/{id}` | Delete note |
| POST | `/{id}/adjuntos` | Upload image/PDF attachment to note |
| DELETE | `/{id}/adjuntos/{adj_id}` | Remove attachment |
| GET | `/{id}/export/pdf` | Export note as PDF |

### Audio — `/api/v1/notas/audio`
| Method | Path | Description |
|--------|------|-------------|
| POST | `/upload` | Upload audio file — creates pending note, enqueues for local worker |

### Tareas — `/api/v1/tareas`
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List events (filters: materia, tipo, estado, próximas, semana) |
| POST | `/` | Create academic event |
| GET | `/pendientes` | Pending events ordered by urgency |
| GET | `/{id}` | Event detail |
| PUT | `/{id}` | Update event |
| DELETE | `/{id}` | Delete event |
| PATCH | `/reorder` | Bulk update custom order |

### Archivos — `/api/v1/archivos`
| Method | Path | Description |
|--------|------|-------------|
| POST | `/upload` | Upload file to a subject |
| GET | `/` | List files (optional filter by materia) |
| GET | `/{id}/download` | Download or redirect to signed URL |
| DELETE | `/{id}` | Delete file |

### Dashboard — `/api/v1/dashboard`
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Stats, upcoming events (7 days) and recent notes |

### Worker (internal) — `/api/v1/worker`
Authenticated with `X-Worker-Key` header.
| Method | Path | Description |
|--------|------|-------------|
| GET | `/jobs/next` | Poll for next pending transcription job |
| POST | `/jobs/{id}/progress` | Report processing progress |
| POST | `/jobs/{id}/complete` | Submit transcription result and HTML note |
| POST | `/jobs/{id}/fail` | Report processing failure |

### WebSocket — `/ws/notas/{nota_id}`
Streams real-time `{percent, message, status}` updates while the local worker processes an audio file.

### System
| Path | Description |
|------|-------------|
| `/health` | Liveness check |
| `/metrics` | Prometheus metrics |

## Technology stack

| Layer | Technology |
|-------|-----------|
| API framework | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.0 |
| Database | PostgreSQL (Supabase hosted) |
| Validation | Pydantic v2 |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| File storage | Supabase Storage / local disk |
| Audio storage | Dropbox / Supabase Storage |
| Real-time | WebSocket (starlette) |
| Logging | loguru + coloredlogs |
| Monitoring | Prometheus client |
| PDF export | WeasyPrint + Markdown |

## Utility scripts

### `scripts/migrate_uploads_to_supabase.py`

One-time script to bulk-upload all files from the local `uploads/` directory to Supabase Storage. Idempotent: skips files that already exist in the bucket. Run once when switching from `STORAGE_BACKEND=local` to `STORAGE_BACKEND=supabase`:

```bash
SUPABASE_URL=https://xxx.supabase.co \
SUPABASE_SERVICE_ROLE_KEY=eyJ... \
python scripts/migrate_uploads_to_supabase.py
```

## License

MIT
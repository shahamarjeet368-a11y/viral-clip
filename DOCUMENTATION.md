# ViralCut AI — Project Documentation

A full-stack app that takes a video (upload or YouTube/Facebook link) and
automatically produces ranked, vertical (9:16) viral-style clips with
burned-in captions, a viral score, and SEO titles/hashtags/description —
saved to history (Supabase, with local JSON fallback).

This document explains what the project is built from, how a request
flows end-to-end, and what each file does — for both frontend and
backend.

---

## 1. Tech stack

### Frontend (`frontend/`)
| Piece | What it's for |
|---|---|
| **React 19** | UI |
| **Vite** | Dev server + build tool |
| **framer-motion** | Animations (page transitions, step tracker, card tilt) |
| Plain CSS (`App.css`, `index.css`) | No CSS framework — hand-written styles using CSS custom properties (`--accent`, `--bg`, etc.) for theming, incl. a dark/light toggle |
| `fetch` (native) | All API calls, wrapped in `src/api.js` |

No router — the whole app is one page with local React state
(`viewTab` = `"create"` or `"history"`).

### Backend (`backend/`)
| Piece | What it's for |
|---|---|
| **FastAPI** + **Uvicorn** | HTTP API server |
| **ffmpeg** (external binary) | All video/audio work: trim, crop to 9:16, burn captions, apply filters, mix background music, generate thumbnails |
| **yt-dlp** | Downloads the source video when the user pastes a YouTube/Facebook URL |
| **faster-whisper** | Speech-to-text transcription (CPU, int8), used for real captions and content-aware SEO |
| **numpy** | Audio energy (RMS) analysis for picking "viral" moments |
| **Supabase** (`supabase-py`) | Optional cloud Postgres for project history; falls back to a local `storage/db.json` file if no Supabase credentials are set |
| **aiofiles** | Async file writes for uploads |

---

## 2. How a request flows end-to-end

1. User fills the form (`App.jsx`) — upload a file **or** paste a
   video URL, pick a clip duration, optionally toggle burned-in
   captions, background music, and a color filter/effects — and submits.
2. `POST /api/projects` (`main.py`) saves the upload (or just the URL)
   and immediately returns a `project_id`. The actual work happens in a
   **background thread** (`pipeline.start_project` → a
   `ThreadPoolExecutor`), so the HTTP request doesn't block.
3. The frontend polls `GET /api/projects/{id}` every 2 seconds
   (`startPolling` in `App.jsx`) and renders a step tracker
   (Fetch → Transcribe → Score → Render) driven by the project's
   `status` field.
4. Inside the background job (`pipeline._run`), in order:
   - **Fetch** — if the source is a YouTube/Facebook URL, download it
     with `yt-dlp` (skipped for direct uploads).
   - **Transcribe** — extract mono 16kHz WAV audio with ffmpeg, then
     run `faster-whisper` over it to get word-level timestamped
     transcript segments.
   - **Score** — compute RMS (loudness) energy per 0.5s window from the
     same WAV, slide candidate windows of the requested clip length
     across the video, score each by average + peak energy, and keep
     the top non-overlapping ones. Each kept candidate is matched back
     against the transcript to get its real spoken text.
   - **Render** — for each selected candidate: ffmpeg crops/pads the
     footage to a 1080×1920 vertical frame (blurred copy of the source
     as the pillarbox background), optionally burns in an `.srt` built
     from the matched transcript segments, bakes in the chosen color
     filter/effects and background music in the same encode pass, and
     ffmpeg also generates a styled thumbnail (dark gradient + bold
     headline) from a frame near the clip's midpoint. SEO titles,
     hashtags (per platform) and a description are generated from the
     real transcript text (`seo.py`).
5. Once all clips are rendered, `status` flips to `done` and the
   frontend renders the results grid (`ClipCard.jsx` per clip), where
   users can edit the title/description/hashtags, re-apply a different
   filter/effects (re-encodes just that clip), and download the MP4 or
   thumbnail.
6. Every project write also gets mirrored to Supabase (if configured)
   and to `backend/storage/db.json` (always), so history survives a
   restart.

---

## 3. Frontend structure

```
frontend/src/
├── main.jsx      entry point, mounts <App/>
├── App.jsx        the whole app: upload form, step tracker, results grid, history tab
├── ClipCard.jsx    one result card: video/thumbnail preview, SEO editing, filters/effects, download
├── api.js          thin fetch wrapper for every backend endpoint
├── App.css         component styles
└── index.css       CSS variables (theme), global resets, fonts
```

- **`api.js`** is the only file that knows the backend's URL
  (`VITE_API_BASE_URL`, see §5). Every network call goes through it —
  nothing else in the app calls `fetch` directly except file
  downloads in `ClipCard.jsx`.
- **`App.jsx`** owns almost all state: form inputs, the active
  project being polled, and the history list. `StepTracker` is a
  small subcomponent that renders the Fetch/Transcribe/Score/Render
  progress dots from `project.status`.
- **Theme**: dark by default, toggled to a light palette via a
  `theme-light` class on `<body>`, persisted in `localStorage`.

---

## 4. Backend structure

```
backend/app/
├── main.py             FastAPI app: routes, CORS, static file mounts
├── config.py            paths, ffmpeg binary resolution, music track definitions
├── pipeline.py           the background job: download → transcribe → score → render
├── scoring.py            candidate-window generation + RMS-energy scoring + transcript matching
├── transcribe.py         faster-whisper wrapper
├── ffmpeg_utils.py       every ffmpeg command (crop/pad, captions, filters, thumbnails)
├── seo.py                keyword extraction → titles/hashtags/description generator
├── store.py              Project/Clip data model + in-memory store + JSON/Supabase persistence
├── supabase_client.py    optional Supabase read/write helpers
├── generate_music.py     one-off script that synthesizes the royalty-free music library with ffmpeg
└── video_processor.py    an older, simpler "short clip" pipeline — not wired to any route (unused)
```

- **`main.py`** exposes:
  - `POST /api/projects` — start a job
  - `GET /api/projects` / `GET /api/projects/{id}` / `DELETE /api/projects/{id}`
  - `PATCH /api/projects/{id}/clips/{id}` — edit a clip's title/description/hashtags
  - `POST /api/projects/{id}/clips/{id}/edit` — re-render a clip with a different filter/effects
  - `GET /api/music-library`, `GET /api/edit-options`, `GET /api/health`
  - Static file mounts `/outputs`, `/uploads`, `/music` serve the rendered files directly from disk.
- **`store.py`** is a simple thread-safe in-memory dict of `Project`
  dataclasses, backed by `storage/db.json` on every write and mirrored
  to Supabase if credentials are configured. There is no real
  database migration system — it's intentionally simple.
- **Files live on local disk** under `backend/storage/{uploads,outputs,music}`
  — there's no S3/object storage. This matters a lot for deployment
  (see the deploy plan).

---

## 5. Configuration (environment variables)

| Var | Where | Purpose | Default |
|---|---|---|---|
| `VITE_API_BASE_URL` | frontend | Base URL of the backend API | `http://127.0.0.1:8000` |
| `SUPABASE_URL` | backend (`backend/.env`) | Supabase project URL | unset → local JSON storage only |
| `SUPABASE_KEY` (or `SUPABASE_ANON_KEY`/`SUPABASE_SERVICE_ROLE_KEY`) | backend | Supabase API key | unset |
| `ALLOWED_ORIGINS` | backend | Comma-separated extra CORS origins allowed to call the API (e.g. your deployed frontend URL) | `localhost:5173`/`3000` only |

---

## 6. Bugs found and fixed this session

1. **Frontend API URL was hardcoded** (`http://127.0.0.1:8000` baked
   into `api.js`) — would have broken the moment frontend and backend
   ran on different machines/domains. Now reads
   `import.meta.env.VITE_API_BASE_URL`.
2. **CORS was wide open**: `allow_origin_regex=r"https?://.*"` combined
   with `allow_credentials=True` let *any* website make credentialed
   requests to the API. Replaced with an explicit origin allowlist
   (`ALLOWED_ORIGINS` env var), no credentials (the app doesn't use
   cookies anywhere).
3. **Captions and content-aware SEO were dead code.** The pipeline
   never called `transcribe.py` — every clip's "transcript" was a
   placeholder string (`"Viral Moment 1"`, etc.), so:
   - "Burn-in subtitles" silently did nothing (`candidate_segments`
     was hardcoded to `None` before rendering).
   - Titles/hashtags/description were generated from that placeholder
     text, not what was actually said.
   - The `status` enum was also missing a `transcribing` value even
     though the frontend's step tracker already expected one.

   Fixed: `pipeline.py` now runs real transcription between audio
   extraction and scoring, `scoring.py` matches each selected clip
   window back to its overlapping transcript segments, and those are
   passed through to caption burn-in and SEO generation.
4. **Thumbnail text used a Windows-only font path**
   (`C:/Windows/Fonts/arialbd.ttf`) with no fallback — would silently
   degrade (font-name fallback, possibly missing) on any Linux
   deployment. Now checks Windows, then common Linux font paths
   (DejaVu/Liberation).
5. **Slow YouTube downloads.** Two causes, both fixed in `pipeline.py`
   (the code path actually used — a duplicate, unused copy in
   `video_processor.py` was fixed too for consistency):
   - `extractor_args.youtube.player_client` was hardcoded to
     `["android", "ios"]`. YouTube's current "SABR-only" experiment
     (see [yt-dlp#12482](https://github.com/yt-dlp/yt-dlp/issues/12482))
     serves these two clients throttled/incomplete formats — confirmed
     locally, this literally triggered the warning during testing.
     Removed the pin so yt-dlp picks its own current best-working
     client.
   - `concurrent_fragment_downloads` (parallel fragment downloading)
     was missing entirely from the live download path — added
     (`8` fragments in parallel), plus `http_chunk_size` so even a
     single progressive stream downloads as parallel byte-range
     requests instead of one serial stream.

## 7. Known limitations (not bugs, just worth knowing)

- **`video_processor.py` is unused** — an older/simpler pipeline that
  isn't wired to any route. Safe to ignore or delete later.
- **All media files live on local disk**, not object storage. Fine for
  a single always-on server; matters if you ever redeploy/restart on a
  host with an ephemeral filesystem (previously rendered clips would
  disappear even though the Supabase/JSON record still points at
  them) or try to run more than one backend instance.
- **No auth** — anyone who can reach the API can create/delete
  projects. Fine for personal/internal use; would need adding before
  any public-facing deployment.

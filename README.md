# ViralCut AI

Paste a video or upload a file, get ranked viral-worthy vertical clips with burned-in captions, a viral score, SEO titles/hashtags/description, and full History saved to **Supabase**.

## Features

1. **Flexible Clip Duration**: Specify exact target clip length using quick presets (30s, 1m, 2m, 3m, 5m, 10m) or type a custom clip duration in seconds or minutes.
2. **History Section & Supabase Database**: All project generations and clips are saved in history and synced to Supabase database (with local JSON fallback if offline).
3. **Smart Viral Scoring**: Heuristic scoring based on audio energy peaks, speech pace, and structural windows.
4. **Vertical 9:16 Render & Captions**: Clips are formatted for TikTok/Reels/Shorts with optional burned-in subtitles.
5. **SEO & Metadata**: Automatic title options, description, and hashtags per clip.

---

## Supabase Database Setup

To sync history directly with your Supabase project:

1. Create a `projects` table in your Supabase SQL Editor:
```sql
create table if not exists projects (
  id text primary key,
  source_type text,
  source text,
  status text,
  progress text,
  error text,
  duration numeric,
  clips jsonb,
  target_duration_min numeric,
  target_duration_sec numeric,
  burn_captions boolean,
  created_at timestamptz default now()
);
```

2. Create a `.env` file inside the `backend/` directory with your Supabase credentials:
```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-or-service-key
```

*Note: If no Supabase credentials are set, the application automatically falls back to local JSON storage (`backend/storage/db.json`) while maintaining full history functionality.*

---

## How to Run

### Backend

```bash
cd backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Requires **ffmpeg** on PATH.

### Frontend

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173`.

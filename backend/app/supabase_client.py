import os
from pathlib import Path
from typing import Any

# Load environment variables from .env file if present
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if ENV_FILE.exists():
    try:
        with ENV_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip().strip("'\""))
    except Exception as e:
        print(f"[Supabase] Error loading .env file: {e}")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

_supabase_client = None

def get_supabase_client():
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            from supabase import create_client
            _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
            print("[Supabase] Successfully initialized Supabase client.")
            return _supabase_client
        except Exception as e:
            print(f"[Supabase] Failed to initialize Supabase client: {e}")
            return None
    else:
        print("[Supabase] SUPABASE_URL or SUPABASE_KEY not set in environment. Running in local JSON storage mode.")
        return None


def is_supabase_enabled() -> bool:
    return get_supabase_client() is not None


def fetch_projects_from_supabase() -> list[dict[str, Any]] | None:
    client = get_supabase_client()
    if not client:
        return None
    try:
        res = client.table("projects").select("*").order("created_at", desc=True).execute()
        return res.data
    except Exception as e:
        print(f"[Supabase] Error fetching projects: {e}")
        return None


def upsert_project_to_supabase(project_data: dict[str, Any]) -> bool:
    client = get_supabase_client()
    if not client:
        return False
    try:
        # Supabase upsert
        client.table("projects").upsert(project_data).execute()
        return True
    except Exception as e:
        print(f"[Supabase] Error upserting project {project_data.get('id')}: {e}")
        return False


def delete_project_from_supabase(project_id: str) -> bool:
    client = get_supabase_client()
    if not client:
        return False
    try:
        client.table("projects").delete().eq("id", project_id).execute()
        return True
    except Exception as e:
        print(f"[Supabase] Error deleting project {project_id}: {e}")
        return False

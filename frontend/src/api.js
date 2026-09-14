const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const BASE_URL = RAW_BASE.trim().replace(/\/+$/, "");

function getUrl(path) {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${BASE_URL}${cleanPath}`;
}

async function safeFetch(url, options = {}) {
  try {
    const res = await fetch(url, options);
    return res;
  } catch (err) {
    if (err.name === "TypeError" || err.message.includes("fetch")) {
      throw new Error(
        "Could not connect to backend server. Render free tier may be spinning up from sleep mode (cold start takes ~40s), or VITE_API_BASE_URL is incorrect. Please wait 10 seconds and click 'Try again'."
      );
    }
    throw err;
  }
}

export async function createProject({
  file,
  videoUrl,
  confirmRights,
  targetDurationMin,
  targetDurationSec,
  burnCaptions,
  bgMusicFile,
  bgMusicTrackId,
  bgMusicVolume,
  filterName,
  effects,
}) {
  const form = new FormData();
  form.append("confirm_rights", confirmRights ? "true" : "false");
  if (file) form.append("file", file);
  if (videoUrl) form.append("video_url", videoUrl);
  if (targetDurationMin !== undefined) form.append("target_duration_min", targetDurationMin);
  if (targetDurationSec !== undefined) form.append("target_duration_sec", targetDurationSec);
  if (burnCaptions !== undefined) form.append("burn_captions", burnCaptions ? "true" : "false");
  if (bgMusicFile) form.append("bg_music_file", bgMusicFile);
  if (bgMusicTrackId) form.append("bg_music_track_id", bgMusicTrackId);
  if (bgMusicVolume !== undefined) form.append("bg_music_volume", bgMusicVolume);
  if (filterName) form.append("filter_name", filterName);
  (effects || []).forEach((e) => form.append("effects", e));

  const res = await safeFetch(getUrl("/api/projects"), { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to create project");
  }
  return res.json();
}

export async function getProjects() {
  const res = await safeFetch(getUrl("/api/projects"));
  if (!res.ok) throw new Error("Failed to fetch history projects");
  return res.json();
}

export async function getProject(projectId) {
  const res = await safeFetch(getUrl(`/api/projects/${projectId}`));
  if (!res.ok) {
    throw new Error(
      res.status === 404
        ? "This project no longer exists (it may have been deleted, or the server restarted)."
        : "Failed to fetch project"
    );
  }
  return res.json();
}

export async function deleteProject(projectId) {
  const res = await fetch(getUrl(`/api/projects/${projectId}`), { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete project");
  return res.json();
}

export async function updateClip(projectId, clipId, updates) {
  const res = await fetch(getUrl(`/api/projects/${projectId}/clips/${clipId}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error("Failed to update clip");
  return res.json();
}

export async function getEditOptions() {
  const res = await fetch(getUrl("/api/edit-options"));
  if (!res.ok) throw new Error("Failed to fetch edit options");
  return res.json();
}

export async function editClip(projectId, clipId, { filterName, effects }) {
  const res = await fetch(getUrl(`/api/projects/${projectId}/clips/${clipId}/edit`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filter_name: filterName, effects }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to apply edit");
  }
  return res.json();
}

export async function getMusicLibrary() {
  const res = await fetch(getUrl("/api/music-library"));
  if (!res.ok) throw new Error("Failed to fetch music library");
  return res.json();
}

export function fileUrl(path) {
  if (!path) return "";
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return getUrl(path);
}


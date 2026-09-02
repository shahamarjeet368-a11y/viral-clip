import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import "./App.css";
import {
  createProject,
  deleteProject,
  fileUrl,
  getEditOptions,
  getMusicLibrary,
  getProject,
  getProjects,
} from "./api";
import ClipCard from "./ClipCard";

const ACTIVE_STATUSES = ["queued", "fetching", "transcribing", "analyzing", "rendering"];

const STEPS = [
  { key: "fetching", label: "Fetch" },
  { key: "transcribing", label: "Transcribe" },
  { key: "analyzing", label: "Score" },
  { key: "rendering", label: "Render" },
];

const STATUS_LABELS = {
  queued: "Queued",
  fetching: "Fetching video",
  transcribing: "Transcribing speech",
  analyzing: "Scoring viral potential",
  rendering: "Rendering clips",
  done: "Done",
  error: "Error",
};

const DURATION_PRESETS = [
  { label: "30 Sec", sec: 30 },
  { label: "1 Min", sec: 60 },
  { label: "2 Min", sec: 120 },
  { label: "3 Min", sec: 180 },
  { label: "5 Min", sec: 300 },
  { label: "10 Min", sec: 600 },
];

function extractPercent(progress) {
  const match = /(\d+(?:\.\d+)?)%/.exec(progress || "");
  return match ? parseFloat(match[1]) : null;
}

function StepTracker({ project }) {
  const steps = project.source_type === "youtube" ? STEPS : STEPS.slice(1);
  const currentIndex = steps.findIndex((s) => s.key === project.status);
  const activeIdx = currentIndex === -1 ? 0 : currentIndex;
  const showProgressBar = ["fetching", "transcribing", "rendering"].includes(project.status);
  const progressPct = showProgressBar ? extractPercent(project.progress) : null;

  return (
    <div className="step-tracker">
      {steps.map((step, i) => {
        const state = i < activeIdx ? "done" : i === activeIdx ? "active" : "pending";
        return (
          <div className={`step step-${state}`} key={step.key}>
            <div className="step-dot">
              {state === "done" ? (
                "✓"
              ) : (
                <motion.span
                  animate={state === "active" ? { scale: [1, 1.25, 1] } : {}}
                  transition={{ repeat: Infinity, duration: 1.4 }}
                />
              )}
            </div>
            <span className="step-label">{step.label}</span>
            {i < steps.length - 1 && (
              <div className="step-connector">
                <motion.div
                  className="step-connector-fill"
                  initial={{ width: "0%" }}
                  animate={{ width: i < activeIdx ? "100%" : "0%" }}
                  transition={{ duration: 0.5 }}
                />
              </div>
            )}
          </div>
        );
      })}
      {progressPct !== null && (
        <div className="download-bar-track">
          <motion.div
            className="download-bar-fill"
            animate={{ width: `${progressPct}%` }}
            transition={{ duration: 0.4 }}
          />
        </div>
      )}
    </div>
  );
}

function App() {
  const [viewTab, setViewTab] = useState("create"); // "create" | "history"
  const [theme, setTheme] = useState(() => localStorage.getItem("viralcut_theme") || "dark");
  const [mode, setMode] = useState("upload");
  const [file, setFile] = useState(null);
  const [videoUrl, setVideoUrl] = useState("");
  const [confirmRights, setConfirmRights] = useState(false);
  
  // Duration controls
  const [durationPresetSec, setDurationPresetSec] = useState(120); // default 2 min
  const [isCustomDuration, setIsCustomDuration] = useState(false);
  const [customVal, setCustomVal] = useState(60);
  const [customUnit, setCustomUnit] = useState("sec"); // "sec" | "min"

  const [burnCaptions, setBurnCaptions] = useState(false);

  // Background music controls
  const [enableBgMusic, setEnableBgMusic] = useState(false);
  const [musicSource, setMusicSource] = useState("library"); // "library" | "upload"
  const [bgMusicFile, setBgMusicFile] = useState(null);
  const [musicLibrary, setMusicLibrary] = useState([]);
  const [selectedTrackId, setSelectedTrackId] = useState(null);
  const [playingTrackId, setPlayingTrackId] = useState(null);
  const [bgMusicVolume, setBgMusicVolume] = useState(0.15);

  // Default filter & effects (baked into the clip at render time)
  const [editOptions, setEditOptions] = useState({ filters: [], effects: [] });
  const [createFilterName, setCreateFilterName] = useState("none");
  const [createEffects, setCreateEffects] = useState([]);

  const [project, setProject] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  // History state
  const [historyList, setHistoryList] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const pollRef = useRef(null);
  const previewAudioRef = useRef(null);

  function toggleCreateEffect(effectId) {
    setCreateEffects((prev) =>
      prev.includes(effectId) ? prev.filter((e) => e !== effectId) : [...prev, effectId]
    );
  }

  function togglePreview(track) {
    const audio = previewAudioRef.current;
    if (!audio) return;
    if (playingTrackId === track.id) {
      audio.pause();
      setPlayingTrackId(null);
      return;
    }
    audio.src = fileUrl(track.url);
    audio.play();
    setPlayingTrackId(track.id);
  }

  useEffect(() => {
    document.body.classList.toggle("theme-light", theme === "light");
    localStorage.setItem("viralcut_theme", theme);
  }, [theme]);

  useEffect(() => {
    const savedId = localStorage.getItem("viralcut_active_project_id");
    if (savedId) {
      getProject(savedId)
        .then((data) => {
          setProject(data);
          if (ACTIVE_STATUSES.includes(data.status)) {
            startPolling(savedId);
          }
        })
        .catch(() => {
          localStorage.removeItem("viralcut_active_project_id");
        });
    }
    fetchHistory();
    getEditOptions().then(setEditOptions).catch(() => {});
    getMusicLibrary().then(setMusicLibrary).catch(() => {});
    return () => clearInterval(pollRef.current);
  }, []);

  async function fetchHistory() {
    setLoadingHistory(true);
    try {
      const projects = await getProjects();
      setHistoryList(projects);
    } catch (e) {
      console.error("Failed to load history:", e);
    } finally {
      setLoadingHistory(false);
    }
  }

  function startPolling(projectId) {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const data = await getProject(projectId);
        setProject(data);
        if (!ACTIVE_STATUSES.includes(data.status)) {
          clearInterval(pollRef.current);
          fetchHistory(); // refresh history list when job completes
        }
      } catch (e) {
        // The project we're polling is gone (deleted, or the server was
        // restarted mid-job) - keep polling forever against a 404 froze the
        // UI on the step tracker with only a silent console error. Fall
        // back to the create form instead, with the error visible there.
        clearInterval(pollRef.current);
        localStorage.removeItem("viralcut_active_project_id");
        setProject(null);
        setSubmitError(e.message);
        fetchHistory();
      }
    }, 2000);
  }

  function calculateTargetDurationSec() {
    if (isCustomDuration) {
      const val = parseFloat(customVal) || 60;
      return customUnit === "min" ? val * 60 : val;
    }
    return durationPresetSec;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitError(null);
    if (!confirmRights) {
      setSubmitError("Please confirm you have rights to this video.");
      return;
    }
    if (mode === "upload" && !file) {
      setSubmitError("Please choose a video file.");
      return;
    }
    if (mode === "youtube" && !videoUrl.trim()) {
      setSubmitError("Please paste a YouTube or Facebook video URL.");
      return;
    }
    if (enableBgMusic && musicSource === "upload" && !bgMusicFile) {
      setSubmitError("Please select a background music audio file.");
      return;
    }
    if (enableBgMusic && musicSource === "library" && !selectedTrackId) {
      setSubmitError("Please pick a track from the free music library.");
      return;
    }

    const targetSec = calculateTargetDurationSec();
    const targetMin = targetSec / 60;

    setSubmitting(true);
    try {
      const { project_id } = await createProject({
        file: mode === "upload" ? file : null,
        videoUrl: mode === "youtube" ? videoUrl.trim() : null,
        confirmRights,
        targetDurationMin: targetMin,
        targetDurationSec: targetSec,
        burnCaptions,
        bgMusicFile: enableBgMusic && musicSource === "upload" ? bgMusicFile : null,
        bgMusicTrackId: enableBgMusic && musicSource === "library" ? selectedTrackId : null,
        bgMusicVolume,
        filterName: createFilterName,
        effects: createEffects,
      });
      localStorage.setItem("viralcut_active_project_id", project_id);
      const data = await getProject(project_id);
      setProject(data);
      startPolling(project_id);
      fetchHistory();
    } catch (e) {
      setSubmitError(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  function handleReset() {
    clearInterval(pollRef.current);
    localStorage.removeItem("viralcut_active_project_id");
    setProject(null);
    setFile(null);
    setVideoUrl("");
    setEnableBgMusic(false);
    setMusicSource("library");
    setBgMusicFile(null);
    setSelectedTrackId(null);
    setBgMusicVolume(0.15);
    setCreateFilterName("none");
    setCreateEffects([]);
    setSubmitError(null);
    fetchHistory();
  }

  async function handleDeleteHistory(pid, event) {
    event.stopPropagation();
    if (!window.confirm("Are you sure you want to delete this item from history?")) return;
    try {
      await deleteProject(pid);
      setHistoryList((prev) => prev.filter((p) => p.id !== pid));
      if (project && project.id === pid) {
        handleReset();
      }
    } catch (e) {
      alert("Failed to delete project: " + e.message);
    }
  }

  function handleSelectHistoryItem(p) {
    setProject(p);
    setViewTab("create");
    if (ACTIVE_STATUSES.includes(p.status)) {
      startPolling(p.id);
    }
  }

  const uniqueHistoryList = historyList.filter(
    (item, index, self) =>
      index === self.findIndex((t) => t.source_type === item.source_type && t.source === item.source)
  );

  const isActive = project && ACTIVE_STATUSES.includes(project.status);

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          <span className="brand-mark">▶</span>
          ViralCut AI
        </div>
        <button
          type="button"
          className="theme-toggle-btn"
          onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          title="Toggle theme"
        >
          {theme === "dark" ? "🌙" : "☀️"}
        </button>
      </div>

      <motion.header
        className="app-header"
        initial={{ opacity: 0, y: -16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <h1>
          ViralCut <span className="accent-text">AI</span>
        </h1>
        <p>Paste a video, get ranked viral-worthy clips with captions and SEO baked in.</p>

        <nav className="main-nav">
          <button
            type="button"
            className={`nav-btn ${viewTab === "create" ? "nav-btn-active" : ""}`}
            onClick={() => setViewTab("create")}
          >
            🎬 Create Clip
          </button>
          <button
            type="button"
            className={`nav-btn ${viewTab === "history" ? "nav-btn-active" : ""}`}
            onClick={() => {
              setViewTab("history");
              fetchHistory();
            }}
          >
            📜 History <span className="badge-count">{uniqueHistoryList.length}</span>
          </button>
        </nav>
      </motion.header>

      <AnimatePresence mode="wait">
        {viewTab === "create" && (
          <motion.div
            key="create-tab"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.3 }}
          >
            {!project && (
              <motion.form
                key="form"
                className="upload-form"
                onSubmit={handleSubmit}
                initial={{ opacity: 0, y: 20, rotateX: -8 }}
                animate={{ opacity: 1, y: 0, rotateX: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4 }}
              >
                <div className="mode-tabs">
                  <button
                    type="button"
                    className={`tab ${mode === "upload" ? "tab-active" : ""}`}
                    onClick={() => setMode("upload")}
                  >
                    Upload file
                  </button>
                  <button
                    type="button"
                    className={`tab ${mode === "youtube" ? "tab-active" : ""}`}
                    onClick={() => setMode("youtube")}
                  >
                    Video link
                  </button>
                </div>

                <AnimatePresence mode="wait">
                  {mode === "upload" ? (
                    <motion.input
                      key="file-input"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      type="file"
                      accept="video/*"
                      onChange={(e) => setFile(e.target.files?.[0] || null)}
                      className="field-input"
                    />
                  ) : (
                    <motion.input
                      key="url-input"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      type="url"
                      placeholder="Paste YouTube or Facebook video URL..."
                      value={videoUrl}
                      onChange={(e) => setVideoUrl(e.target.value)}
                      className="field-input"
                    />
                  )}
                </AnimatePresence>

                <div className="form-section">
                  <label className="field-label">Clip Duration Input</label>
                  <div className="duration-pills">
                    {DURATION_PRESETS.map((item) => (
                      <button
                        key={item.sec}
                        type="button"
                        className={`pill-btn ${
                          !isCustomDuration && durationPresetSec === item.sec ? "pill-btn-active" : ""
                        }`}
                        onClick={() => {
                          setIsCustomDuration(false);
                          setDurationPresetSec(item.sec);
                        }}
                      >
                        {item.label}
                      </button>
                    ))}
                    <button
                      type="button"
                      className={`pill-btn ${isCustomDuration ? "pill-btn-active" : ""}`}
                      onClick={() => setIsCustomDuration(true)}
                    >
                      ✏️ Custom
                    </button>
                  </div>

                  {isCustomDuration && (
                    <div className="custom-duration-row">
                      <input
                        type="number"
                        min="5"
                        max="3600"
                        value={customVal}
                        onChange={(e) => setCustomVal(e.target.value)}
                        placeholder="Enter clip duration..."
                        className="custom-duration-input"
                      />
                      <select
                        value={customUnit}
                        onChange={(e) => setCustomUnit(e.target.value)}
                        className="custom-unit-select"
                      >
                        <option value="sec">Seconds</option>
                        <option value="min">Minutes</option>
                      </select>
                    </div>
                  )}
                </div>

                <div className="form-section">
                  <label className="toggle-container">
                    <div className="toggle-switch">
                      <input
                        type="checkbox"
                        checked={burnCaptions}
                        onChange={(e) => setBurnCaptions(e.target.checked)}
                      />
                      <span className="toggle-slider"></span>
                    </div>
                    <span className="toggle-label">Burn-in subtitles/captions</span>
                  </label>
                </div>

                <div className="form-section">
                  <label className="field-label">🎨 Default Filter &amp; Effects</label>
                  <div className="edit-panel">
                    <div className="bg-music-row">
                      <label className="field-sublabel">Color Filter</label>
                      <select
                        className="field-select"
                        value={createFilterName}
                        onChange={(e) => setCreateFilterName(e.target.value)}
                      >
                        {editOptions.filters.map((f) => (
                          <option key={f.id} value={f.id}>
                            {f.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="bg-music-row">
                      <label className="field-sublabel">Effects</label>
                      <div className="effect-chip-row">
                        {editOptions.effects.map((eff) => (
                          <button
                            key={eff.id}
                            type="button"
                            className={`pill-btn ${createEffects.includes(eff.id) ? "pill-btn-active" : ""}`}
                            onClick={() => toggleCreateEffect(eff.id)}
                          >
                            {eff.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="form-section">
                  <label className="toggle-container">
                    <div className="toggle-switch">
                      <input
                        type="checkbox"
                        checked={enableBgMusic}
                        onChange={(e) => setEnableBgMusic(e.target.checked)}
                      />
                      <span className="toggle-slider"></span>
                    </div>
                    <span className="toggle-label">🎵 Add Background Music</span>
                  </label>

                  {enableBgMusic && (
                    <motion.div
                      className="bg-music-panel"
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.3 }}
                    >
                      <div className="mode-tabs">
                        <button
                          type="button"
                          className={`tab ${musicSource === "library" ? "tab-active" : ""}`}
                          onClick={() => setMusicSource("library")}
                        >
                          🎧 Free Music Library
                        </button>
                        <button
                          type="button"
                          className={`tab ${musicSource === "upload" ? "tab-active" : ""}`}
                          onClick={() => setMusicSource("upload")}
                        >
                          Upload your own
                        </button>
                      </div>

                      {musicSource === "library" ? (
                        <div className="bg-music-row">
                          <label className="field-sublabel">
                            Copyright-free tracks — pick one to preview or use
                          </label>
                          <div className="music-track-list">
                            {musicLibrary.map((track) => (
                              <div
                                key={track.id}
                                className={`music-track-row ${
                                  selectedTrackId === track.id ? "music-track-row-active" : ""
                                }`}
                                onClick={() => setSelectedTrackId(track.id)}
                              >
                                <button
                                  type="button"
                                  className="music-preview-btn"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    togglePreview(track);
                                  }}
                                >
                                  {playingTrackId === track.id ? "⏸" : "▶"}
                                </button>
                                <div className="music-track-info">
                                  <span className="music-track-name">{track.name}</span>
                                  <span className="music-track-mood">{track.mood}</span>
                                </div>
                                {selectedTrackId === track.id && (
                                  <span className="music-track-check">✓</span>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : (
                        <div className="bg-music-row">
                          <label className="field-sublabel">Audio File (.mp3, .wav, .m4a)</label>
                          <input
                            type="file"
                            accept="audio/*"
                            className="field-input"
                            onChange={(e) => setBgMusicFile(e.target.files?.[0] || null)}
                          />
                        </div>
                      )}

                      <div className="bg-music-row">
                        <div className="volume-label-row">
                          <label className="field-sublabel">Music Volume</label>
                          <span className="volume-value">{Math.round(bgMusicVolume * 100)}%</span>
                        </div>
                        <input
                          type="range"
                          min="0.05"
                          max="0.50"
                          step="0.01"
                          value={bgMusicVolume}
                          onChange={(e) => setBgMusicVolume(parseFloat(e.target.value))}
                          className="volume-slider"
                        />
                      </div>
                    </motion.div>
                  )}
                </div>

                <audio
                  ref={previewAudioRef}
                  onEnded={() => setPlayingTrackId(null)}
                  hidden
                />

                <label className="rights-check">
                  <input
                    type="checkbox"
                    checked={confirmRights}
                    onChange={(e) => setConfirmRights(e.target.checked)}
                  />
                  I own this video, or have explicit rights to use and edit it.
                </label>

                {submitError && <p className="error-text">{submitError}</p>}

                <motion.button
                  className="btn btn-block"
                  type="submit"
                  disabled={submitting}
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.97 }}
                >
                  {submitting ? "Uploading..." : "Find viral clips"}
                </motion.button>
              </motion.form>
            )}

            {project && isActive && (
              <motion.div
                key="status"
                className="status-panel"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
              >
                <StepTracker project={project} />
                <p className="status-detail">{project.progress || STATUS_LABELS[project.status]}</p>
              </motion.div>
            )}

            {project && project.status === "error" && (
              <motion.div
                key="error"
                className="status-panel status-error"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <p>Something went wrong: {project.error}</p>
                <button className="btn" onClick={handleReset}>Try again</button>
              </motion.div>
            )}

            {project && project.status === "done" && (
              <motion.div
                key="results"
                className="results"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
              >
                <div className="results-header">
                  <h2>{project.clips.length} clips found</h2>
                  <button className="btn btn-secondary" onClick={handleReset}>New project</button>
                </div>
                <div className="clip-grid">
                  {project.clips.map((clip, i) => (
                    <ClipCard key={clip.id} projectId={project.id} clip={clip} index={i} />
                  ))}
                </div>
              </motion.div>
            )}
          </motion.div>
        )}

        {viewTab === "history" && (
          <motion.div
            key="history-tab"
            className="history-container"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.3 }}
          >
            <div className="history-header">
              <h2>Generation History</h2>
              <span className="db-badge">⚡ Supabase Database Active</span>
            </div>

            {loadingHistory ? (
              <p style={{ textAlign: "center", color: "var(--text-muted)", padding: "2rem" }}>
                Loading history from Supabase...
              </p>
            ) : uniqueHistoryList.length === 0 ? (
              <div className="empty-history">
                <p style={{ fontSize: "1.2rem", fontWeight: 600, marginBottom: "0.5rem" }}>
                  No generation history found
                </p>
                <p>Created clip projects will be saved here automatically.</p>
                <button
                  className="btn"
                  style={{ marginTop: "1rem" }}
                  onClick={() => setViewTab("create")}
                >
                  Create First Clip
                </button>
              </div>
            ) : (
              <div className="history-list">
                {uniqueHistoryList.map((p) => {
                  const createdDate = p.created_at
                    ? new Date(p.created_at).toLocaleString()
                    : "Unknown date";
                  const targetSec = p.target_duration_sec || (p.target_duration_min ? p.target_duration_min * 60 : 600);
                  const durLabel = targetSec >= 60 ? `${Math.round(targetSec / 60)} Mins` : `${targetSec} Secs`;

                  return (
                    <div
                      key={p.id}
                      className="history-card"
                      onClick={() => handleSelectHistoryItem(p)}
                      style={{ cursor: "pointer" }}
                    >
                      <div className="history-info">
                        <div className="history-title">
                          {p.source_type === "upload" ? `📁 ${p.source}` : `🔗 ${p.source}`}
                        </div>
                        <div className="history-meta">
                          <span>{createdDate}</span>
                          <span>• Target: {durLabel}</span>
                          <span>• Subtitles: {p.burn_captions ? "On" : "Off"}</span>
                          <span>• Clips: {p.clips ? p.clips.length : 0}</span>
                        </div>
                      </div>
                      <div className="history-actions">
                        <span
                          className={`status-tag ${
                            p.status === "done"
                              ? "status-tag-done"
                              : p.status === "error"
                              ? "status-tag-error"
                              : "status-tag-active"
                          }`}
                        >
                          {p.status}
                        </span>
                        <button
                          className="btn btn-secondary"
                          style={{ padding: "0.4rem 0.8rem", fontSize: "0.85rem" }}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleSelectHistoryItem(p);
                          }}
                        >
                          View Clips
                        </button>
                        <button
                          className="btn-danger"
                          title="Delete from history"
                          onClick={(e) => handleDeleteHistory(p.id, e)}
                        >
                          🗑️
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default App;

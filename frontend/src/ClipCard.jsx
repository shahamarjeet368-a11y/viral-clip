import { motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { editClip, fileUrl, getEditOptions, updateClip } from "./api";

const PLATFORMS = ["instagram", "youtube", "tiktok"];
const TILT_RANGE = 8; // max degrees of 3D tilt on hover

export default function ClipCard({ projectId, clip, index = 0 }) {
  const [localClip, setLocalClip] = useState(clip);
  const [platform, setPlatform] = useState("instagram");
  const [title, setTitle] = useState(clip.seo.selected_title || clip.seo.titles[0]);
  const [description, setDescription] = useState(clip.seo.description);
  const [hashtagsText, setHashtagsText] = useState(clip.seo.hashtags[platform].join(" "));
  const [saved, setSaved] = useState(false);
  const [viewMode, setViewMode] = useState("video");
  const [tilt, setTilt] = useState({ x: 0, y: 0 });
  const cardRef = useRef(null);

  const [copiedTitle, setCopiedTitle] = useState(false);
  const [copiedDescription, setCopiedDescription] = useState(false);
  const [copiedHashtags, setCopiedHashtags] = useState(false);

  // Filters & effects editing
  const [showEditPanel, setShowEditPanel] = useState(false);
  const [editOptions, setEditOptions] = useState({ filters: [], effects: [] });
  const [filterName, setFilterName] = useState(clip.filter_name || "none");
  const [selectedEffects, setSelectedEffects] = useState(clip.effects || []);
  const [applyingEdit, setApplyingEdit] = useState(false);
  const [editError, setEditError] = useState(null);
  const [editVersion, setEditVersion] = useState(0);

  useEffect(() => {
    getEditOptions()
      .then(setEditOptions)
      .catch(() => {});
  }, []);

  function toggleEffect(effectId) {
    setSelectedEffects((prev) =>
      prev.includes(effectId) ? prev.filter((e) => e !== effectId) : [...prev, effectId]
    );
  }

  async function handleApplyEdit() {
    setApplyingEdit(true);
    setEditError(null);
    try {
      const updated = await editClip(projectId, localClip.id, { filterName, effects: selectedEffects });
      setLocalClip(updated);
      setEditVersion((v) => v + 1);
    } catch (err) {
      setEditError(err.message);
    } finally {
      setApplyingEdit(false);
    }
  }

  function copyText(text, setCopiedState) {
    navigator.clipboard.writeText(text);
    setCopiedState(true);
    setTimeout(() => setCopiedState(false), 2000);
  }

  function handleMouseMove(e) {
    const rect = cardRef.current.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width - 0.5;
    const py = (e.clientY - rect.top) / rect.height - 0.5;
    setTilt({ x: py * -TILT_RANGE, y: px * TILT_RANGE });
  }

  function handleMouseLeave() {
    setTilt({ x: 0, y: 0 });
  }

  function switchPlatform(p) {
    setPlatform(p);
    setHashtagsText(clip.seo.hashtags[p].join(" "));
    setSaved(false);
  }

  async function handleSave() {
    const hashtags = { ...clip.seo.hashtags, [platform]: hashtagsText.split(/\s+/).filter(Boolean) };
    await updateClip(projectId, clip.id, { title, description, hashtags });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  async function handleDownload() {
    try {
      const res = await fetch(fileUrl(localClip.file_path));
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${localClip.id || "clip"}.mp4`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      console.error(err);
      window.open(fileUrl(localClip.file_path), "_blank");
    }
  }

  async function handleDownloadThumbnail() {
    if (!localClip.thumbnail_path) return;
    try {
      const res = await fetch(fileUrl(localClip.thumbnail_path));
      if (!res.ok) throw new Error("Thumbnail download failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${localClip.id || "clip"}_thumb.jpg`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      console.error(err);
      window.open(fileUrl(localClip.thumbnail_path), "_blank");
    }
  }

  return (
    <motion.div
      ref={cardRef}
      className="clip-card"
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: index * 0.08 }}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      style={{
        transform: `perspective(900px) rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)`,
      }}
    >
      <div className="clip-media-container">
        {localClip.thumbnail_path && (
          <div className="media-toggle-bar">
            <button
              type="button"
              className={`media-toggle-btn ${viewMode === "video" ? "active" : ""}`}
              onClick={() => setViewMode("video")}
            >
              🎥 Video
            </button>
            <button
              type="button"
              className={`media-toggle-btn ${viewMode === "thumbnail" ? "active" : ""}`}
              onClick={() => setViewMode("thumbnail")}
            >
              🖼️ Thumbnail
            </button>
          </div>
        )}

        {viewMode === "video" || !localClip.thumbnail_path ? (
          <video
            key={`${localClip.file_path}?v=${editVersion}`}
            className="clip-video"
            src={`${fileUrl(localClip.file_path)}${editVersion ? `?v=${editVersion}` : ""}`}
            poster={localClip.thumbnail_path ? fileUrl(localClip.thumbnail_path) : undefined}
            controls
            preload="metadata"
          />
        ) : (
          <div className="thumbnail-preview-box">
            <img
              src={fileUrl(localClip.thumbnail_path)}
              alt="Viral Thumbnail"
              className="clip-thumbnail-img"
            />
          </div>
        )}
      </div>

      <div className="clip-body">
        <div className="clip-score">
          <span className="score-badge">{clip.score}% viral</span>
          <span className="clip-duration">
            {Math.floor(clip.duration / 60)}:{String(Math.round(clip.duration % 60)).padStart(2, "0")}
          </span>
        </div>

        <div className="field-header">
          <label className="field-label">Filters &amp; Effects</label>
          <button
            type="button"
            className={`copy-btn ${showEditPanel ? "copy-btn-success" : ""}`}
            onClick={() => setShowEditPanel((v) => !v)}
          >
            {showEditPanel ? "Hide" : "Edit"}
          </button>
        </div>

        {showEditPanel && (
          <motion.div
            className="edit-panel"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.25 }}
          >
            <div className="bg-music-row">
              <label className="field-sublabel">Color Filter</label>
              <select
                className="field-select"
                value={filterName}
                onChange={(e) => setFilterName(e.target.value)}
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
                    className={`pill-btn ${selectedEffects.includes(eff.id) ? "pill-btn-active" : ""}`}
                    onClick={() => toggleEffect(eff.id)}
                  >
                    {eff.label}
                  </button>
                ))}
              </div>
            </div>

            {editError && <p className="error-text">{editError}</p>}

            <button
              type="button"
              className="btn btn-block"
              disabled={applyingEdit}
              onClick={handleApplyEdit}
            >
              {applyingEdit ? "Applying... this can take a minute or two" : "Apply Filter & Effects"}
            </button>
            {applyingEdit && (
              <p className="edit-panel-hint">
                Re-encoding the full clip - please don't close this tab or click Apply again until it finishes.
              </p>
            )}
          </motion.div>
        )}

        <div className="field-header">
          <label className="field-label">Title</label>
          <button
            type="button"
            className={`copy-btn ${copiedTitle ? "copy-btn-success" : ""}`}
            onClick={() => copyText(title, setCopiedTitle)}
          >
            {copiedTitle ? "Copied" : "Copy"}
          </button>
        </div>
        <input
          className="field-input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <div className="title-suggestions">
          {clip.seo.titles.map((t) => (
            <button key={t} type="button" className="chip" onClick={() => setTitle(t)}>
              {t}
            </button>
          ))}
        </div>

        <div className="field-header">
          <label className="field-label">Description</label>
          <button
            type="button"
            className={`copy-btn ${copiedDescription ? "copy-btn-success" : ""}`}
            onClick={() => copyText(description, setCopiedDescription)}
          >
            {copiedDescription ? "Copied" : "Copy"}
          </button>
        </div>
        <textarea
          className="field-textarea"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
        />

        <div className="field-header">
          <label className="field-label">Hashtags</label>
          <button
            type="button"
            className={`copy-btn ${copiedHashtags ? "copy-btn-success" : ""}`}
            onClick={() => copyText(hashtagsText, setCopiedHashtags)}
          >
            {copiedHashtags ? "Copied" : "Copy"}
          </button>
        </div>
        <div className="platform-tabs">
          {PLATFORMS.map((p) => (
            <button
              key={p}
              className={`tab ${platform === p ? "tab-active" : ""}`}
              onClick={() => switchPlatform(p)}
              type="button"
            >
              {p}
            </button>
          ))}
        </div>
        <textarea
          className="field-textarea"
          value={hashtagsText}
          onChange={(e) => setHashtagsText(e.target.value)}
          rows={2}
        />

        <div className="clip-actions">
          <button className="btn" onClick={handleSave}>{saved ? "Saved!" : "Save changes"}</button>
          <button type="button" className="btn btn-secondary" onClick={handleDownload}>
            Download MP4
          </button>
          {localClip.thumbnail_path && (
            <button type="button" className="btn btn-secondary" onClick={handleDownloadThumbnail}>
              🖼️ Thumbnail
            </button>
          )}
        </div>
      </div>
    </motion.div>
  );
}

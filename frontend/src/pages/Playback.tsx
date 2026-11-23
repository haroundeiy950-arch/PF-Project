import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { useRealtime } from "../context/RealtimeContext";
import { useDocumentTitle, useResource } from "../hooks/useResource";
import {
  cx,
  formatBytes,
  formatDateTime,
  formatDuration,
  formatGb,
  formatTime,
} from "../lib/format";
import type { EvidenceAudit, Recording } from "../types";
import {
  IconCamera,
  IconClock,
  IconDatabase,
  IconDownload,
  IconFilm,
  IconPlay,
  IconRefresh,
  IconTrash,
  IconWarning,
} from "../components/Icons";
import {
  EmptyState,
  ErrorState,
  Gauge,
  LoadingState,
  Modal,
  Pagination,
  Panel,
  TonePill,
} from "../components/UI";

const PAGE_SIZE = 24;

export default function Playback() {
  useDocumentTitle("Evidence Playback");
  const { can } = useAuth();
  const { pushToast, statsVersion } = useRealtime();
  const [searchParams] = useSearchParams();
  const [cameraId, setCameraId] = useState(searchParams.get("camera") ?? "");
  const [kind, setKind] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Recording | null>(null);
  const [deleting, setDeleting] = useState<Recording | null>(null);
  const [busy, setBusy] = useState(false);
  const [audit, setAudit] = useState<EvidenceAudit | null>(null);
  const [auditBusy, setAuditBusy] = useState(false);

  const cameras = useResource(() => api.cameras.list(), []);
  const stats = useResource(() => api.recordings.stats(), [statsVersion]);
  const system = useResource(() => api.system.info(), []);
  const filterKey = [cameraId, kind, offset].join("|");
  const recordings = useResource(
    () =>
      api.recordings.list({
        camera_id: cameraId || undefined,
        kind: kind || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    [filterKey, statsVersion],
  );

  const remove = async () => {
    if (!deleting) return;
    setBusy(true);
    try {
      await api.recordings.remove(deleting.id);
      pushToast({ title: "Evidence deleted", message: "The recording was removed and audited", tone: "success" });
      setDeleting(null);
      stats.reload();
      recordings.reload();
    } catch (error) {
      pushToast({ title: "Delete failed", message: error instanceof Error ? error.message : "Request rejected", tone: "danger" });
    } finally {
      setBusy(false);
    }
  };

  const runAudit = async (repair = false) => {
    if (auditBusy) return;
    setAuditBusy(true);
    try {
      const result = await api.recordings.audit(repair);
      setAudit(result);
      pushToast({
        title: result.healthy ? "Evidence archive healthy" : "Evidence issues found",
        message: `${result.checked_files} files checked · ${result.summary.unresolved} unresolved`,
        tone: result.healthy ? "success" : "warning",
      });
      stats.reload();
      recordings.reload();
    } catch (error) {
      pushToast({ title: "Audit failed", message: error instanceof Error ? error.message : "Request rejected", tone: "danger" });
    } finally {
      setAuditBusy(false);
    }
  };

  const durationLabel = (recording: Recording) =>
    recording.kind === "snapshot" ? "Still image" : formatDuration(recording.duration_seconds);

  const items = recordings.data?.items ?? [];
  const total = recordings.data?.total ?? 0;
  const disk = stats.data?.disk;
  const clips = stats.data?.by_kind.find((item) => item.kind === "clip");
  const snapshots = stats.data?.by_kind.find((item) => item.kind === "snapshot");
  const continuous = stats.data?.by_kind.find((item) => item.kind === "continuous");
  const segmentMinutes = Math.max(1, Math.round((system.data?.continuous_segment_seconds ?? 300) / 60));

  return (
    <div className="page page--playback">
      <div className="page-toolbar">
        <div className="page-toolbar__left">
          <span className="live-chip">
            <span className="live-chip__dot" /> EVIDENCE ARCHIVE
          </span>
          <span className="muted">
            {stats.data?.total_count ?? 0} files · {formatBytes(stats.data?.total_size_bytes ?? 0)} stored · retention
            policy enforced nightly
          </span>
        </div>
        <div className="page-toolbar__actions">
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            disabled={auditBusy}
            onClick={() => void runAudit(false)}
          >
            <IconWarning size={14} /> {auditBusy ? "Auditing…" : "Audit files"}
          </button>
          {can("delete_recordings") && (
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              disabled={auditBusy}
              onClick={() => void runAudit(true)}
            >
              Repair files
            </button>
          )}
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => { stats.reload(); recordings.reload(); }}>
            <IconRefresh size={14} /> Refresh archive
          </button>
          {can("view_reports") && (
            <Link to="/reports" className="btn btn--primary btn--sm">
              <IconDownload size={14} /> Evidence report
            </Link>
          )}
        </div>
      </div>

      {audit && (
        <div className="safety-note">
          <IconWarning size={15} />
          <span>
            {audit.healthy ? "All evidence files are valid." : `${audit.summary.unresolved} issue(s) need attention.`}{" "}
            {audit.checked_files} files checked · {audit.summary.expected_active} in-progress file(s) skipped ·{" "}
            {audit.summary.fixed} repaired.
          </span>
        </div>
      )}

      <div className="stat-strip">
        <div className="stat-tile stat-tile--cyan">
          <span className="stat-tile__icon"><IconFilm size={18} /></span>
          <span>
            <small>Video clips</small>
            <strong>{clips?.count ?? 0}</strong>
            <em>{formatBytes(clips?.size_bytes ?? 0)}</em>
          </span>
        </div>
        <div className="stat-tile stat-tile--cyan">
          <span className="stat-tile__icon"><IconFilm size={18} /></span>
          <span>
            <small>Continuous video</small>
            <strong>{continuous?.count ?? 0}</strong>
            <em>{formatBytes(continuous?.size_bytes ?? 0)}</em>
          </span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile__icon"><IconCamera size={18} /></span>
          <span>
            <small>Snapshots</small>
            <strong>{snapshots?.count ?? 0}</strong>
            <em>{formatBytes(snapshots?.size_bytes ?? 0)}</em>
          </span>
        </div>
        <div className="stat-tile stat-tile--green">
          <span className="stat-tile__icon"><IconDatabase size={18} /></span>
          <span>
            <small>Evidence on disk</small>
            <strong>{formatGb(stats.data?.total_size_gb ?? 0)}</strong>
            <em>{disk ? `${formatGb(disk.storage_gb)} media folder` : "calculating"}</em>
          </span>
        </div>
        <div className="stat-tile stat-tile--amber">
          <span className="stat-tile__icon"><IconWarning size={18} /></span>
          <span>
            <small>Disk usage</small>
            <strong>{disk?.percent ?? 0}%</strong>
            <em>{disk ? `${disk.free_gb} GB free` : "—"}</em>
          </span>
        </div>
      </div>

      <div className="playback-top">
        <Panel title="Storage health" subtitle="Workspace disk where evidence is written" accent="green">
          {disk ? (
            <div className="health">
              <div className="health__gauges">
                <Gauge label="Disk used" value={disk.percent} />
              </div>
              <div className="health__facts">
                <div>
                  <IconDatabase size={14} />
                  <span>Total</span>
                  <strong>{formatGb(disk.total_gb ?? 0)}</strong>
                </div>
                <div>
                  <IconFilm size={14} />
                  <span>Free</span>
                  <strong>{formatGb(disk.free_gb)}</strong>
                </div>
                <div>
                  <IconClock size={14} />
                  <span>Files</span>
                  <strong>{stats.data?.total_count ?? 0}</strong>
                </div>
              </div>
              <small className="muted">Evidence is retained according to the recording retention setting.</small>
            </div>
          ) : (
            <LoadingState label="Reading disk telemetry…" />
          )}
        </Panel>

        <Panel title="Playback guide" subtitle="How evidence is captured" accent="amber">
          <div className="playback-guide">
            <div>
              <span>PRE-EVENT</span>
              <strong>6 seconds</strong>
              <small>Buffered before the verified detection</small>
            </div>
            <div>
              <span>POST-EVENT</span>
              <strong>3 seconds</strong>
              <small>Captured after the incident is raised</small>
            </div>
            <div>
              <span>CONTINUOUS</span>
              <strong>{system.data?.continuous_recording_enabled === false ? "OFF" : `${segmentMinutes} min`}</strong>
              <small>Non-stop segmented video, not only alarms</small>
            </div>
            <div>
              <span>FORMAT</span>
              <strong>MP4 + JPG</strong>
              <small>Continuous clips, event clips and snapshots</small>
            </div>
          </div>
          <p className="safety-note">
            <IconWarning size={15} />
            Evidence is access-controlled by role. Deletions are permanent and always recorded in the audit trail.
          </p>
        </Panel>
      </div>

      <Panel title="Recordings & snapshots" subtitle="Search the evidence archive by camera or file type" bodyClassName="panel__body--flush">
        <div className="filter-bar">
          <select className="select" value={cameraId} onChange={(event) => { setCameraId(event.target.value); setOffset(0); }}>
            <option value="">All cameras</option>
            {cameras.data?.items.map((camera) => (
              <option key={camera.id} value={camera.id}>{camera.code} · {camera.name}</option>
            ))}
          </select>
          <select className="select" value={kind} onChange={(event) => { setKind(event.target.value); setOffset(0); }}>
            <option value="">All file types</option>
            <option value="continuous">Continuous video</option>
            <option value="clip">Event clips</option>
            <option value="snapshot">Snapshots</option>
          </select>
          <span className="filter-bar__count">{total} matching files</span>
        </div>

        {recordings.loading && !recordings.data ? (
          <LoadingState label="Loading evidence archive…" />
        ) : recordings.error ? (
          <ErrorState message={recordings.error} retry={recordings.reload} />
        ) : items.length ? (
          <>
            <div className="evidence-grid">
              {items.map((recording) => (
                <button
                  type="button"
                  className={cx("evidence-card", recording.kind === "snapshot" && "evidence-card--snapshot")}
                  key={recording.id}
                  onClick={() => setSelected(recording)}
                >
                  <span className="evidence-card__media">
                    {recording.kind === "snapshot" && recording.url ? (
                      <img src={recording.url} alt="Evidence snapshot" loading="lazy" />
                    ) : recording.url ? (
                      <video src={recording.url} preload="metadata" muted />
                    ) : (
                      <span className="evidence-card__missing"><IconFilm size={22} /> File unavailable</span>
                    )}
                    <span className="evidence-card__play"><IconPlay size={18} /></span>
                    <span className="evidence-card__kind">{recording.kind.toUpperCase()}</span>
                  </span>
                  <span className="evidence-card__body">
                    <strong>{recording.camera_code ?? recording.camera_name ?? `Camera ${recording.camera_id}`}</strong>
                    <small>{formatDateTime(recording.started_at, true)}</small>
                    <span className="evidence-card__meta">
                      <span>{durationLabel(recording)}</span>
                      <span>{formatBytes(recording.size_bytes)}</span>
                      {recording.incident_code && <span className="mono">{recording.incident_code}</span>}
                    </span>
                  </span>
                </button>
              ))}
            </div>
            <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        ) : (
          <EmptyState
            icon={<IconFilm size={28} />}
            title="No recordings found"
            message="Continuous segments, event snapshots and incident clips are saved here automatically while the live camera is running."
            action={<Link to="/devices" className="btn btn--ghost btn--sm">Open cameras</Link>}
          />
        )}
      </Panel>

      <Modal
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={selected
          ? `${
              selected.kind === "snapshot"
                ? "Evidence snapshot"
                : selected.kind === "continuous"
                  ? "Continuous recording"
                  : "Evidence clip"
            } · ${selected.camera_code ?? selected.camera_name}`
          : "Evidence"}
        subtitle={selected ? formatDateTime(selected.started_at, true) : undefined}
        size="xl"
        footer={
          selected ? (
            <div className="modal__footer-row">
              <div className="btn-row">
                {selected.incident_id && (
                  <Link className="btn btn--danger btn--sm" to={`/threat/${selected.incident_id}`} onClick={() => setSelected(null)}>
                    Open incident
                  </Link>
                )}
                {selected.url && (
                  <a className="btn btn--ghost btn--sm" href={selected.url} download>
                    <IconDownload size={14} /> Download
                  </a>
                )}
                {can("delete_recordings") && (
                  <button type="button" className="btn btn--ghost btn--sm btn--danger-ghost" onClick={() => { setDeleting(selected); setSelected(null); }}>
                    <IconTrash size={14} /> Delete evidence
                  </button>
                )}
              </div>
              <span className="muted">
                {formatBytes(selected.size_bytes)} · {durationLabel(selected)} · {selected.path}
              </span>
            </div>
          ) : null
        }
      >
        {selected && (
          <div className="evidence-player">
            {selected.kind === "snapshot" && selected.url ? (
              <img src={selected.url} alt="Evidence snapshot in full resolution" />
            ) : selected.url ? (
              <video src={selected.url} controls autoPlay playsInline />
            ) : (
              <EmptyState title="File unavailable" message="The evidence file may have been removed by the retention policy." />
            )}
            <div className="evidence-player__meta">
              <span><IconCamera size={13} /> {selected.camera_name}</span>
              <span><IconClock size={13} /> {formatTime(selected.started_at, true)} → {formatTime(selected.ended_at, true)}</span>
              {selected.incident_code && <TonePill tone={selected.incident_level === "critical" ? "red" : "amber"}>{selected.incident_code}</TonePill>}
              <span className="mono">{selected.kind.toUpperCase()}</span>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={Boolean(deleting)}
        onClose={() => setDeleting(null)}
        title="Delete evidence file"
        subtitle={deleting ? `${deleting.kind} · ${deleting.camera_code ?? deleting.camera_name}` : undefined}
        size="sm"
        footer={
          <div className="modal__footer-row">
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => setDeleting(null)}>Cancel</button>
            <button type="button" className="btn btn--danger btn--sm" disabled={busy} onClick={() => void remove()}>
              {busy ? <span className="spinner spinner--sm" /> : <IconTrash size={14} />} Delete permanently
            </button>
          </div>
        }
      >
        <p className="muted">
          This removes the file from disk and detaches it from the incident. The deletion is recorded in the audit log
          with your username and IP address. This action cannot be undone.
        </p>
      </Modal>
    </div>
  );
}

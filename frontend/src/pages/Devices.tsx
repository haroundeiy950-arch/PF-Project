import { useMemo, useRef, useState, type FormEvent, type MouseEvent as ReactMouseEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { useRealtime } from "../context/RealtimeContext";
import { useDocumentTitle, useResource } from "../hooks/useResource";
import {
  ZONE_LABELS,
  cx,
  formatRelative,
  formatTime,
  humanize,
} from "../lib/format";
import type { Camera, Zone } from "../types";
import {
  IconCamera,
  IconCheck,
  IconClock,
  IconClose,
  IconDatabase,
  IconEdit,
  IconExpand,
  IconEye,
  IconPlayback,
  IconPlus,
  IconRefresh,
  IconShield,
  IconTarget,
  IconTrash,
  IconWarning,
} from "../components/Icons";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  Modal,
  Panel,
  TonePill,
  Toggle,
} from "../components/UI";

type Tab = "cameras" | "zones";

const DEFAULT_POINTS = [
  [0.18, 0.24],
  [0.82, 0.24],
  [0.82, 0.78],
  [0.18, 0.78],
];

const ZONE_TYPE_COLORS: Record<string, string> = {
  restricted: "#ef4444",
  limited: "#f59e0b",
  public: "#22d3ee",
};

function statusTone(status: string): "green" | "amber" | "red" | "muted" {
  if (status === "online" || status === "streaming") return "green";
  if (status === "starting" || status === "connecting") return "amber";
  if (status === "error" || status === "offline" || status === "stopped") return "red";
  return "muted";
}

interface ConfirmRequest {
  title: string;
  message: string;
  confirmLabel: string;
  action: () => Promise<void>;
}

interface CameraDialogProps {
  open: boolean;
  camera: Camera | null;
  sourceTypes: { value: string; label: string }[];
  resolutions: string[];
  busy: boolean;
  onClose: () => void;
  onSubmit: (payload: Partial<Camera>) => Promise<void>;
}

function CameraDialog({ open, camera, sourceTypes, resolutions, busy, onClose, onSubmit }: CameraDialogProps) {
  const [name, setName] = useState(camera?.name ?? "");
  const [code, setCode] = useState(camera?.code ?? "");
  const [location, setLocation] = useState(camera?.location ?? "");
  const [sourceType, setSourceType] = useState(camera?.source_type ?? "demo");
  const [rtspUrl, setRtspUrl] = useState(camera?.rtsp_url ?? "");
  const [fps, setFps] = useState(String(camera?.fps ?? 8));
  const [resolution, setResolution] = useState(camera?.resolution ?? "960x540");
  const [notes, setNotes] = useState(camera?.notes ?? "");
  const [enabled, setEnabled] = useState(camera?.is_enabled ?? true);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (name.trim().length < 2) {
      setError("Give the camera a name of at least 2 characters.");
      return;
    }
    if (sourceType === "rtsp" && !rtspUrl.trim()) {
      setError("An RTSP camera needs a stream URL.");
      return;
    }
    setError("");
    await onSubmit({
      name: name.trim(),
      code: code.trim() || undefined,
      location: location.trim(),
      source_type: sourceType,
      rtsp_url: rtspUrl.trim(),
      fps: Math.max(1, Math.min(30, Number(fps) || 8)),
      resolution,
      notes: notes.trim(),
      is_enabled: enabled,
    });
  };

  return (
    <Modal
      open={open}
      title={camera ? `Edit ${camera.code}` : "Add camera"}
      subtitle={camera ? camera.name : "Register a demo, RTSP, file or webcam source"}
      onClose={onClose}
      size="lg"
      footer={
        <div className="modal__footer-row">
          <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>Cancel</button>
          <button type="submit" form="camera-form" className="btn btn--primary btn--sm" disabled={busy}>
            {busy ? <span className="spinner spinner--sm" /> : <IconCheck size={14} />}
            {camera ? "Save camera" : "Add camera"}
          </button>
        </div>
      }
    >
      <form id="camera-form" className="form-stack" onSubmit={submit}>
        {error && (
          <div className="form-error">
            <IconWarning size={15} /> {error}
          </div>
        )}
        <div className="form-grid">
          <label className="field">
            <span>Camera name *</span>
            <input value={name} required maxLength={120} onChange={(event) => setName(event.target.value)} placeholder="e.g. Main gate" />
          </label>
          <label className="field">
            <span>Camera code</span>
            <input value={code} maxLength={20} onChange={(event) => setCode(event.target.value)} placeholder="Auto, e.g. CAM-04" />
          </label>
        </div>
        <label className="field">
          <span>Location</span>
          <input value={location} maxLength={160} onChange={(event) => setLocation(event.target.value)} placeholder="e.g. North perimeter, gate 2" />
        </label>
        <div className="form-grid">
          <label className="field">
            <span>Source type</span>
            <select className="select" value={sourceType} onChange={(event) => setSourceType(event.target.value)}>
              {sourceTypes.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Resolution</span>
            <select className="select" value={resolution} onChange={(event) => setResolution(event.target.value)}>
              {resolutions.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
          </label>
        </div>
        <label className="field">
          <span>{sourceType === "rtsp" ? "RTSP stream URL *" : "Stream URL / file path"}</span>
          <input
            value={rtspUrl}
            maxLength={500}
            onChange={(event) => setRtspUrl(event.target.value)}
            placeholder={sourceType === "rtsp" ? "rtsp://user:pass@192.168.1.20:554/stream1" : "Optional for the demo source"}
          />
          <small className="field__hint">
            Demo cameras synthesise a live scene, so no hardware is required. RTSP credentials stay server-side.
          </small>
        </label>
        <div className="form-grid">
          <label className="field">
            <span>Target FPS</span>
            <input type="number" min={1} max={30} value={fps} onChange={(event) => setFps(event.target.value)} />
          </label>
          <div className="field">
            <span>Initial state</span>
            <Toggle
              checked={enabled}
              onChange={setEnabled}
              label="Enabled"
              description="Disabled cameras keep their history but stop processing."
            />
          </div>
        </div>
        <label className="field">
          <span>Notes</span>
          <textarea rows={2} value={notes} maxLength={500} onChange={(event) => setNotes(event.target.value)} placeholder="Mounting height, lens, owner or maintenance notes…" />
        </label>
      </form>
    </Modal>
  );
}

interface ZoneDialogProps {
  open: boolean;
  zone: Zone | null;
  cameras: Camera[];
  defaultCameraId: number | null;
  zoneTypes: { value: string; label: string; description: string; color: string }[];
  weekdays: { value: number; label: string }[];
  defaults: { min_dwell_seconds: number; min_frames: number; cooldown_seconds: number };
  busy: boolean;
  onClose: () => void;
  onSubmit: (payload: Partial<Zone>) => Promise<void>;
}

function ZoneDialog({
  open,
  zone,
  cameras,
  defaultCameraId,
  zoneTypes,
  weekdays,
  defaults,
  busy,
  onClose,
  onSubmit,
}: ZoneDialogProps) {
  const [cameraId, setCameraId] = useState(String(zone?.camera_id ?? defaultCameraId ?? cameras[0]?.id ?? ""));
  const [name, setName] = useState(zone?.name ?? "");
  const [zoneType, setZoneType] = useState(zone?.zone_type ?? "restricted");
  const [points, setPoints] = useState<number[][]>(zone?.points?.length ? zone.points : DEFAULT_POINTS);
  const [scheduleStart, setScheduleStart] = useState(zone?.schedule_start ?? "00:00");
  const [scheduleEnd, setScheduleEnd] = useState(zone?.schedule_end ?? "23:59");
  const [days, setDays] = useState<number[]>(zone?.days?.length ? zone.days : [0, 1, 2, 3, 4, 5, 6]);
  const [minDwell, setMinDwell] = useState(String(zone?.min_dwell_seconds ?? defaults.min_dwell_seconds));
  const [minFrames, setMinFrames] = useState(String(zone?.min_frames ?? defaults.min_frames));
  const [cooldown, setCooldown] = useState(String(zone?.cooldown_seconds ?? defaults.cooldown_seconds));
  const [color, setColor] = useState(zone?.color ?? ZONE_TYPE_COLORS[zoneType] ?? "#22d3ee");
  const [enabled, setEnabled] = useState(zone?.is_enabled ?? true);
  const [error, setError] = useState("");
  const surfaceRef = useRef<HTMLDivElement>(null);

  const selectedCamera = cameras.find((camera) => String(camera.id) === cameraId);
  const activeZoneType = zoneTypes.find((item) => item.value === zoneType);

  const addPoint = (event: ReactMouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = Math.min(0.999, Math.max(0.001, (event.clientX - rect.left) / rect.width));
    const y = Math.min(0.999, Math.max(0.001, (event.clientY - rect.top) / rect.height));
    setPoints((current) => [...current, [Number(x.toFixed(3)), Number(y.toFixed(3))]]);
  };

  const toggleDay = (value: number) => {
    setDays((current) =>
      current.includes(value) ? current.filter((day) => day !== value) : [...current, value].sort((left, right) => left - right),
    );
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!cameraId) {
      setError("Select the camera this zone belongs to.");
      return;
    }
    if (name.trim().length < 2) {
      setError("Give the zone a name of at least 2 characters.");
      return;
    }
    if (points.length < 3) {
      setError("Draw at least 3 polygon points. Click on the preview to add points.");
      return;
    }
    if (!days.length) {
      setError("Select at least one active day.");
      return;
    }
    setError("");
    await onSubmit({
      camera_id: Number(cameraId),
      name: name.trim(),
      zone_type: zoneType,
      points,
      schedule_start: scheduleStart,
      schedule_end: scheduleEnd,
      days,
      min_dwell_seconds: Number(minDwell) || 0,
      min_frames: Math.max(1, Number(minFrames) || 1),
      cooldown_seconds: Math.max(0, Number(cooldown) || 0),
      is_enabled: enabled,
      color,
    });
  };

  return (
    <Modal
      open={open}
      title={zone ? `Edit zone · ${zone.name}` : "Draw a detection zone"}
      subtitle={zone ? "Changes reach the running pipeline within a frame." : "Click the preview to place polygon points in normalized coordinates."}
      onClose={onClose}
      size="xl"
      footer={
        <div className="modal__footer-row">
          <span className="mono muted">{points.length} POINT{points.length === 1 ? "" : "S"} · {ZONE_LABELS[zoneType]}</span>
          <div className="btn-row">
            <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>Cancel</button>
            <button type="submit" form="zone-form" className="btn btn--primary btn--sm" disabled={busy}>
              {busy ? <span className="spinner spinner--sm" /> : <IconCheck size={14} />}
              {zone ? "Save zone" : "Create zone"}
            </button>
          </div>
        </div>
      }
    >
      <form id="zone-form" className="form-stack" onSubmit={submit}>
        {error && (
          <div className="form-error">
            <IconWarning size={15} /> {error}
          </div>
        )}
        <div className="zone-editor">
          <div
            ref={surfaceRef}
            className="zone-canvas"
            onClick={addPoint}
            role="img"
            aria-label="Zone polygon editor — click to add points"
          >
            {selectedCamera ? (
              <img src={`${snapshotFor(selectedCamera.id)}`} alt={selectedCamera.name} className="zone-canvas__image" draggable={false} />
            ) : (
              <div className="zone-canvas__placeholder"><IconCamera size={30} /><span>Select a camera</span></div>
            )}
            <svg className="zone-canvas__svg" viewBox="0 0 100 100" preserveAspectRatio="none">
              <defs>
                <pattern id="zone-grid" width="10" height="10" patternUnits="userSpaceOnUse">
                  <path d="M 10 0 L 0 0 0 10" fill="none" stroke="rgba(148, 197, 255, 0.18)" strokeWidth="0.25" />
                </pattern>
              </defs>
              <rect width="100" height="100" fill="url(#zone-grid)" />
              {points.length >= 3 && (
                <polygon
                  points={points.map(([x, y]) => `${x * 100},${y * 100}`).join(" ")}
                  fill={`${color}33`}
                  stroke={color}
                  strokeWidth="0.55"
                  vectorEffect="non-scaling-stroke"
                />
              )}
              {points.map(([x, y], index) => (
                <g key={`${x}-${y}-${index}`}>
                  <circle cx={x * 100} cy={y * 100} r="1.1" fill={color} stroke="#04070d" strokeWidth="0.35" />
                  <text x={x * 100 + 1.6} y={y * 100 - 1.2} fontSize="2.2" fill="#dbeafe" fontWeight="700">
                    {index + 1}
                  </text>
                </g>
              ))}
            </svg>
            <span className="zone-canvas__hint">CLICK TO ADD POINT</span>
          </div>
          <div className="zone-editor__tools">
            <div className="zone-editor__legend">
              <strong>Polygon editor</strong>
              <p>
                Points are stored in 0–1 image coordinates, so the same polygon works at any resolution. Click the preview to add a
                point; the polygon closes automatically.
              </p>
            </div>
            <div className="btn-row">
              <button
                type="button"
                className="btn btn--ghost btn--xs"
                onClick={() => setPoints((current) => current.slice(0, -1))}
                disabled={!points.length}
              >
                <IconClose size={13} /> Undo point
              </button>
              <button type="button" className="btn btn--ghost btn--xs" onClick={() => setPoints(DEFAULT_POINTS)}>
                <IconTarget size={13} /> Default rectangle
              </button>
              <button type="button" className="btn btn--ghost btn--xs" onClick={() => setPoints([])}>
                <IconTrash size={13} /> Clear
              </button>
            </div>
            <div className="zone-editor__readout">
              <span className="mono">x,y normalized</span>
              <div className="zone-editor__points">
                {points.map(([x, y], index) => (
                  <span key={`${x}-${y}-${index}`} className="mono">{index + 1}: {x.toFixed(2)}, {y.toFixed(2)}</span>
                ))}
                {!points.length && <span className="muted">No points yet.</span>}
              </div>
            </div>
          </div>
        </div>

        <div className="form-grid">
          <label className="field">
            <span>Camera *</span>
            <select className="select" value={cameraId} onChange={(event) => setCameraId(event.target.value)} disabled={Boolean(zone)}>
              {cameras.map((camera) => (
                <option key={camera.id} value={camera.id}>{camera.code} · {camera.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Zone name *</span>
            <input value={name} required maxLength={120} onChange={(event) => setName(event.target.value)} placeholder="e.g. Generator yard" />
          </label>
        </div>

        <div className="form-grid">
          <label className="field">
            <span>Zone type</span>
            <select
              className="select"
              value={zoneType}
              onChange={(event) => {
                const next = event.target.value as Zone["zone_type"];
                setZoneType(next);
                setColor(ZONE_TYPE_COLORS[next] ?? "#22d3ee");
              }}
            >
              {zoneTypes.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            <small className="field__hint">{activeZoneType?.description}</small>
          </label>
          <label className="field">
            <span>Polygon colour</span>
            <div className="color-field">
              <input type="color" value={color} onChange={(event) => setColor(event.target.value)} />
              <input value={color} maxLength={9} onChange={(event) => setColor(event.target.value)} className="mono" />
            </div>
          </label>
        </div>

        <fieldset className="field fieldset">
          <legend>Active schedule</legend>
          <div className="form-grid">
            <label className="field">
              <span>From</span>
              <input type="time" value={scheduleStart} onChange={(event) => setScheduleStart(event.target.value)} />
            </label>
            <label className="field">
              <span>To</span>
              <input type="time" value={scheduleEnd} onChange={(event) => setScheduleEnd(event.target.value)} />
            </label>
          </div>
          <div className="weekday-row">
            {weekdays.map((day) => (
              <button
                key={day.value}
                type="button"
                className={cx("weekday", days.includes(day.value) && "weekday--on")}
                onClick={() => toggleDay(day.value)}
              >
                {day.label}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset className="field fieldset">
          <legend>Verification rules</legend>
          <div className="form-grid form-grid--three">
            <label className="field">
              <span>Minimum dwell (s)</span>
              <input type="number" min={0} max={120} step={0.5} value={minDwell} onChange={(event) => setMinDwell(event.target.value)} />
            </label>
            <label className="field">
              <span>Minimum frames</span>
              <input type="number" min={1} max={120} value={minFrames} onChange={(event) => setMinFrames(event.target.value)} />
            </label>
            <label className="field">
              <span>Cooldown (s)</span>
              <input type="number" min={0} max={3600} value={cooldown} onChange={(event) => setCooldown(event.target.value)} />
            </label>
          </div>
          <small className="field__hint">
            A target must persist for both the dwell time and the frame count before an incident can be raised. The cooldown
            suppresses duplicate alarms for the same track.
          </small>
        </fieldset>

        <Toggle
          checked={enabled}
          onChange={setEnabled}
          label="Zone enabled"
          description="Disabled zones still render in the list but are ignored by detection."
        />
      </form>
    </Modal>
  );
}

function snapshotFor(cameraId: number): string {
  const token = localStorage.getItem("sentinel.token");
  return `/api/cameras/${cameraId}/snapshot${token ? `?token=${encodeURIComponent(token)}` : ""}`;
}

function streamFor(cameraId: number): string {
  const token = localStorage.getItem("sentinel.token");
  return `/api/cameras/${cameraId}/stream${token ? `?token=${encodeURIComponent(token)}` : ""}`;
}

export default function Devices() {
  useDocumentTitle("Cameras & Zones");
  const { can } = useAuth();
  const { pushToast, statsVersion } = useRealtime();
  const [tab, setTab] = useState<Tab>("cameras");
  const [zoneCameraId, setZoneCameraId] = useState<number | "all">("all");
  const [cameraDialog, setCameraDialog] = useState<{ open: boolean; camera: Camera | null }>({ open: false, camera: null });
  const [zoneDialog, setZoneDialog] = useState<{ open: boolean; zone: Zone | null }>({ open: false, zone: null });
  const [previewCamera, setPreviewCamera] = useState<Camera | null>(null);
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState<number | null>(null);
  const [autoBusy, setAutoBusy] = useState(false);

  const cameras = useResource(() => api.cameras.list(), [statsVersion]);
  const cameraMeta = useResource(() => api.cameras.meta(), []);
  const cameraDevices = useResource(() => api.cameras.discover(), []);
  const zones = useResource(() => api.zones.list(), [statsVersion]);
  const zoneMeta = useResource(() => api.zones.meta(), []);

  const canManageCameras = can("manage_cameras");
  const canManageZones = can("manage_zones");

  const cameraList = cameras.data?.items ?? [];
  const zoneList = zones.data?.items ?? [];
  const activeDeviceIndex = Number.parseInt(cameraList[0]?.rtsp_url || "0", 10) || 0;

  const selectLiveDevice = async (camera: Camera, index: number) => {
    setActionBusy(camera.id);
    try {
      await api.cameras.selectLiveDevice(camera.id, index);
      pushToast({ title: "Live camera updated", message: `${camera.code} now uses device ${index}.`, tone: "success" });
      cameras.reload();
      cameraDevices.reload();
    } catch (error) {
      pushToast({ title: "Camera switch failed", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setActionBusy(null);
    }
  };

  const autoDetectLiveDevice = async () => {
    const target = cameraList[0];
    if (!target) return;
    setAutoBusy(true);
    try {
      const result = await api.cameras.autoLiveDevice(target.id);
      pushToast({
        title: "Live camera auto-detected",
        message: `${target.code} now uses device ${result.index}; the worker is restarting.`,
        tone: "success",
      });
      cameras.reload();
      cameraDevices.reload();
    } catch (error) {
      pushToast({
        title: "Auto-detect failed",
        message: error instanceof Error ? error.message : "No working camera was found",
        tone: "danger",
      });
    } finally {
      setAutoBusy(false);
    }
  };

  const stats = useMemo(() => {
    const online = cameraList.filter((camera) => camera.is_enabled && !["offline", "error", "stopped"].includes(camera.status)).length;
    const fps = cameraList.reduce((total, camera) => total + (camera.runtime_fps ?? camera.fps ?? 0), 0);
    const threats = cameraList.reduce((total, camera) => total + camera.active_threats, 0);
    return { online, fps: Math.round(fps), threats };
  }, [cameraList]);

  const filteredZones = useMemo(
    () => (zoneCameraId === "all" ? zoneList : zoneList.filter((zone) => zone.camera_id === zoneCameraId)),
    [zoneList, zoneCameraId],
  );

  const saveCamera = async (payload: Partial<Camera>) => {
    setBusy(true);
    try {
      if (cameraDialog.camera) {
        await api.cameras.update(cameraDialog.camera.id, payload);
        pushToast({ title: "Camera updated", message: `${payload.name ?? cameraDialog.camera.code} saved`, tone: "success" });
      } else {
        await api.cameras.create(payload);
        pushToast({ title: "Camera added", message: `${payload.name ?? "New camera"} is starting`, tone: "success" });
      }
      setCameraDialog({ open: false, camera: null });
      cameras.reload();
    } catch (error) {
      pushToast({
        title: "Could not save camera",
        message: error instanceof Error ? error.message : "Request failed",
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  };

  const toggleCamera = async (camera: Camera) => {
    setActionBusy(camera.id);
    try {
      await api.cameras.update(camera.id, { is_enabled: !camera.is_enabled });
      pushToast({
        title: camera.is_enabled ? "Camera disabled" : "Camera enabled",
        message: `${camera.code} · ${camera.name}`,
        tone: camera.is_enabled ? "warning" : "success",
      });
      cameras.reload();
    } catch (error) {
      pushToast({ title: "Could not change camera", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setActionBusy(null);
    }
  };

  const restartCamera = async (camera: Camera) => {
    setActionBusy(camera.id);
    try {
      await api.cameras.restart(camera.id);
      pushToast({ title: "Worker restarting", message: `${camera.code} will reconnect in a few seconds`, tone: "info" });
      cameras.reload();
    } catch (error) {
      pushToast({ title: "Restart failed", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setActionBusy(null);
    }
  };

  const captureSnapshot = async (camera: Camera) => {
    setActionBusy(camera.id);
    try {
      const recording = await api.cameras.capture(camera.id);
      pushToast({
        title: "Snapshot captured",
        message: `${camera.code} · saved to the evidence archive (${recording.kind})`,
        tone: "success",
      });
    } catch (error) {
      pushToast({ title: "Snapshot failed", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setActionBusy(null);
    }
  };

  const requestDeleteCamera = (camera: Camera) => {
    setConfirmRequest({
      title: `Delete ${camera.code}?`,
      message:
        "Cameras with evidence history cannot be deleted. If this camera has incidents or events the server will refuse and ask you to disable it instead.",
      confirmLabel: "Delete camera",
      action: async () => {
        await api.cameras.remove(camera.id);
        pushToast({ title: "Camera deleted", message: `${camera.code} removed`, tone: "success" });
        cameras.reload();
      },
    });
  };

  const saveZone = async (payload: Partial<Zone>) => {
    setBusy(true);
    try {
      if (zoneDialog.zone) {
        await api.zones.update(zoneDialog.zone.id, payload);
        pushToast({ title: "Zone updated", message: payload.name ?? zoneDialog.zone.name, tone: "success" });
      } else {
        await api.zones.create(payload);
        pushToast({ title: "Zone created", message: `${payload.name ?? "Zone"} is now protecting the area`, tone: "success" });
      }
      setZoneDialog({ open: false, zone: null });
      zones.reload();
      cameras.reload();
    } catch (error) {
      pushToast({
        title: "Could not save zone",
        message: error instanceof Error ? error.message : "Request failed",
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  };

  const toggleZone = async (zone: Zone) => {
    try {
      await api.zones.update(zone.id, { is_enabled: !zone.is_enabled });
      zones.reload();
    } catch (error) {
      pushToast({ title: "Could not change zone", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    }
  };

  const requestDeleteZone = (zone: Zone) => {
    setConfirmRequest({
      title: `Delete zone “${zone.name}”?`,
      message: "Historical events and incidents are kept, but they lose their zone link. The polygon stops protecting the area immediately.",
      confirmLabel: "Delete zone",
      action: async () => {
        await api.zones.remove(zone.id);
        pushToast({ title: "Zone deleted", message: `${zone.name} removed`, tone: "success" });
        zones.reload();
        cameras.reload();
      },
    });
  };

  const runConfirm = async () => {
    if (!confirmRequest) return;
    setBusy(true);
    try {
      await confirmRequest.action();
      setConfirmRequest(null);
    } catch (error) {
      pushToast({ title: "Action failed", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setBusy(false);
    }
  };

  const sourceTypes = cameraMeta.data?.source_types ?? [
    { value: "demo", label: "Synthetic demo feed" },
    { value: "rtsp", label: "RTSP / IP camera" },
    { value: "file", label: "Video file" },
    { value: "webcam", label: "Local webcam" },
  ];
  const resolutions = cameraMeta.data?.resolutions ?? ["640x360", "960x540", "1280x720", "1920x1080"];
  const recordingLabel = cameraMeta.data
    ? cameraMeta.data.continuous_recording_enabled
      ? "continuous video is being saved"
      : cameraMeta.data.evidence_saved
        ? "event evidence is being saved"
        : "recording is disabled"
    : "checking recording state";
  const hiddenInactive = cameraDevices.data?.hidden_inactive ?? 0;
  const discoveryLabel = hiddenInactive
    ? `Physical cameras detected · ${hiddenInactive} inactive input hidden · ${recordingLabel}`
    : `Physical cameras detected on this computer · ${recordingLabel}`;

  return (
    <div className="page page--devices">
      <div className="page-toolbar">
        <div className="page-toolbar__left">
          <span className={cx("live-chip", stats.threats > 0 && "live-chip--danger")}>
            <span className="live-chip__dot" /> DEVICE FLEET
          </span>
          <span className="muted">
            {stats.online}/{cameraList.length} cameras online · {zoneList.length} detection zones · AI pipeline{" "}
            {cameras.data?.supervisor_running ? "running" : "stopped"}
          </span>
        </div>
        <div className="page-toolbar__actions">
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => { cameras.reload(); zones.reload(); }}>
            <IconRefresh size={14} /> Refresh
          </button>
          {tab === "cameras" ? (
            <button
              type="button"
              className="btn btn--primary btn--sm"
              onClick={() => setCameraDialog({ open: true, camera: null })}
              disabled={!canManageCameras}
            >
              <IconPlus size={14} /> Add camera
            </button>
          ) : (
            <button
              type="button"
              className="btn btn--primary btn--sm"
              onClick={() => setZoneDialog({ open: true, zone: null })}
              disabled={!canManageZones || !cameraList.length}
            >
              <IconPlus size={14} /> Draw zone
            </button>
          )}
        </div>
      </div>

      <div className="stat-strip">
        <div className="stat-tile stat-tile--green">
          <span className="stat-tile__icon"><IconCamera size={18} /></span>
          <span>
            <small>Cameras online</small>
            <strong>{stats.online}<em>/{cameraList.length}</em></strong>
            <em>{cameraList.filter((camera) => !camera.is_enabled).length} disabled</em>
          </span>
        </div>
        <div className="stat-tile stat-tile--cyan">
          <span className="stat-tile__icon"><IconTarget size={18} /></span>
          <span>
            <small>Detection zones</small>
            <strong>{zoneList.length}</strong>
            <em>{zoneList.filter((zone) => zone.is_enabled).length} active polygons</em>
          </span>
        </div>
        <div className="stat-tile stat-tile--amber">
          <span className="stat-tile__icon"><IconEye size={18} /></span>
          <span>
            <small>Pipeline throughput</small>
            <strong>{stats.fps}<em> fps</em></strong>
            <em>Across all workers</em>
          </span>
        </div>
        <div className={cx("stat-tile", stats.threats > 0 ? "stat-tile--red" : "stat-tile--green")}>
          <span className="stat-tile__icon"><IconWarning size={18} /></span>
          <span>
            <small>Active camera threats</small>
            <strong>{stats.threats}</strong>
            <em>{stats.threats > 0 ? "Open incidents linked to cameras" : "No open camera incidents"}</em>
          </span>
        </div>
      </div>

      <div className="tabs">
        <button type="button" className={cx("tab", tab === "cameras" && "tab--active")} onClick={() => setTab("cameras")}>
          <IconCamera size={15} /> Cameras <span className="tab__count">{cameraList.length}</span>
        </button>
        <button type="button" className={cx("tab", tab === "zones" && "tab--active")} onClick={() => setTab("zones")}>
          <IconTarget size={15} /> Zones <span className="tab__count">{zoneList.length}</span>
        </button>
        <span className="tabs__note">
          {canManageCameras || canManageZones ? "Your role can modify this device fleet." : "Read-only device view."}
        </span>
      </div>

      {tab === "cameras" ? (
        <>
          <Panel
            title="Live camera devices"
            subtitle={discoveryLabel}
            accent="cyan"
            bodyClassName="panel__body--tight"
            actions={
              <>
                <button
                  type="button"
                  className="btn btn--primary btn--xs"
                  disabled={!canManageCameras || !cameraList.length || autoBusy}
                  onClick={() => void autoDetectLiveDevice()}
                  title="Scan every device and use the first one with a live image"
                >
                  {autoBusy ? <span className="spinner spinner--sm" /> : <IconTarget size={13} />}
                  Auto-detect live camera
                </button>
                <button type="button" className="btn btn--ghost btn--xs" onClick={cameraDevices.reload}>
                  <IconRefresh size={13} /> Rescan devices
                </button>
              </>
            }
          >
            {cameraDevices.data?.items.length ? (
              <div className="live-device-list">
                {cameraDevices.data.items.map((device) => (
                  <div
                    key={device.index}
                    className={cx("live-device", device.index === activeDeviceIndex && "live-device--active")}
                  >
                    <span className={cx("status-dot", device.has_signal ? "status-dot--online" : "status-dot--offline")} />
                    <span className="live-device__body">
                      <strong>Device {device.index}</strong>
                      <small>
                        {device.width && device.height ? `${device.width}x${device.height} · ` : ""}
                        {device.has_signal ? "Live image detected" : device.note || "Connected but no image"}
                        {device.backend ? ` · ${device.backend.toUpperCase()}` : ""}
                      </small>
                    </span>
                    {cameraList[0] && (
                      <button
                        type="button"
                        className="btn btn--ghost btn--xs"
                        disabled={!canManageCameras || actionBusy === cameraList[0].id}
                        onClick={() => void selectLiveDevice(cameraList[0], device.index)}
                      >
                        Use live
                      </button>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                title="No cameras detected"
                message="Connect a webcam and allow desktop camera access, then rescan or auto-detect a live device."
              />
            )}
          </Panel>

          {cameras.loading && !cameras.data ? (
          <LoadingState label="Loading camera fleet…" />
        ) : cameras.error ? (
          <ErrorState message={cameras.error} retry={cameras.reload} />
        ) : cameraList.length ? (
          <div className="device-grid">
            {cameraList.map((camera) => {
              return (
                <article key={camera.id} className={cx("device-card", !camera.is_enabled && "device-card--offline")}>
                  <div className="device-card__media">
                    <img src={streamFor(camera.id)} alt={`${camera.name} live feed`} />
                    <div className="device-card__overlay">
                      <TonePill tone={statusTone(camera.status)}>
                        <span className={cx("status-dot", `status-dot--${statusTone(camera.status) === "green" ? "online" : "offline"}`)} />
                        {(camera.status || "unknown").toUpperCase()}
                      </TonePill>
                      {camera.active_threats > 0 && (
                        <span className="device-card__threat">
                          <IconWarning size={13} /> {camera.active_threats} THREAT{camera.active_threats === 1 ? "" : "S"}
                        </span>
                      )}
                    </div>
                    <span className="device-card__scan" />
                    <button type="button" className="device-card__expand" onClick={() => setPreviewCamera(camera)} title="Open live feed">
                      <IconExpand />
                    </button>
                  </div>
                  <div className="device-card__body">
                    <header className="device-card__head">
                      <div>
                        <strong>{camera.name}</strong>
                        <small>{camera.location || "Location not recorded"}</small>
                      </div>
                      <span className="mono muted">{camera.code}</span>
                    </header>
                    <dl className="device-facts">
                      <div><dt>Source</dt><dd>{humanize(camera.source_type)}</dd></div>
                      <div><dt>Resolution</dt><dd className="mono">{camera.resolution}</dd></div>
                      <div><dt>Live FPS</dt><dd className="mono">{camera.runtime_fps ?? camera.fps}</dd></div>
                      <div><dt>Zones</dt><dd>{camera.zones_count}</dd></div>
                      <div><dt>Last seen</dt><dd>{camera.last_seen_at ? formatRelative(camera.last_seen_at) : "—"}</dd></div>
                      <div><dt>Frames</dt><dd className="mono">{camera.runtime_frames ?? "—"}</dd></div>
                    </dl>
                    <div className="device-card__footer">
                      <div className="device-card__actions">
                        <button type="button" className="icon-btn" title="Live feed" onClick={() => setPreviewCamera(camera)}>
                          <IconEye size={15} />
                        </button>
                        <button
                          type="button"
                          className="icon-btn"
                          title="Capture snapshot"
                          onClick={() => void captureSnapshot(camera)}
                          disabled={actionBusy === camera.id || !camera.is_enabled}
                        >
                          <IconCamera size={15} />
                        </button>
                        <button
                          type="button"
                          className="icon-btn"
                          title="Restart worker"
                          onClick={() => void restartCamera(camera)}
                          disabled={actionBusy === camera.id || !camera.is_enabled}
                        >
                          <IconRefresh size={15} />
                        </button>
                        {canManageCameras && (
                          <>
                            <button type="button" className="icon-btn" title="Edit camera" onClick={() => setCameraDialog({ open: true, camera })}>
                              <IconEdit size={15} />
                            </button>
                            <button type="button" className="icon-btn icon-btn--danger" title="Delete camera" onClick={() => requestDeleteCamera(camera)}>
                              <IconTrash size={15} />
                            </button>
                          </>
                        )}
                      </div>
                      <button
                        type="button"
                        className={cx("switch switch--sm", camera.is_enabled && "switch--on")}
                        role="switch"
                        aria-checked={camera.is_enabled}
                        disabled={!canManageCameras || actionBusy === camera.id}
                        onClick={() => void toggleCamera(camera)}
                        title={camera.is_enabled ? "Disable camera" : "Enable camera"}
                      >
                        <span className="switch__thumb" />
                      </button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <Panel>
            <EmptyState
              icon={<IconCamera size={28} />}
              title="No cameras registered"
              message="Connect a physical webcam or add an RTSP source, then auto-detect the live device."
              action={
                canManageCameras ? (
                  <button type="button" className="btn btn--primary btn--sm" onClick={() => setCameraDialog({ open: true, camera: null })}>
                    <IconPlus size={14} /> Add camera
                  </button>
                ) : undefined
              }
            />
          </Panel>
          )}
        </>
      ) : (
        <div className="zones-layout">
          <div className="zones-layout__main">
            <Panel
              title="Detection zones"
              subtitle="Polygons define where a target becomes a threat"
              bodyClassName="panel__body--flush"
              actions={
                <select
                  className="select select--sm"
                  value={String(zoneCameraId)}
                  onChange={(event) => setZoneCameraId(event.target.value === "all" ? "all" : Number(event.target.value))}
                >
                  <option value="all">All cameras</option>
                  {cameraList.map((camera) => (
                    <option key={camera.id} value={camera.id}>{camera.code} · {camera.name}</option>
                  ))}
                </select>
              }
            >
              {zones.loading && !zones.data ? (
                <LoadingState label="Loading zones…" />
              ) : zones.error ? (
                <ErrorState message={zones.error} retry={zones.reload} />
              ) : filteredZones.length ? (
                <div className="zone-list">
                  {filteredZones.map((zone) => {
                    const camera = cameraList.find((item) => item.id === zone.camera_id);
                    const typeColor = zone.color || ZONE_TYPE_COLORS[zone.zone_type] || "#22d3ee";
                    return (
                      <div key={zone.id} className={cx("zone-row", !zone.is_enabled && "zone-row--off")}>
                        <span className="zone-row__swatch" style={{ background: `${typeColor}22`, borderColor: typeColor, color: typeColor }}>
                          <IconTarget size={18} />
                        </span>
                        <div className="zone-row__body">
                          <div className="zone-row__head">
                            <strong>{zone.name}</strong>
                            <TonePill tone={zone.zone_type === "restricted" ? "red" : zone.zone_type === "limited" ? "amber" : "cyan"}>
                              {ZONE_LABELS[zone.zone_type]}
                            </TonePill>
                            {!zone.is_enabled && <TonePill tone="muted">DISABLED</TonePill>}
                          </div>
                          <span className="muted">
                            {camera ? `${camera.code} · ${camera.name}` : `Camera ${zone.camera_id}`} · {zone.schedule_label ?? `${zone.schedule_start}–${zone.schedule_end}`}
                          </span>
                          <div className="zone-row__meta">
                            <span><IconShield size={13} /> {zone.min_frames} frames · {zone.min_dwell_seconds}s dwell</span>
                            <span><IconRefresh size={13} /> {zone.cooldown_seconds}s cooldown</span>
                            <span><IconTarget size={13} /> {zone.points.length} points</span>
                          </div>
                        </div>
                        <div className="zone-row__actions">
                          <button
                            type="button"
                            className={cx("switch switch--sm", zone.is_enabled && "switch--on")}
                            role="switch"
                            aria-checked={zone.is_enabled}
                            disabled={!canManageZones}
                            onClick={() => void toggleZone(zone)}
                            title={zone.is_enabled ? "Disable zone" : "Enable zone"}
                          >
                            <span className="switch__thumb" />
                          </button>
                          <button
                            type="button"
                            className="icon-btn"
                            title="Edit zone"
                            disabled={!canManageZones}
                            onClick={() => setZoneDialog({ open: true, zone })}
                          >
                            <IconEdit size={15} />
                          </button>
                          <button
                            type="button"
                            className="icon-btn icon-btn--danger"
                            title="Delete zone"
                            disabled={!canManageZones}
                            onClick={() => requestDeleteZone(zone)}
                          >
                            <IconTrash size={15} />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <EmptyState
                  icon={<IconTarget size={28} />}
                  title="No detection zones"
                  message="Without a zone every detection is treated as public-area context and risk stays low."
                  action={
                    canManageZones && cameraList.length ? (
                      <button type="button" className="btn btn--primary btn--sm" onClick={() => setZoneDialog({ open: true, zone: null })}>
                        <IconPlus size={14} /> Draw the first zone
                      </button>
                    ) : undefined
                  }
                />
              )}
            </Panel>

            <Panel title="Zone risk model" subtitle="Zone sensitivity contributes the largest share of the score" accent="red">
              <div className="zone-type-grid">
                {(zoneMeta.data?.zone_types ?? []).map((type) => (
                  <div key={type.value} className="zone-type-card" style={{ borderColor: `${type.color}55` }}>
                    <span className="zone-type-card__dot" style={{ background: type.color }} />
                    <strong>{type.label}</strong>
                    <p>{type.description}</p>
                    <span className="mono muted">
                      {zoneList.filter((zone) => zone.zone_type === type.value).length} zone(s) configured
                    </span>
                  </div>
                ))}
              </div>
              <p className="safety-note">
                <IconWarning size={15} />
                A polygon that is too small or badly placed will miss targets. Use the live snapshot while drawing and keep the
                zone clear of reflective surfaces.
              </p>
            </Panel>
          </div>

          <aside className="zones-layout__side">
            <Panel title="Camera coverage" subtitle="Zones per camera" bodyClassName="panel__body--flush">
              <div className="coverage-list">
                {cameraList.map((camera) => {
                  const count = zoneList.filter((zone) => zone.camera_id === camera.id).length;
                  return (
                    <button
                      key={camera.id}
                      type="button"
                      className="coverage-row"
                      onClick={() => setZoneCameraId(camera.id)}
                    >
                      <span className={cx("status-dot", camera.is_enabled ? "status-dot--online" : "status-dot--offline")} />
                      <span>
                        <strong>{camera.code}</strong>
                        <small>{camera.name}</small>
                      </span>
                      <span className={cx("coverage-row__count", count === 0 && "is-zero")}>{count}</span>
                    </button>
                  );
                })}
              </div>
            </Panel>

            <Panel title="Zone defaults" subtitle="Applied to new polygons">
              <ul className="plain-list">
                <li><IconClock size={14} /> Minimum dwell: <strong>{zoneMeta.data?.defaults.min_dwell_seconds ?? 2}s</strong></li>
                <li><IconTarget size={14} /> Minimum frames: <strong>{zoneMeta.data?.defaults.min_frames ?? 6}</strong></li>
                <li><IconRefresh size={14} /> Cooldown: <strong>{zoneMeta.data?.defaults.cooldown_seconds ?? 90}s</strong></li>
                <li><IconDatabase size={14} /> Coordinates: normalized 0–1</li>
              </ul>
              <p className="safety-note">
                <IconShield size={15} />
                Every zone change is written to the audit log with the acting user and affected camera.
              </p>
            </Panel>

            <Panel title="Pipeline health" subtitle="Live worker state">
              <div className="health-mini">
                <div>
                  <span>Supervisor</span>
                  <strong className={cameras.data?.supervisor_running ? "text-green" : "text-danger"}>
                    {cameras.data?.supervisor_running ? "RUNNING" : "STOPPED"}
                  </strong>
                </div>
                <div>
                  <span>Demo mode</span>
                  <strong>{cameraMeta.data?.demo_mode ? "ON" : "OFF"}</strong>
                </div>
                <div>
                  <span>Max FPS</span>
                  <strong>{cameraMeta.data?.max_fps ?? 30}</strong>
                </div>
                <div>
                  <span>Detector</span>
                  <strong>{cameraMeta.data?.detector_modes.join(" / ") ?? "auto"}</strong>
                </div>
              </div>
              <Link to="/settings" className="btn btn--ghost btn--sm btn--block">
                <IconCamera size={14} /> AI & recording settings
              </Link>
            </Panel>
          </aside>
        </div>
      )}

      {cameraDialog.open && (
        <CameraDialog
          key={cameraDialog.camera?.id ?? "new-camera"}
          open
          camera={cameraDialog.camera}
          sourceTypes={sourceTypes}
          resolutions={resolutions}
          busy={busy}
          onClose={() => setCameraDialog({ open: false, camera: null })}
          onSubmit={saveCamera}
        />
      )}

      {zoneDialog.open && (
        <ZoneDialog
          key={zoneDialog.zone?.id ?? `new-zone-${zoneCameraId}`}
          open
          zone={zoneDialog.zone}
          cameras={cameraList}
          defaultCameraId={zoneCameraId === "all" ? null : zoneCameraId}
          zoneTypes={zoneMeta.data?.zone_types ?? []}
          weekdays={zoneMeta.data?.weekdays ?? []}
          defaults={zoneMeta.data?.defaults ?? { min_dwell_seconds: 2, min_frames: 6, cooldown_seconds: 90 }}
          busy={busy}
          onClose={() => setZoneDialog({ open: false, zone: null })}
          onSubmit={saveZone}
        />
      )}

      <Modal
        open={Boolean(previewCamera)}
        onClose={() => setPreviewCamera(null)}
        title={previewCamera ? `${previewCamera.code} · ${previewCamera.name}` : "Live camera"}
        subtitle={previewCamera?.location}
        size="xl"
        footer={
          previewCamera ? (
            <div className="modal__footer-row">
              <span className="mono muted">
                {previewCamera.resolution} · {previewCamera.runtime_fps ?? previewCamera.fps} FPS ·{" "}
                {previewCamera.last_seen_at ? formatTime(previewCamera.last_seen_at, true) : "no frame yet"}
              </span>
              <div className="btn-row">
                <Link to={`/playback?camera=${previewCamera.id}`} className="btn btn--ghost btn--sm" onClick={() => setPreviewCamera(null)}>
                  <IconPlayback size={14} /> Evidence
                </Link>
                <button type="button" className="btn btn--danger btn--sm" onClick={() => setPreviewCamera(null)}>
                  Close feed
                </button>
              </div>
            </div>
          ) : null
        }
      >
        {previewCamera && (
          <div className="camera-preview">
            <div className="camera-preview__stage">
              <img src={streamFor(previewCamera.id)} alt={`${previewCamera.name} live stream`} />
              <span className="camera-preview__hud">
                <span className="live-chip live-chip--danger"><span className="live-chip__dot" /> LIVE</span>
                <span className="mono">{previewCamera.code}</span>
              </span>
            </div>
            <div className="camera-preview__facts">
              <div><span>Status</span><strong>{humanize(previewCamera.status)}</strong></div>
              <div><span>Source</span><strong>{humanize(previewCamera.source_type)}</strong></div>
              <div><span>Zones</span><strong>{previewCamera.zones_count}</strong></div>
              <div><span>Active threats</span><strong className={previewCamera.active_threats ? "text-danger" : ""}>{previewCamera.active_threats}</strong></div>
              <div><span>Frames processed</span><strong className="mono">{previewCamera.runtime_frames ?? "—"}</strong></div>
              <div><span>RTSP URL</span><strong className="mono">{previewCamera.rtsp_url ? "configured" : "not required"}</strong></div>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={Boolean(confirmRequest)}
        onClose={() => setConfirmRequest(null)}
        title={confirmRequest?.title ?? "Confirm action"}
        subtitle="This action is recorded in the audit log."
        size="sm"
        footer={
          <div className="modal__footer-row">
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => setConfirmRequest(null)} disabled={busy}>
              Cancel
            </button>
            <button type="button" className="btn btn--danger btn--sm" onClick={() => void runConfirm()} disabled={busy}>
              {busy ? <span className="spinner spinner--sm" /> : <IconTrash size={14} />} {confirmRequest?.confirmLabel ?? "Confirm"}
            </button>
          </div>
        }
      >
        <p className="confirm-text">{confirmRequest?.message}</p>
      </Modal>
    </div>
  );
}

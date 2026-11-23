/** Direct live camera viewer — always reads the camera, never stored media. */

import { useRef, useState } from "react";
import { api, streamUrl } from "../api";
import { useAuth } from "../context/AuthContext";
import { useNow, useResource } from "../hooks/useResource";
import { cx, formatTime } from "../lib/format";
import { IconCamera, IconExpand, IconRefresh, IconTarget } from "./Icons";

interface LiveCameraInfo {
  id: number;
  name: string;
  code: string;
  location: string;
  status: string;
  rtsp_url?: string;
}

interface LiveCameraViewProps {
  camera: LiveCameraInfo;
  cameras: LiveCameraInfo[];
  onSelect?: (camera: LiveCameraInfo) => void;
  onDeviceChange?: () => void;
  compact?: boolean;
}

function deviceSummary(device: { index: number; has_signal: boolean; note?: string; width: number; height: number }) {
  const state = device.has_signal ? "live image" : device.note || "no signal";
  return `Device ${device.index} · ${state}${device.width ? ` · ${device.width}x${device.height}` : ""}`;
}

export default function LiveCameraView({
  camera,
  cameras,
  onSelect,
  onDeviceChange,
  compact = false,
}: LiveCameraViewProps) {
  const frameRef = useRef<HTMLDivElement>(null);
  const { can } = useAuth();
  const now = useNow(1000);
  const [busy, setBusy] = useState(false);
  const [deviceError, setDeviceError] = useState("");
  const devices = useResource(() => api.cameras.discover(), []);
  const system = useResource(() => api.system.info(), []);
  const evidenceSaved = system.data?.evidence_saved ?? false;
  const continuous = system.data?.continuous_recording_enabled ?? false;
  const webcamBackend = system.data?.webcam_backend ?? devices.data?.backend;
  const activeIndex =
    Number.parseInt(camera.rtsp_url || "", 10) || devices.data?.active_index || 0;
  const activeDevice = devices.data?.items.find((device) => device.index === activeIndex);
  const offline = camera.status !== "online";

  const recordingLabel = continuous
    ? evidenceSaved
      ? "continuous video + event evidence saved to disk"
      : "continuous video saved to disk"
    : evidenceSaved
      ? "event snapshots + clips saved to disk"
      : "nothing saved to disk";

  const selectDevice = async (index: number) => {
    if (index === activeIndex || busy) return;
    setBusy(true);
    setDeviceError("");
    try {
      await api.cameras.selectLiveDevice(camera.id, index);
      devices.reload();
      onDeviceChange?.();
    } catch (error) {
      setDeviceError(error instanceof Error ? error.message : "Device switch failed");
    } finally {
      setBusy(false);
    }
  };

  const autoDetect = async () => {
    if (busy) return;
    setBusy(true);
    setDeviceError("");
    try {
      await api.cameras.autoLiveDevice(camera.id);
      devices.reload();
      onDeviceChange?.();
    } catch (error) {
      setDeviceError(error instanceof Error ? error.message : "No working camera was found");
    } finally {
      setBusy(false);
    }
  };

  const goFullscreen = () => {
    const element = frameRef.current;
    if (element?.requestFullscreen) void element.requestFullscreen();
  };

  return (
    <div className={cx("live-view", compact && "live-view--compact")}>
      <div className="live-view__toolbar">
        <span className="live-chip live-chip--sm">
          <span className={cx("live-chip__dot", offline && "live-chip__dot--offline")} />
          {offline ? "CAMERA OFFLINE" : "LIVE CAMERA"}
        </span>
        <span className="live-view__name">
          <IconCamera size={14} /> {camera.code} · {camera.name}
        </span>
        <span className="live-view__clock mono">{formatTime(new Date(now).toISOString(), true)}</span>
        <div className="live-view__actions">
          {cameras.length > 1 && (
            <select
              className="select select--sm"
              value={camera.id}
              onChange={(event) => {
                const next = cameras.find((item) => item.id === Number(event.target.value));
                if (next) onSelect?.(next);
              }}
              aria-label="Select camera"
            >
              {cameras.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.code} · {item.name}
                </option>
              ))}
            </select>
          )}
          {can("manage_cameras") && (
            <button
              type="button"
              className="btn btn--ghost btn--xs"
              title="Find the first camera that produces a live image"
              disabled={busy}
              onClick={() => void autoDetect()}
            >
              {busy ? <span className="spinner spinner--sm" /> : <IconTarget size={13} />}
              Find live camera
            </button>
          )}
          {can("manage_cameras") && devices.data?.items.length ? (
            <select
              className="select select--sm"
              value={activeIndex}
              disabled={busy}
              onChange={(event) => void selectDevice(Number(event.target.value))}
              aria-label="Select camera device"
            >
              {devices.data.items.map((device) => (
                <option key={device.index} value={device.index} title={device.note}>
                  {deviceSummary(device)}
                </option>
              ))}
            </select>
          ) : null}
          <button type="button" className="icon-btn" title="Rescan camera devices" onClick={devices.reload}>
            <IconRefresh size={14} />
          </button>
          <button type="button" className="icon-btn" title="Fullscreen" onClick={goFullscreen}>
            <IconExpand size={14} />
          </button>
        </div>
      </div>

      <div className="live-view__frame" ref={frameRef}>
        <img
          key={`${camera.id}-${camera.rtsp_url}`}
          src={streamUrl(camera.id)}
          alt={`Live feed from ${camera.name}`}
        />
        <span className="live-view__corner live-view__corner--tl" />
        <span className="live-view__corner live-view__corner--tr" />
        <span className="live-view__corner live-view__corner--bl" />
        <span className="live-view__corner live-view__corner--br" />
        {offline && (
          <div className="live-view__offline">
            <strong>NO CAMERA SIGNAL</strong>
            <span>Check that the camera is connected and enabled, then rescan or auto-detect devices.</span>
          </div>
        )}
      </div>

      <div className="live-view__footer">
        <span>
          <strong>DIRECT FROM PHYSICAL CAMERA</strong> · frames streamed live in memory ·{" "}
          {recordingLabel}
          {deviceError ? ` · ${deviceError}` : ""}
        </span>
        <span className="mono">
          {activeDevice
            ? `DEVICE ${activeDevice.index} · ${activeDevice.has_signal ? "SIGNAL OK" : "BLANK FRAME"}${
                activeDevice.backend ? ` · ${activeDevice.backend.toUpperCase()}` : ""
              }`
            : `DEVICE ${activeIndex}`}
          {webcamBackend ? ` · ${String(webcamBackend).toUpperCase()} BACKEND` : ""}
        </span>
      </div>
    </div>
  );
}

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useRealtime } from "../context/RealtimeContext";
import { useDocumentTitle, useResource } from "../hooks/useResource";
import { cx, formatDateTime, formatRelative, formatTime, humanize } from "../lib/format";
import type { EventItem } from "../types";
import {
  IconCamera,
  IconEye,
  IconRefresh,
  IconTarget,
  IconVehicles,
  IconWarning,
} from "../components/Icons";
import {
  BarList,
  EmptyState,
  ErrorState,
  LevelBadge,
  LoadingState,
  Modal,
  Panel,
  TonePill,
} from "../components/UI";

export default function Vehicles() {
  useDocumentTitle("Vehicle Activity");
  const { statsVersion } = useRealtime();
  const [cameraId, setCameraId] = useState("");
  const [selected, setSelected] = useState<EventItem | null>(null);

  const cameras = useResource(() => api.cameras.list(), []);
  const stats = useResource(() => api.events.stats(24), [statsVersion]);
  const filterKey = [cameraId, statsVersion].join("|");
  const events = useResource(
    () => api.events.list({ target_type: "vehicle", camera_id: cameraId || undefined, limit: 60 }),
    [filterKey],
  );
  const incidents = useResource(
    () => api.incidents.list({ incident_type: "vehicle_intrusion", limit: 8 }),
    [statsVersion],
  );

  const items = events.data?.items ?? [];

  const uniqueTracks = useMemo(() => {
    const map = new Map<string, EventItem>();
    items.forEach((event) => {
      const key = event.track_id || `event-${event.id}`;
      if (!map.has(key)) map.set(key, event);
    });
    return [...map.values()];
  }, [items]);

  const classes = useMemo(() => {
    const counts = new Map<string, number>();
    items.forEach((event) => {
      const raw = event.meta?.vehicle_type ?? event.meta?.label ?? event.meta?.class ?? "Vehicle";
      const label = humanize(String(raw));
      counts.set(label, (counts.get(label) ?? 0) + 1);
    });
    return [...counts.entries()]
      .map(([label, value]) => ({ label, value }))
      .sort((left, right) => right.value - left.value)
      .slice(0, 6);
  }, [items]);

  const vehicleCount24h = stats.data?.by_target.find((item) => item.target_type === "vehicle")?.count ?? 0;
  const camerasWithVehicles = stats.data?.by_camera.length ?? 0;
  const threatened = items.filter((event) => event.is_threat).length;

  return (
    <div className="page page--vehicles">
      <div className="page-toolbar">
        <div className="page-toolbar__left">
          <span className="live-chip">
            <span className="live-chip__dot" /> VEHICLE INTELLIGENCE
          </span>
          <span className="muted">
            {vehicleCount24h} vehicle detections in 24h · {uniqueTracks.length} unique tracks on this view · classification by AI
          </span>
        </div>
        <div className="page-toolbar__actions">
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => { events.reload(); incidents.reload(); stats.reload(); }}>
            <IconRefresh size={14} /> Refresh
          </button>
          <Link to="/events?q=vehicle" className="btn btn--primary btn--sm">
            <IconTarget size={14} /> Full event search
          </Link>
        </div>
      </div>

      <div className="stat-strip">
        <div className="stat-tile stat-tile--cyan">
          <span className="stat-tile__icon"><IconVehicles size={18} /></span>
          <span>
            <small>Vehicle detections · 24h</small>
            <strong>{vehicleCount24h}</strong>
            <em>All cameras</em>
          </span>
        </div>
        <div className="stat-tile stat-tile--green">
          <span className="stat-tile__icon"><IconTarget size={18} /></span>
          <span>
            <small>Unique tracks</small>
            <strong>{uniqueTracks.length}</strong>
            <em>Current result set</em>
          </span>
        </div>
        <div className="stat-tile stat-tile--amber">
          <span className="stat-tile__icon"><IconWarning size={18} /></span>
          <span>
            <small>Verified vehicle threats</small>
            <strong>{threatened}</strong>
            <em>Restricted-zone intrusions</em>
          </span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile__icon"><IconCamera size={18} /></span>
          <span>
            <small>Reporting cameras</small>
            <strong>{camerasWithVehicles}</strong>
            <em>In the last 24 hours</em>
          </span>
        </div>
      </div>

      <div className="vehicles-layout">
        <div className="vehicles-layout__main">
          <Panel
            title="Vehicle detections"
            subtitle="Every tracked vehicle with its zone verdict"
            bodyClassName="panel__body--flush"
            actions={
              <select className="select select--sm" value={cameraId} onChange={(event) => setCameraId(event.target.value)}>
                <option value="">All cameras</option>
                {cameras.data?.items.map((camera) => (
                  <option key={camera.id} value={camera.id}>{camera.code} · {camera.name}</option>
                ))}
              </select>
            }
          >
            {events.loading && !events.data ? (
              <LoadingState label="Loading vehicle detections…" />
            ) : events.error ? (
              <ErrorState message={events.error} retry={events.reload} />
            ) : items.length ? (
              <div className="vehicle-grid">
                {items.map((event) => (
                  <button
                    type="button"
                    key={event.id}
                    className={cx("vehicle-card", event.is_threat && "vehicle-card--threat")}
                    onClick={() => setSelected(event)}
                  >
                    <span className="vehicle-card__media">
                      {event.snapshot_url ? (
                        <img src={event.snapshot_url} alt="Vehicle detection" loading="lazy" />
                      ) : (
                        <span className="vehicle-card__empty"><IconVehicles size={24} /></span>
                      )}
                      <span className="vehicle-card__tag">{event.is_threat ? "RESTRICTED" : "TRACKED"}</span>
                      {event.is_threat && <span className="vehicle-card__danger">!</span>}
                    </span>
                    <span className="vehicle-card__body">
                      <span className="vehicle-card__head">
                        <strong>{humanize(String(event.meta?.vehicle_type ?? event.meta?.label ?? "Vehicle"))}</strong>
                        <span className="confidence">
                          <span className="confidence__bar"><i style={{ width: `${Math.round(event.confidence * 100)}%` }} /></span>
                          {Math.round(event.confidence * 100)}%
                        </span>
                      </span>
                      <small>{event.camera_name} · {event.zone_name ?? "outside zone"}</small>
                      <span className="vehicle-card__foot">
                        <span className="mono">{event.track_id || `#${event.id}`}</span>
                        <span>{formatTime(event.occurred_at, true)}</span>
                        <IconEye size={14} />
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={<IconVehicles size={28} />}
                title="No vehicle activity"
                message="No vehicles have been classified in the selected camera and window."
              />
            )}
          </Panel>

          <Panel title="Recent vehicle incidents" subtitle="Restricted-area intrusions and abnormal vehicle behaviour" bodyClassName="panel__body--flush">
            {incidents.loading && !incidents.data ? (
              <LoadingState label="Loading vehicle incidents…" />
            ) : incidents.data?.items.length ? (
              <div className="data-table data-table--compact">
                <div className="data-table__head incidents-row">
                  <span>Level</span>
                  <span>Incident</span>
                  <span>Camera / zone</span>
                  <span>Risk</span>
                  <span>Status</span>
                  <span>Detected</span>
                </div>
                {incidents.data.items.map((incident) => (
                  <Link className="data-table__row incidents-row" key={incident.id} to={`/threat/${incident.id}`}>
                    <LevelBadge level={incident.level} />
                    <span className="cell-stack">
                      <strong>{incident.title}</strong>
                      <small>{incident.code} · {incident.type_label}</small>
                    </span>
                    <span className="cell-stack">
                      <strong>{incident.camera_code}</strong>
                      <small>{incident.zone_name ?? incident.camera_name}</small>
                    </span>
                    <span className={cx("risk-inline", `risk-inline--${incident.level}`)}>{incident.risk_score}</span>
                    <span><TonePill tone={incident.status === "open" ? "red" : incident.status === "acknowledged" ? "amber" : "green"}>{incident.status.replace("_", " ")}</TonePill></span>
                    <span className="cell-time">{formatTime(incident.detected_at, true)}<small>{formatRelative(incident.detected_at)}</small></span>
                  </Link>
                ))}
              </div>
            ) : (
              <EmptyState title="No vehicle incidents" message="No vehicle intrusion has been verified in the current window." />
            )}
          </Panel>
        </div>

        <aside className="vehicles-layout__side">
          <Panel title="Vehicle classes" subtitle="AI classification distribution">
            {classes.length ? (
              <BarList items={classes} color="cyan" />
            ) : (
              <EmptyState title="No classifications" message="Vehicle classes will appear after the next detection." />
            )}
          </Panel>

          <Panel title="Activity by camera" subtitle="Vehicle detections · last 24h">
            {stats.data?.by_camera.length ? (
              <BarList
                color="amber"
                items={stats.data.by_camera.slice(0, 6).map((camera) => ({
                  label: camera.camera_name,
                  value: camera.count,
                  hint: `Camera ${camera.camera_id}`,
                }))}
              />
            ) : (
              <EmptyState title="No camera activity" />
            )}
          </Panel>

          <Panel title="Vehicle risk model" subtitle="How vehicle targets influence the score" accent="amber">
            <div className="vehicle-risk">
              <div>
                <span className="vehicle-risk__weight">15 pts</span>
                <span>
                  <strong>Target type</strong>
                  <small>Vehicles carry the highest target weight because of speed and mass.</small>
                </span>
              </div>
              <div>
                <span className="vehicle-risk__weight">30 pts</span>
                <span>
                  <strong>Zone sensitivity</strong>
                  <small>A vehicle inside a restricted polygon scores the maximum zone contribution.</small>
                </span>
              </div>
              <div>
                <span className="vehicle-risk__weight">15 pts</span>
                <span>
                  <strong>Dwell time</strong>
                  <small>Stationary vehicles near a gate increase the dwell contribution.</small>
                </span>
              </div>
              <div>
                <span className="vehicle-risk__weight">+10</span>
                <span>
                  <strong>Repetition</strong>
                  <small>Repeated passes within the grouping window raise the score further.</small>
                </span>
              </div>
            </div>
            <p className="safety-note">
              <IconWarning size={15} />
              No automatic number-plate recognition is enabled in this build. Vehicle identity must be confirmed by an
              operator from the evidence image.
            </p>
          </Panel>
        </aside>
      </div>

      <Modal
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={selected ? `Vehicle detection · ${humanize(String(selected.meta?.vehicle_type ?? selected.meta?.label ?? "Vehicle"))}` : "Vehicle"}
        subtitle={selected ? `${selected.camera_name} · ${formatDateTime(selected.occurred_at, true)}` : undefined}
        size="lg"
        footer={
          selected ? (
            <div className="modal__footer-row">
              <span className="mono muted">TRACK {selected.track_id || "—"}</span>
              <div className="btn-row">
                {selected.incident_id && (
                  <Link className="btn btn--danger btn--sm" to={`/threat/${selected.incident_id}`} onClick={() => setSelected(null)}>
                    Open incident
                  </Link>
                )}
                <Link className="btn btn--ghost btn--sm" to={`/playback?camera=${selected.camera_id}`} onClick={() => setSelected(null)}>
                  Evidence
                </Link>
              </div>
            </div>
          ) : null
        }
      >
        {selected && (
          <div className="event-detail">
            <div className="event-detail__media">
              {selected.snapshot_url ? (
                <img src={selected.snapshot_url} alt="Vehicle evidence" />
              ) : (
                <div className="event-detail__placeholder"><IconVehicles size={24} /><span>No snapshot</span></div>
              )}
            </div>
            <div className="event-detail__side">
              <div className="event-detail__verdict">
                {selected.is_threat ? <LevelBadge level="high" pulse /> : <TonePill tone="green">NORMAL VEHICLE</TonePill>}
                <span className="mono muted">CONFIDENCE {Math.round(selected.confidence * 100)}%</span>
              </div>
              <dl className="fact-grid">
                <div><dt>Camera</dt><dd>{selected.camera_name}</dd></div>
                <div><dt>Zone</dt><dd>{selected.zone_name ?? "Outside zones"}</dd></div>
                <div><dt>Track</dt><dd className="mono">{selected.track_id || "—"}</dd></div>
                <div><dt>Event</dt><dd>{humanize(selected.event_type)}</dd></div>
                <div><dt>Time</dt><dd>{formatDateTime(selected.occurred_at, true)}</dd></div>
                <div><dt>Incident</dt><dd>{selected.incident_id ? `#${selected.incident_id}` : "Not grouped"}</dd></div>
              </dl>
              {selected.bbox.length === 4 && (
                <span className="mono muted">BBOX {selected.bbox.map((value) => Number(value).toFixed(3)).join(" · ")}</span>
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

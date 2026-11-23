import { useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, streamUrl } from "../api";
import { useAuth } from "../context/AuthContext";
import { useRealtime } from "../context/RealtimeContext";
import { useDocumentTitle, useResource } from "../hooks/useResource";
import {
  countdown,
  cx,
  formatCountdown,
  formatDate,
  formatGb,
  formatRelative,
  formatTime,
  formatUptime,
  humanize,
  LEVEL_LABELS,
  percentage,
} from "../lib/format";
import type { Camera, Dashboard as DashboardData, Level, TimelinePoint } from "../types";
import LiveCameraView from "../components/LiveCameraView";
import {
  IconActivity,
  IconCamera,
  IconChevron,
  IconClock,
  IconCpu,
  IconDatabase,
  IconExpand,
  IconPeople,
  IconRefresh,
  IconShield,
  IconTarget,
  IconVehicles,
  IconWarning,
} from "../components/Icons";
import {
  EmptyState,
  ErrorState,
  Gauge,
  LevelBadge,
  LoadingState,
  Modal,
  Panel,
  ScoreRing,
  StatusBadge,
  TonePill,
} from "../components/UI";

const LEVEL_COLORS: Record<Level, string> = {
  critical: "#ef4444",
  high: "#fb7185",
  medium: "#f59e0b",
  normal: "#22c55e",
};

function KpiCard({
  label,
  value,
  hint,
  tone,
  icon,
}: {
  label: string;
  value: string | number;
  hint: string;
  tone?: "red" | "amber" | "cyan" | "green";
  icon: ReactNode;
}) {
  return (
    <div className={cx("kpi", tone && `kpi--${tone}`)}>
      <div className="kpi__icon">{icon}</div>
      <div className="kpi__body">
        <span className="kpi__label">{label}</span>
        <strong className="kpi__value">{value}</strong>
        <span className="kpi__hint">{hint}</span>
      </div>
      <span className="kpi__spark" />
    </div>
  );
}

function TimelineChart({ points }: { points: TimelinePoint[] }) {
  const width = 760;
  const height = 150;
  const padding = { top: 12, right: 8, bottom: 24, left: 8 };
  const max = Math.max(4, ...points.map((point) => point.events));
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const step = innerWidth / Math.max(1, points.length);
  const line = points
    .map((point, index) => {
      const x = padding.left + step * index + step / 2;
      const y = padding.top + innerHeight - (point.incidents / Math.max(1, max)) * innerHeight;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${width} ${height}`} className="chart__svg" role="img" aria-label="24 hour event timeline">
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
          <line
            key={ratio}
            x1={padding.left}
            x2={width - padding.right}
            y1={padding.top + innerHeight * ratio}
            y2={padding.top + innerHeight * ratio}
            className="chart__grid"
          />
        ))}
        {points.map((point, index) => {
          const barHeight = (point.events / max) * innerHeight;
          return (
            <g key={`${point.hour}-${index}`}>
              <rect
                x={padding.left + step * index + step * 0.24}
                y={padding.top + innerHeight - barHeight}
                width={step * 0.52}
                height={Math.max(1, barHeight)}
                rx={2}
                className="chart__bar"
              />
              {index % 3 === 0 && (
                <text x={padding.left + step * index + step / 2} y={height - 7} textAnchor="middle" className="chart__label">
                  {point.hour}
                </text>
              )}
            </g>
          );
        })}
        {points.some((point) => point.incidents > 0) && <path d={line} className="chart__line" />}
      </svg>
      <div className="chart__legend">
        <span>
          <i className="legend-dot legend-dot--cyan" /> Events
        </span>
        <span>
          <i className="legend-dot legend-dot--red" /> Incidents
        </span>
        <strong>24 HOURS</strong>
      </div>
    </div>
  );
}

function WeeklyChart({ data }: { data: DashboardData["weekly"] }) {
  const max = Math.max(4, ...data.map((point) => point.incidents));
  return (
    <div className="weekly">
      {data.map((point) => (
        <div className="weekly__col" key={point.date}>
          <div className="weekly__bars">
            <span
              className="weekly__bar weekly__bar--incidents"
              style={{ height: `${Math.max(4, (point.incidents / max) * 100)}%` }}
              title={`${point.incidents} incidents`}
            />
            <span
              className="weekly__bar weekly__bar--critical"
              style={{ height: `${Math.max(2, (point.critical / max) * 100)}%` }}
              title={`${point.critical} critical`}
            />
          </div>
          <span className="weekly__label">{point.label}</span>
          <strong>{point.incidents}</strong>
        </div>
      ))}
    </div>
  );
}

function LevelDonut({ data }: { data: DashboardData["level_distribution"] }) {
  const total = data.reduce((sum, item) => sum + item.count, 0);
  let cursor = 0;
  const segments = data.map((item) => {
    const start = cursor;
    const size = total ? (item.count / total) * 360 : 0;
    cursor += size;
    return `${LEVEL_COLORS[item.level]} ${start}deg ${cursor}deg`;
  });
  return (
    <div className="donut-wrap">
      <div
        className="donut"
        style={{ background: total ? `conic-gradient(${segments.join(", ")})` : "#1a2634" }}
      >
        <div className="donut__hole">
          <strong>{total}</strong>
          <span>LAST 24H</span>
        </div>
      </div>
      <div className="donut-legend">
        {data.map((item) => (
          <div key={item.level}>
            <span className={cx("dot", `dot--${item.level}`)} />
            <span>{item.label}</span>
            <strong>{item.count}</strong>
            <small>{percentage(item.count, total)}%</small>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Dashboard() {
  useDocumentTitle("Perimeter Overview");
  const navigate = useNavigate();
  const { statsVersion, health: liveHealth, activeCount } = useRealtime();
  const { can } = useAuth();
  const dashboard = useResource(() => api.dashboard.get(), [statsVersion]);
  const eventStats = useResource(() => api.events.stats(24), [statsVersion]);
  const system = useResource(() => api.system.info(), []);
  const [preview, setPreview] = useState<Camera | null>(null);
  const [selectedCameraId, setSelectedCameraId] = useState<number | null>(null);
  const [acking, setAcking] = useState(false);

  const data = dashboard.data;
  const stats = eventStats.data;
  const recordingLabel = system.data
    ? system.data.continuous_recording_enabled
      ? system.data.evidence_saved
        ? "continuous + event evidence saved"
        : "continuous video saved"
      : system.data.evidence_saved
        ? "event snapshots + clips saved"
        : "nothing saved"
    : "evidence recording enabled";
  const selectedCamera =
    data?.cameras.find((camera) => camera.id === selectedCameraId) ?? data?.cameras[0] ?? null;

  const counts = useMemo(() => {
    const find = (target: string) => stats?.by_target.find((item) => item.target_type === target)?.count ?? 0;
    const motion = stats?.by_type.find((item) => item.event_type === "motion")?.count ?? 0;
    return {
      people: find("person"),
      vehicles: find("vehicle"),
      motion: motion || data?.kpis.events_today || 0,
    };
  }, [stats, data]);

  const incident = data?.active.primary ?? null;
  const remaining = incident ? countdown(new Date(incident.detected_at).getTime() + 30000) : 0;
  const health = liveHealth ?? data?.health;

  const acknowledge = async () => {
    if (!incident) return;
    setAcking(true);
    try {
      await api.incidents.acknowledge(incident.id, "Acknowledged from dashboard — alarm stood down");
      dashboard.reload();
    } catch {
      /* surfaced by the API toast in the alert centre */
    } finally {
      setAcking(false);
    }
  };

  if (dashboard.loading && !data) return <LoadingState label="Loading perimeter overview…" />;
  if (dashboard.error && !data) return <ErrorState message={dashboard.error} retry={dashboard.reload} />;
  if (!data) return <EmptyState title="No dashboard data" message="The security server returned an empty response." />;

  return (
    <div className="page page--dashboard">
      <div className="page-toolbar">
        <div className="page-toolbar__left">
          <span className="live-chip">
            <span className="live-chip__dot" /> LIVE FEED
          </span>
          <span className="muted">
            Sync {formatTime(data.generated_at, true)} · {data.kpis.cameras_online}/{data.kpis.cameras_total} cameras online ·{" "}
            {activeCount} active threats
          </span>
        </div>
        <div className="page-toolbar__actions">
          <Link to="/threat" className="btn btn--danger btn--sm">
            <IconTarget size={15} /> AI LIVE THREAT SCREEN
          </Link>
          <button type="button" className="btn btn--ghost btn--sm" onClick={dashboard.reload}>
            <IconRefresh size={15} /> Refresh
          </button>
        </div>
      </div>

      {selectedCamera && (
        <Panel
          title="Live security camera"
          subtitle={`Direct feed from the physical camera · ${recordingLabel}`}
          accent="cyan"
          bodyClassName="panel__body--tight"
          actions={
            <Link to="/devices" className="btn btn--ghost btn--xs">
              Camera devices <IconChevron size={13} />
            </Link>
          }
        >
          <LiveCameraView
            camera={selectedCamera}
            cameras={data?.cameras ?? []}
            onSelect={(camera) => setSelectedCameraId(camera.id)}
            onDeviceChange={dashboard.reload}
          />
        </Panel>
      )}

      <div className="kpi-row">
        <KpiCard
          label="Active threats"
          value={data.active.total}
          hint={`${data.active.critical_count} critical · ${data.active.high_count} high`}
          tone="red"
          icon={<IconWarning size={20} />}
        />
        <KpiCard
          label="People detected"
          value={counts.people}
          hint="AI person classifications · 24h"
          tone="cyan"
          icon={<IconPeople size={20} />}
        />
        <KpiCard
          label="Vehicles detected"
          value={counts.vehicles}
          hint="Vehicle tracking · 24h"
          icon={<IconVehicles size={20} />}
        />
        <KpiCard
          label="Motion events"
          value={counts.motion}
          hint={`${data.kpis.events_today} events logged today`}
          icon={<IconActivity size={20} />}
        />
        <KpiCard
          label="Verified reduction"
          value={`${data.kpis.verified_reduction}%`}
          hint={`False alarms ${data.kpis.false_alarm_rate}% · avg response ${data.kpis.avg_response_minutes}m`}
          tone="green"
          icon={<IconShield size={20} />}
        />
        <KpiCard
          label="Cameras online"
          value={`${data.kpis.cameras_online}/${data.kpis.cameras_total}`}
          hint={`${data.kpis.storage_percent}% storage used · ${formatGb(data.kpis.storage_gb)}`}
          icon={<IconCamera size={20} />}
        />
      </div>

      <div className="dashboard-grid">
        <div className="dashboard-grid__main">
          <Panel
            title="Live camera matrix"
            subtitle="AI overlays · object boxes · zone polygons"
            accent="cyan"
            actions={
              <Link to="/devices" className="btn btn--ghost btn--xs">
                Manage devices <IconChevron size={13} />
              </Link>
            }
            bodyClassName="panel__body--tight"
          >
            <div className="camera-grid">
              {data.cameras.map((camera) => (
                <button
                  type="button"
                  key={camera.id}
                  className={cx(
                    "camera-tile",
                    camera.active_threats > 0 && "camera-tile--alert",
                    camera.status !== "online" && "camera-tile--offline",
                  )}
                  onClick={() => setPreview(camera as Camera)}
                >
                  <img src={streamUrl(camera.id)} alt={`${camera.name} live feed`} />
                  <span className="camera-tile__scan" />
                  <span className="camera-tile__top">
                    <span className="camera-tile__live">
                      <span className="status-dot status-dot--online" /> LIVE
                    </span>
                    <span className="camera-tile__code">{camera.code}</span>
                  </span>
                  <span className="camera-tile__bottom">
                    <span>
                      <strong>{camera.name}</strong>
                      <small>{camera.location}</small>
                    </span>
                    <span className="camera-tile__meta">
                      {camera.active_threats > 0 ? (
                        <TonePill tone="red">{camera.active_threats} THREAT</TonePill>
                      ) : (
                        <TonePill tone="green">CLEAR</TonePill>
                      )}
                      <small>{camera.fps ? `${camera.fps.toFixed(0)} FPS` : "WAITING"}</small>
                    </span>
                  </span>
                  <span className="camera-tile__expand">
                    <IconExpand size={14} />
                  </span>
                </button>
              ))}
              {!data.cameras.length && <EmptyState title="No cameras" message="Add a camera from the Devices screen." />}
            </div>
          </Panel>

          <Panel
            title="Event timeline"
            subtitle="24-hour incident and event density"
            actions={<TonePill tone="cyan">{data.kpis.events_today} EVENTS TODAY</TonePill>}
          >
            <TimelineChart points={data.timeline} />
          </Panel>

          <Panel
            title="Recent incidents"
            subtitle="Newest verified threats across the site"
            actions={
              <Link to="/events" className="btn btn--ghost btn--xs">
                View all <IconChevron size={13} />
              </Link>
            }
            bodyClassName="panel__body--flush"
          >
            <div className="data-table data-table--compact">
              <div className="data-table__head incidents-row">
                <span>Level</span>
                <span>Incident</span>
                <span>Camera / zone</span>
                <span>Risk</span>
                <span>Status</span>
                <span>Detected</span>
              </div>
              {data.recent_incidents.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className="data-table__row incidents-row"
                  onClick={() => navigate(`/threat/${item.id}`)}
                >
                  <LevelBadge level={item.level} />
                  <span className="cell-stack">
                    <strong>{item.title}</strong>
                    <small>{item.code} · {item.type_label}</small>
                  </span>
                  <span className="cell-stack">
                    <strong>{item.camera_code}</strong>
                    <small>{item.zone_name ?? item.camera_name}</small>
                  </span>
                  <span className={cx("risk-inline", `risk-inline--${item.level}`)}>{item.risk_score}</span>
                  <StatusBadge status={item.status} />
                  <span className="cell-time">{formatTime(item.detected_at, true)}<small>{formatRelative(item.detected_at)}</small></span>
                </button>
              ))}
              {!data.recent_incidents.length && <EmptyState title="No incidents yet" message="The site is currently quiet." />}
            </div>
          </Panel>
        </div>

        <div className="dashboard-grid__side">
          <Panel
            title="Active threat"
            subtitle="Highest-priority verified alarm"
            accent={incident ? "red" : "none"}
            actions={incident ? <LevelBadge level={incident.level} pulse={incident.status === "open"} /> : <TonePill tone="green">STANDBY</TonePill>}
          >
            {incident ? (
              <div className="threat-mini">
                <div className="threat-mini__top">
                  <ScoreRing score={incident.risk_score} level={incident.level} size={116} />
                  <div className="threat-mini__ident">
                    <span className="eyebrow">THREAT LEVEL</span>
                    <strong className={cx("threat-mini__level", `text-${incident.level}`)}>{LEVEL_LABELS[incident.level]}</strong>
                    <span className="threat-mini__type">{incident.type_label}</span>
                    <span className="mono muted">{incident.code}</span>
                  </div>
                </div>

                <div className="threat-mini__snapshot">
                  <img src={streamUrl(incident.camera_id)} alt={`Live feed from ${incident.camera_code}`} />
                  <span className="threat-mini__stamp">LIVE · DETECTED {formatTime(incident.detected_at, true)}</span>
                </div>

                <dl className="fact-grid">
                  <div>
                    <dt>Camera</dt>
                    <dd>{incident.camera_code} · {incident.camera_name}</dd>
                  </div>
                  <div>
                    <dt>Zone</dt>
                    <dd>{incident.zone_name ?? "Outside zone"}</dd>
                  </div>
                  <div>
                    <dt>Target</dt>
                    <dd>{humanize(incident.target_type)} · {incident.track_id || "—"}</dd>
                  </div>
                  <div>
                    <dt>Face</dt>
                    <dd>{humanize(incident.face_status)}</dd>
                  </div>
                </dl>

                <p className="threat-mini__reason">{incident.explanation}</p>

                <div className="alarm-box">
                  <span className="alarm-box__label">
                    <IconClock size={13} /> ALARM ACTIVATION IN
                  </span>
                  {incident.status === "open" ? (
                    <strong className={cx("alarm-box__clock", remaining === 0 && "is-due")}>
                      {remaining > 0 ? formatCountdown(remaining) : "ESCALATION DUE"}
                    </strong>
                  ) : (
                    <strong className="alarm-box__clock is-ack">{incident.status.replace("_", " ").toUpperCase()}</strong>
                  )}
                  <small>
                    {incident.status === "open"
                      ? "Alarm escalates to the administrator and siren if no operator responds."
                      : "Alarm repetition stopped. The incident remains in the audit trail."}
                  </small>
                </div>

                <div className="btn-row">
                  <Link to={`/threat/${incident.id}`} className="btn btn--primary btn--sm">
                    <IconTarget size={14} /> Open threat screen
                  </Link>
                  {incident.status === "open" && can("acknowledge_alarms") && (
                    <button type="button" className="btn btn--danger btn--sm" disabled={acking} onClick={() => void acknowledge()}>
                      {acking ? <span className="spinner spinner--sm" /> : <IconShield size={14} />} Stand down
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <EmptyState
                icon={<IconShield size={30} />}
                title="Perimeter secure"
                message="No active threats. Verification engine is monitoring every camera."
                action={
                  <Link to="/threat" className="btn btn--ghost btn--sm">
                    Open standby threat screen
                  </Link>
                }
              />
            )}
          </Panel>

          <Panel title="System health" subtitle={health ? `${health.status.toUpperCase()} · checked ${formatRelative(health.checked_at)}` : "Telemetry"} accent="green">
            {health ? (
              <div className="health">
                <div className="health__gauges">
                  <Gauge label="CPU" value={health.cpu_percent} />
                  <Gauge label="Memory" value={health.memory_percent} />
                  <Gauge label="Disk" value={health.disk_percent} />
                </div>
                <div className="health__facts">
                  <div>
                    <IconCamera size={14} />
                    <span>Cameras</span>
                    <strong>{health.cameras_online}/{health.cameras_total}</strong>
                  </div>
                  <div>
                    <IconActivity size={14} />
                    <span>Pipeline</span>
                    <strong>{health.pipeline_running === false ? "Idle" : `${health.fps_total.toFixed(0)} FPS`}</strong>
                  </div>
                  <div>
                    <IconDatabase size={14} />
                    <span>Storage</span>
                    <strong>{formatGb(health.storage_gb)}</strong>
                  </div>
                  <div>
                    <IconCpu size={14} />
                    <span>Uptime</span>
                    <strong>{formatUptime(health.uptime_seconds)}</strong>
                  </div>
                </div>
                <div className="health__bar">
                  <span style={{ width: `${health.disk_percent}%` }} />
                </div>
                <small className="muted">Disk allocation · {health.disk_percent}% used</small>
              </div>
            ) : (
              <EmptyState title="Telemetry unavailable" />
            )}
          </Panel>

          <Panel title="Threat distribution" subtitle="Verified incidents by level · last 24h">
            <LevelDonut data={data.level_distribution} />
          </Panel>

          <Panel
            title="Live event stream"
            subtitle="Latest detections from all cameras"
            actions={<span className="live-chip live-chip--sm"><span className="live-chip__dot" /> LIVE</span>}
          >
            <div className="event-stream">
              {data.recent_events.slice(0, 6).map((event) => (
                <Link to={`/events?q=${encodeURIComponent(event.track_id || event.event_type)}`} key={event.id} className="event-stream__row">
                  <span className={cx("event-stream__icon", event.is_threat && "is-threat")}>
                    {event.target_type === "vehicle" ? <IconVehicles size={15} /> : <IconPeople size={15} />}
                  </span>
                  <span className="event-stream__body">
                    <strong>{event.is_threat ? humanize(event.event_type) : `${humanize(event.target_type)} detected`}</strong>
                    <small>{event.camera_name} · {event.zone_name ?? "outside zones"} · {Math.round(event.confidence * 100)}%</small>
                  </span>
                  <span className="event-stream__time">{formatTime(event.occurred_at, true)}</span>
                </Link>
              ))}
              {!data.recent_events.length && <EmptyState title="No recent events" />}
            </div>
          </Panel>
        </div>
      </div>

      <div className="dashboard-lower">
        <Panel title="7-day incident trend" subtitle="Total incidents with critical overlay">
          <WeeklyChart data={data.weekly} />
          <div className="chart__legend">
            <span><i className="legend-dot legend-dot--cyan" /> Incidents</span>
            <span><i className="legend-dot legend-dot--red" /> Critical</span>
            <strong>{formatDate(data.weekly[0]?.date)} → {formatDate(data.weekly[6]?.date)}</strong>
          </div>
        </Panel>

        <Panel title="Hot zones" subtitle="Most triggered zones · last 24h">
          {data.top_zones.length ? (
            <div className="hot-zones">
              {data.top_zones.map((zone) => (
                <div className="hot-zone" key={`${zone.camera_code}-${zone.zone_name}`}>
                  <span className={cx("hot-zone__rank", `hot-zone__rank--${zone.zone_type}`)}>{zone.incidents}</span>
                  <span className="hot-zone__body">
                    <strong>{zone.zone_name}</strong>
                    <small>{zone.camera_code} · {humanize(zone.zone_type)} zone</small>
                  </span>
                  <div className="hot-zone__bar">
                    <span
                      style={{
                        width: `${percentage(zone.incidents, Math.max(...data.top_zones.map((item) => item.incidents)))}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="No zone activity" message="No incidents were linked to zones in this window." />
          )}
        </Panel>

        <Panel title="Control room activity" subtitle="Audit trail · latest operations">
          <div className="activity-feed">
            {data.activity.map((entry) => (
              <div className="activity-feed__row" key={entry.id}>
                <span className="activity-feed__dot">
                  <IconWarning size={12} />
                </span>
                <span>
                  <strong>{entry.username}</strong> {humanize(entry.action)} <em>{entry.target}</em>
                  <small>{entry.detail}</small>
                </span>
                <time>{formatRelative(entry.created_at)}</time>
              </div>
            ))}
            {!data.activity.length && <EmptyState title="No audit entries" />}
          </div>
        </Panel>
      </div>

      <Panel title="AI analysis" subtitle="Threat types classified in the last 24 hours" bodyClassName="panel__body--tight">
        <div className="type-chips">
          {data.type_distribution.map((item) => (
            <div className="type-chip" key={item.incident_type}>
              <span>{item.label}</span>
              <strong>{item.count}</strong>
            </div>
          ))}
          {!data.type_distribution.length && <span className="muted">No classified threats yet.</span>}
        </div>
      </Panel>

      <Modal
        open={Boolean(preview)}
        onClose={() => setPreview(null)}
        title={preview ? `${preview.code} · ${preview.name}` : "Camera"}
        subtitle={preview?.location}
        size="xl"
        footer={
          preview ? (
            <div className="modal__footer-row">
              <Link to="/devices" className="btn btn--ghost btn--sm">
                Device settings
              </Link>
              <span className="muted">
                {preview.source_type.toUpperCase()} · {preview.resolution} · {preview.fps} FPS target
              </span>
            </div>
          ) : null
        }
      >
        {preview && (
          <div className="camera-preview">
            <img src={streamUrl(preview.id)} alt={`${preview.name} large live feed`} />
            <div className="camera-preview__hud">
              <span className="danger-corner danger-corner--tl" />
              <span className="danger-corner danger-corner--tr" />
              <span className="danger-corner danger-corner--bl" />
              <span className="danger-corner danger-corner--br" />
              <div className="camera-preview__meta">
                <span className="badge badge--red">● LIVE AI OVERLAY</span>
                <span>{preview.code}</span>
                <span>{preview.location}</span>
                <span>{formatTime(new Date().toISOString(), true)}</span>
              </div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

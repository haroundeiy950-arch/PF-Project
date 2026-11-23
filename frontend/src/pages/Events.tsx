import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useRealtime } from "../context/RealtimeContext";
import { useDocumentTitle, useResource } from "../hooks/useResource";
import {
  cx,
  daysAgoInput,
  formatDateTime,
  formatRelative,
  formatTime,
  humanize,
  todayInput,
  toApiDate,
  toApiEnd,
} from "../lib/format";
import type { EventItem } from "../types";
import {
  IconActivity,
  IconCamera,
  IconClose,
  IconEye,
  IconPeople,
  IconRefresh,
  IconSearch,
  IconTarget,
  IconVehicles,
  IconWarning,
} from "../components/Icons";
import {
  EmptyState,
  ErrorState,
  LevelBadge,
  LoadingState,
  Modal,
  Pagination,
  Panel,
  TonePill,
} from "../components/UI";

const TARGET_TYPES = [
  { value: "", label: "All targets" },
  { value: "person", label: "People" },
  { value: "vehicle", label: "Vehicles" },
  { value: "animal", label: "Animals" },
  { value: "unknown", label: "Unknown" },
];

const EVENT_TYPES = [
  { value: "", label: "All event types" },
  { value: "motion", label: "Motion" },
  { value: "person", label: "Person detected" },
  { value: "vehicle", label: "Vehicle detected" },
  { value: "unknown_face", label: "Unknown face" },
  { value: "loitering", label: "Loitering" },
  { value: "restricted_intrusion", label: "Restricted intrusion" },
  { value: "abnormal_activity", label: "Abnormal activity" },
  { value: "vehicle_intrusion", label: "Vehicle intrusion" },
  { value: "door_open", label: "Door opened" },
];

const PAGE_SIZE = 25;

export default function Events() {
  useDocumentTitle("Detection Events");
  const { statsVersion } = useRealtime();
  const [searchParams] = useSearchParams();
  const [q, setQ] = useState(searchParams.get("q") ?? "");
  const [cameraId, setCameraId] = useState("");
  const [eventType, setEventType] = useState("");
  const [targetType, setTargetType] = useState("");
  const [threatOnly, setThreatOnly] = useState(false);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<EventItem | null>(null);

  const cameras = useResource(() => api.cameras.list(), []);
  const stats = useResource(() => api.events.stats(24), [statsVersion]);
  const filterKey = [q, cameraId, eventType, targetType, threatOnly, start, end, offset].join("|");
  const events = useResource(
    () =>
      api.events.list({
        q: q || undefined,
        camera_id: cameraId || undefined,
        event_type: eventType || undefined,
        target_type: targetType || undefined,
        is_threat: threatOnly ? true : undefined,
        start: start ? toApiDate(start) : undefined,
        end: end ? toApiEnd(end) : undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    [filterKey, statsVersion],
  );

  const counts = useMemo(() => {
    const find = (target: string) => stats.data?.by_target.find((item) => item.target_type === target)?.count ?? 0;
    return {
      people: find("person"),
      vehicles: find("vehicle"),
      animals: find("animal"),
      unknown: find("unknown"),
    };
  }, [stats.data]);

  const applyFilters = (changes: () => void) => {
    changes();
    setOffset(0);
  };

  const resetFilters = () => {
    setQ("");
    setCameraId("");
    setEventType("");
    setTargetType("");
    setThreatOnly(false);
    setStart("");
    setEnd("");
    setOffset(0);
  };

  const items = events.data?.items ?? [];
  const total = events.data?.total ?? 0;
  const threatTotal = (events.data as { threats?: number } | null)?.threats ?? 0;

  return (
    <div className="page page--events">
      <div className="page-toolbar">
        <div className="page-toolbar__left">
          <span className="live-chip">
            <span className="live-chip__dot" /> AI EVENT LEDGER
          </span>
          <span className="muted">
            {total} matching events · {threatTotal} verified threats · raw detections retained for evidence
          </span>
        </div>
        <div className="page-toolbar__actions">
          <button type="button" className="btn btn--ghost btn--sm" onClick={events.reload}>
            <IconRefresh size={14} /> Refresh
          </button>
          <Link to="/reports" className="btn btn--primary btn--sm">
            <IconActivity size={14} /> Export report
          </Link>
        </div>
      </div>

      <div className="stat-strip">
        <div className="stat-tile stat-tile--cyan">
          <span className="stat-tile__icon"><IconPeople size={18} /></span>
          <span>
            <small>People · 24h</small>
            <strong>{counts.people}</strong>
          </span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile__icon"><IconVehicles size={18} /></span>
          <span>
            <small>Vehicles · 24h</small>
            <strong>{counts.vehicles}</strong>
          </span>
        </div>
        <div className="stat-tile stat-tile--amber">
          <span className="stat-tile__icon"><IconTarget size={18} /></span>
          <span>
            <small>Animals · 24h</small>
            <strong>{counts.animals}</strong>
          </span>
        </div>
        <div className="stat-tile stat-tile--red">
          <span className="stat-tile__icon"><IconWarning size={18} /></span>
          <span>
            <small>Unverified targets</small>
            <strong>{counts.unknown}</strong>
          </span>
        </div>
        <div className="stat-tile stat-tile--green">
          <span className="stat-tile__icon"><IconCamera size={18} /></span>
          <span>
            <small>Cameras reporting</small>
            <strong>{stats.data?.by_camera.length ?? 0}</strong>
          </span>
        </div>
      </div>

      <Panel title="Search the event ledger" subtitle="Filter by camera, classification, target or verified threat" bodyClassName="panel__body--flush">
        <div className="filter-bar">
          <label className="search-field">
            <IconSearch size={15} />
            <input
              value={q}
              placeholder="Search event type, target or track ID…"
              onChange={(event) => applyFilters(() => setQ(event.target.value))}
            />
            {q && (
              <button type="button" className="icon-btn" onClick={() => applyFilters(() => setQ(""))} aria-label="Clear search">
                <IconClose size={13} />
              </button>
            )}
          </label>
          <select
            className="select"
            value={cameraId}
            onChange={(event) => applyFilters(() => setCameraId(event.target.value))}
          >
            <option value="">All cameras</option>
            {cameras.data?.items.map((camera) => (
              <option key={camera.id} value={camera.id}>
                {camera.code} · {camera.name}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={eventType}
            onChange={(event) => applyFilters(() => setEventType(event.target.value))}
          >
            {EVENT_TYPES.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <select
            className="select"
            value={targetType}
            onChange={(event) => applyFilters(() => setTargetType(event.target.value))}
          >
            {TARGET_TYPES.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <label className="check-field">
            <input
              type="checkbox"
              checked={threatOnly}
              onChange={(event) => applyFilters(() => setThreatOnly(event.target.checked))}
            />
            Verified threats only
          </label>
          <button type="button" className="btn btn--ghost btn--sm" onClick={resetFilters}>
            Reset filters
          </button>
        </div>
        <div className="filter-bar filter-bar--dates">
          <label className="field field--inline">
            <span>From</span>
            <input type="date" value={start} max={end || todayInput()} onChange={(event) => applyFilters(() => setStart(event.target.value))} />
          </label>
          <label className="field field--inline">
            <span>To</span>
            <input type="date" value={end} min={start || undefined} max={todayInput()} onChange={(event) => applyFilters(() => setEnd(event.target.value))} />
          </label>
          <button type="button" className="btn btn--ghost btn--xs" onClick={() => applyFilters(() => { setStart(todayInput()); setEnd(todayInput()); })}>
            Today
          </button>
          <button type="button" className="btn btn--ghost btn--xs" onClick={() => applyFilters(() => { setStart(daysAgoInput(6)); setEnd(todayInput()); })}>
            Last 7 days
          </button>
          <span className="filter-bar__count">{total} results</span>
        </div>
      </Panel>

      <Panel
        title="Detection events"
        subtitle="Newest first · click a row to inspect the evidence frame"
        bodyClassName="panel__body--flush"
        actions={<TonePill tone={threatOnly ? "red" : "cyan"}>{threatOnly ? "THREATS ONLY" : "ALL EVENTS"}</TonePill>}
      >
        {events.loading && !events.data ? (
          <LoadingState label="Loading event ledger…" />
        ) : events.error ? (
          <ErrorState message={events.error} retry={events.reload} />
        ) : items.length ? (
          <>
            <div className="data-table">
              <div className="data-table__head events-row">
                <span>Preview</span>
                <span>Event</span>
                <span>Target / track</span>
                <span>Camera / zone</span>
                <span>Confidence</span>
                <span>Verdict</span>
                <span>Occurred</span>
                <span />
              </div>
              {items.map((event) => (
                <button
                  type="button"
                  className={cx("data-table__row", "events-row", event.is_threat && "is-threat")}
                  key={event.id}
                  onClick={() => setSelected(event)}
                >
                  <span className="event-thumb">
                    {event.snapshot_url ? (
                      <img src={event.snapshot_url} alt="" loading="lazy" />
                    ) : (
                      <span className="event-thumb__empty"><IconEye size={14} /></span>
                    )}
                  </span>
                  <span className="cell-stack">
                    <strong>{humanize(event.event_type)}</strong>
                    <small>#{event.id} · {formatRelative(event.occurred_at)}</small>
                  </span>
                  <span className="cell-stack">
                    <strong>{humanize(event.target_type)}</strong>
                    <small className="mono">{event.track_id || "no track"}</small>
                  </span>
                  <span className="cell-stack">
                    <strong>{event.camera_name ?? `Camera ${event.camera_id}`}</strong>
                    <small>{event.zone_name ?? "Outside zones"}</small>
                  </span>
                  <span className="confidence">
                    <span className="confidence__bar">
                      <i style={{ width: `${Math.round(event.confidence * 100)}%` }} />
                    </span>
                    {Math.round(event.confidence * 100)}%
                  </span>
                  <span>
                    {event.is_threat ? <TonePill tone="red">VERIFIED</TonePill> : <TonePill tone="muted">LOGGED</TonePill>}
                  </span>
                  <span className="cell-time">
                    {formatTime(event.occurred_at, true)}
                    <small>{formatDateTime(event.occurred_at).slice(0, 10)}</small>
                  </span>
                  <span className="row-action"><IconEye size={15} /></span>
                </button>
              ))}
            </div>
            <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        ) : (
          <EmptyState
            icon={<IconSearch size={26} />}
            title="No events match the filters"
            message="Try widening the date range or clearing the classification filter."
            action={<button type="button" className="btn btn--ghost btn--sm" onClick={resetFilters}>Reset filters</button>}
          />
        )}
      </Panel>

      <EventDetail event={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

function EventDetail({ event, onClose }: { event: EventItem | null; onClose: () => void }) {
  if (!event) return null;
  const meta = event.meta ?? {};
  const metaEntries = Object.entries(meta).filter(([, value]) => typeof value !== "object");
  return (
    <Modal
      open={Boolean(event)}
      onClose={onClose}
      title={`${humanize(event.event_type)} · #${event.id}`}
      subtitle={`${event.camera_name ?? "Camera"} · ${formatDateTime(event.occurred_at, true)}`}
      size="lg"
      footer={
        <div className="modal__footer-row">
          <span className="muted mono">TRACK {event.track_id || "—"}</span>
          <div className="btn-row">
            {event.incident_id && (
              <Link className="btn btn--danger btn--sm" to={`/threat/${event.incident_id}`} onClick={onClose}>
                <IconWarning size={14} /> Open incident
              </Link>
            )}
            <Link className="btn btn--ghost btn--sm" to={`/playback?camera=${event.camera_id}`} onClick={onClose}>
              <IconCamera size={14} /> Recordings
            </Link>
          </div>
        </div>
      }
    >
      <div className="event-detail">
        <div className="event-detail__media">
          {event.snapshot_url ? (
            <img src={event.snapshot_url} alt="Event evidence frame" />
          ) : (
            <div className="event-detail__placeholder">
              <IconEye size={24} />
              <span>No evidence frame stored</span>
            </div>
          )}
          {event.bbox.length === 4 && (
            <span className="event-detail__bbox">
              BBOX {event.bbox.map((value) => Number(value).toFixed(3)).join(" · ")}
            </span>
          )}
        </div>
        <div className="event-detail__side">
          <div className="event-detail__verdict">
            {event.is_threat ? <LevelBadge level="high" pulse /> : <TonePill tone="green">NORMAL ACTIVITY</TonePill>}
            <span className="mono muted">CONFIDENCE {Math.round(event.confidence * 100)}%</span>
          </div>
          <dl className="fact-grid">
            <div>
              <dt>Camera</dt>
              <dd>{event.camera_name ?? event.camera_id}</dd>
            </div>
            <div>
              <dt>Zone</dt>
              <dd>{event.zone_name ?? "Outside mapped zones"}</dd>
            </div>
            <div>
              <dt>Target</dt>
              <dd>{humanize(event.target_type)}</dd>
            </div>
            <div>
              <dt>Track ID</dt>
              <dd className="mono">{event.track_id || "—"}</dd>
            </div>
            <div>
              <dt>Occurred</dt>
              <dd>{formatDateTime(event.occurred_at, true)}</dd>
            </div>
            <div>
              <dt>Incident</dt>
              <dd>{event.incident_id ? `#${event.incident_id}` : "Not grouped"}</dd>
            </div>
          </dl>
          {metaEntries.length > 0 && (
            <div className="meta-list">
              <span className="eyebrow">AI METADATA</span>
              {metaEntries.map(([key, value]) => (
                <div className="meta-list__row" key={key}>
                  <span>{humanize(key)}</span>
                  <strong>{String(value)}</strong>
                </div>
              ))}
            </div>
          )}
          {event.is_threat && (
            <p className="safety-note">
              <IconWarning size={15} />
              This detection was verified by the multi-frame rule engine. It is linked to a curated incident and the
              bilingual alarm chain.
            </p>
          )}
        </div>
      </div>
    </Modal>
  );
}

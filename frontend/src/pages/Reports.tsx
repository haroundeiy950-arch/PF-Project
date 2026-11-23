import { useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { useRealtime } from "../context/RealtimeContext";
import { useDocumentTitle, useResource } from "../hooks/useResource";
import {
  LEVEL_LABELS,
  cx,
  daysAgoInput,
  formatDate,
  formatDateTime,
  humanize,
  percentage,
  todayInput,
  toApiDate,
  toApiEnd,
} from "../lib/format";
import type { Level, ReportOverview } from "../types";
import {
  IconActivity,
  IconAlerts,
  IconCamera,
  IconCheck,
  IconClock,
  IconDownload,
  IconRefresh,
  IconReports,
  IconShield,
  IconTarget,
  IconWarning,
} from "../components/Icons";
import {
  BarList,
  EmptyState,
  ErrorState,
  LevelBadge,
  LoadingState,
  Panel,
  TonePill,
} from "../components/UI";

const PRESETS = [
  { label: "7 days", days: 6 },
  { label: "30 days", days: 29 },
  { label: "90 days", days: 89 },
];

const STATUS_TONES: Record<string, "red" | "amber" | "green" | "cyan" | "muted"> = {
  open: "red",
  acknowledged: "amber",
  resolved: "green",
  false_alarm: "muted",
};

export default function Reports() {
  useDocumentTitle("Security Reports");
  const { can } = useAuth();
  const { pushToast, statsVersion } = useRealtime();
  const [start, setStart] = useState(daysAgoInput(6));
  const [end, setEnd] = useState(todayInput());
  const [applied, setApplied] = useState({ start: daysAgoInput(6), end: todayInput() });
  const [exporting, setExporting] = useState("");

  const rangeKey = `${applied.start}|${applied.end}|${statsVersion}`;
  const overview = useResource(
    () =>
      api.reports.overview(
        applied.start ? toApiDate(applied.start) : undefined,
        applied.end ? toApiEnd(applied.end) : undefined,
      ),
    [rangeKey],
  );

  const report: ReportOverview | null = overview.data;
  const totals = report?.totals;

  const daily = report?.daily ?? [];
  const maxDaily = useMemo(
    () => Math.max(1, ...daily.map((point) => point.incidents)),
    [daily],
  );

  const exportFile = async (kind: "incidents" | "events" | "json") => {
    if (!can("export_data")) {
      pushToast({ title: "Export not permitted", message: "Your role cannot export evidence.", tone: "warning" });
      return;
    }
    setExporting(kind);
    try {
      if (kind === "incidents")
        await api.reports.incidentsCsv(
          applied.start ? toApiDate(applied.start) : undefined,
          applied.end ? toApiEnd(applied.end) : undefined,
        );
      if (kind === "events")
        await api.reports.eventsCsv(
          applied.start ? toApiDate(applied.start) : undefined,
          applied.end ? toApiEnd(applied.end) : undefined,
        );
      if (kind === "json")
        await api.reports.exportJson(
          applied.start ? toApiDate(applied.start) : undefined,
          applied.end ? toApiEnd(applied.end) : undefined,
        );
      pushToast({
        title: "Export ready",
        message: kind === "json" ? "JSON evidence package downloaded" : `${humanize(kind)} CSV downloaded`,
        tone: "success",
      });
    } catch (error) {
      pushToast({
        title: "Export failed",
        message: error instanceof Error ? error.message : "Could not build the file",
        tone: "danger",
      });
    } finally {
      setExporting("");
    }
  };

  const applyPreset = (days: number) => {
    const nextStart = daysAgoInput(days);
    const nextEnd = todayInput();
    setStart(nextStart);
    setEnd(nextEnd);
    setApplied({ start: nextStart, end: nextEnd });
  };

  return (
    <div className="page page--reports">
      <div className="page-toolbar">
        <div className="page-toolbar__left">
          <span className="live-chip">
            <span className="live-chip__dot" /> SECURITY ANALYTICS
          </span>
          <span className="muted">
            {report ? `${report.range.days} days · ${formatDate(report.range.start)} → ${formatDate(report.range.end)}` : "Building the report…"}
          </span>
        </div>
        <div className="page-toolbar__actions">
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => window.print()}>
            <IconReports size={14} /> Print
          </button>
          <button type="button" className="btn btn--ghost btn--sm" onClick={overview.reload}>
            <IconRefresh size={14} /> Refresh
          </button>
          <button
            type="button"
            className="btn btn--primary btn--sm"
            onClick={() => void exportFile("json")}
            disabled={!can("export_data") || exporting === "json"}
          >
            {exporting === "json" ? <span className="spinner spinner--sm" /> : <IconDownload size={14} />} Evidence package
          </button>
        </div>
      </div>

      <div className="filter-bar report-filters">
        <div className="report-filters__presets">
          {PRESETS.map((preset) => (
            <button
              key={preset.label}
              type="button"
              className={cx("btn btn--ghost btn--xs", daysBetween(applied) === preset.days + 1 && "btn--active")}
              onClick={() => applyPreset(preset.days)}
            >
              {preset.label}
            </button>
          ))}
        </div>
        <label className="field field--inline">
          <span>From</span>
          <input type="date" value={start} max={end} onChange={(event) => setStart(event.target.value)} />
        </label>
        <label className="field field--inline">
          <span>To</span>
          <input type="date" value={end} min={start} onChange={(event) => setEnd(event.target.value)} />
        </label>
        <button
          type="button"
          className="btn btn--primary btn--sm"
          onClick={() => setApplied({ start, end })}
          disabled={!start || !end}
        >
          <IconActivity size={14} /> Apply range
        </button>
        <span className="filter-bar__spacer" />
        <span className="muted mono">
          {report ? formatDateTime(report.generated_at, true) : "—"}
        </span>
      </div>

      {overview.loading && !report ? (
        <LoadingState label="Aggregating incidents, events and response times…" />
      ) : overview.error ? (
        <ErrorState message={overview.error} retry={overview.reload} />
      ) : report && totals ? (
        <>
          <div className="stat-strip">
            <div className="stat-tile stat-tile--cyan">
              <span className="stat-tile__icon"><IconAlerts size={18} /></span>
              <span>
                <small>Verified incidents</small>
                <strong>{totals.incidents}</strong>
                <em>{totals.critical} critical · {totals.high} high</em>
              </span>
            </div>
            <div className="stat-tile">
              <span className="stat-tile__icon"><IconActivity size={18} /></span>
              <span>
                <small>Raw AI events</small>
                <strong>{totals.events}</strong>
                <em>{totals.verification_reduction}% filtered before alarm</em>
              </span>
            </div>
            <div className={cx("stat-tile", totals.false_alarm_rate > 20 ? "stat-tile--red" : "stat-tile--green")}>
              <span className="stat-tile__icon"><IconWarning size={18} /></span>
              <span>
                <small>False-alarm rate</small>
                <strong>{totals.false_alarm_rate}<em>%</em></strong>
                <em>{totals.false_alarms} marked by operators</em>
              </span>
            </div>
            <div className="stat-tile stat-tile--amber">
              <span className="stat-tile__icon"><IconClock size={18} /></span>
              <span>
                <small>Average response</small>
                <strong>{totals.avg_response_minutes}<em> min</em></strong>
                <em>Resolution avg {totals.avg_resolution_minutes} min</em>
              </span>
            </div>
          </div>

          <div className="report-layout">
            <div className="report-layout__main">
              <Panel
                title="Incident trend"
                subtitle="Daily verified incidents with critical and high overlay"
                actions={<span className="mono muted">PEAK {maxDaily}</span>}
              >
                {daily.length ? (
                  <div className="trend-chart">
                    <div className="trend-chart__grid">
                      {[100, 75, 50, 25, 0].map((line) => (
                        <span key={line} className="trend-chart__gridline" style={{ bottom: `${line}%` }}>
                          <em>{Math.round((maxDaily * line) / 100)}</em>
                        </span>
                      ))}
                    </div>
                    <div className="trend-chart__bars">
                      {daily.map((point) => {
                        const height = Math.max(2, (point.incidents / maxDaily) * 100);
                        const criticalHeight = point.incidents ? (point.critical / point.incidents) * 100 : 0;
                        const highHeight = point.incidents ? (point.high / point.incidents) * 100 : 0;
                        return (
                          <div
                            className="trend-chart__column"
                            key={point.date}
                            title={`${point.date} · ${point.incidents} incidents · ${point.critical} critical · ${point.high} high`}
                          >
                            <div className="trend-chart__bar" style={{ height: `${height}%` }}>
                              {point.high > 0 && <span className="trend-chart__segment trend-chart__segment--high" style={{ height: `${highHeight}%` }} />}
                              {point.critical > 0 && (
                                <span className="trend-chart__segment trend-chart__segment--critical" style={{ height: `${criticalHeight}%` }} />
                              )}
                            </div>
                            <span className="trend-chart__label">{point.label}</span>
                            <span className="trend-chart__value mono">{point.incidents}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : (
                  <EmptyState title="No incidents in range" message="Widen the date range or wait for the next verified detection." />
                )}
              </Panel>

              <div className="report-grid">
                <Panel title="Severity distribution" subtitle="Verified incidents by level">
                  <div className="level-breakdown">
                    {report.by_level.map((row) => (
                      <div className="level-breakdown__row" key={row.level}>
                        <LevelBadge level={row.level as Level} />
                        <div className="level-breakdown__bar">
                          <span
                            className={cx("level-breakdown__fill", `level-breakdown__fill--${row.level}`)}
                            style={{ width: `${percentage(row.count, totals.incidents)}%` }}
                          />
                        </div>
                        <strong>{row.count}</strong>
                        <small>{percentage(row.count, totals.incidents)}%</small>
                      </div>
                    ))}
                  </div>
                  <div className="report-notes">
                    <IconShield size={15} />
                    <span>
                      Thresholds: medium ≥ 30 · high ≥ 60 · critical ≥ 85. Scores are frozen on the incident for audit purposes.
                    </span>
                  </div>
                </Panel>

                <Panel title="Status breakdown" subtitle="Operator workflow">
                  <div className="status-breakdown">
                    {report.by_status.length ? (
                      report.by_status.map((row) => (
                        <div className="status-breakdown__row" key={row.status}>
                          <TonePill tone={STATUS_TONES[row.status] ?? "muted"}>{humanize(row.status)}</TonePill>
                          <div className="status-breakdown__bar">
                            <span
                              className={cx("status-breakdown__fill", `status-breakdown__fill--${row.status}`)}
                              style={{ width: `${percentage(row.count, totals.incidents)}%` }}
                            />
                          </div>
                          <strong>{row.count}</strong>
                        </div>
                      ))
                    ) : (
                      <EmptyState title="No status data" />
                    )}
                  </div>
                  <div className="report-notes">
                    <IconCheck size={15} />
                    <span>{totals.acknowledged} acknowledged · {totals.resolved} resolved · {totals.open} still open.</span>
                  </div>
                </Panel>
              </div>

              <div className="report-grid">
                <Panel title="Incident types" subtitle="What the AI detected">
                  {report.by_type.length ? (
                    <BarList
                      color="red"
                      items={report.by_type.map((row) => ({ label: row.label, value: row.count }))}
                    />
                  ) : (
                    <EmptyState title="No incident types" />
                  )}
                </Panel>
                <Panel title="Camera hotspots" subtitle="Incidents per camera">
                  {report.by_camera.length ? (
                    <BarList
                      color="cyan"
                      items={report.by_camera.slice(0, 8).map((row) => ({ label: row.camera_name, value: row.count }))}
                    />
                  ) : (
                    <EmptyState title="No camera activity" />
                  )}
                </Panel>
              </div>

              <Panel title="Zone hotspots" subtitle="Where risk concentrates" bodyClassName="panel__body--flush">
                {report.by_zone.length ? (
                  <div className="data-table data-table--compact zone-report-table">
                    <div className="data-table__head zone-report-row">
                      <span>Zone</span>
                      <span>Incidents</span>
                      <span>Share</span>
                      <span>Bar</span>
                    </div>
                    {report.by_zone.map((row) => (
                      <div className="data-table__row zone-report-row" key={row.zone_name}>
                        <span className="cell-stack">
                          <strong>{row.zone_name}</strong>
                          <small>Detected presence</small>
                        </span>
                        <span className="mono">{row.count}</span>
                        <span>{percentage(row.count, totals.incidents)}%</span>
                        <span className="zone-report-bar">
                          <i style={{ width: `${percentage(row.count, totals.incidents)}%` }} />
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="No zone incidents" message="No incident has been linked to a zone in this range." />
                )}
              </Panel>

              <Panel title="Daily ledger" subtitle="Raw figures used by the charts" bodyClassName="panel__body--flush">
                {daily.length ? (
                  <div className="data-table data-table--compact daily-table">
                    <div className="data-table__head daily-row">
                      <span>Date</span>
                      <span>Day</span>
                      <span>Incidents</span>
                      <span>Critical</span>
                      <span>High</span>
                      <span>Level mix</span>
                    </div>
                    {daily.map((row) => (
                      <div className="data-table__row daily-row" key={row.date}>
                        <span className="mono">{row.date}</span>
                        <span>{row.label}</span>
                        <span className="mono">{row.incidents}</span>
                        <span className={row.critical ? "text-danger mono" : "mono muted"}>{row.critical}</span>
                        <span className={row.high ? "text-amber mono" : "mono muted"}>{row.high}</span>
                        <span className="daily-row__mix">
                          {row.critical > 0 && <i className="mix-critical" style={{ flex: row.critical }} />}
                          {row.high > 0 && <i className="mix-high" style={{ flex: row.high }} />}
                          {row.incidents - row.critical - row.high > 0 && (
                            <i className="mix-normal" style={{ flex: row.incidents - row.critical - row.high }} />
                          )}
                          {row.incidents === 0 && <span className="muted">—</span>}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="No daily data" />
                )}
              </Panel>
            </div>

            <aside className="report-layout__side">
              <Panel title="Export evidence" subtitle="Auditor-ready files" accent="cyan">
                <div className="export-stack">
                  <button
                    type="button"
                    className="export-card"
                    disabled={!can("export_data") || Boolean(exporting)}
                    onClick={() => void exportFile("incidents")}
                  >
                    <span className="export-card__icon"><IconAlerts size={18} /></span>
                    <span>
                      <strong>Incident ledger</strong>
                      <small>CSV · code, level, score, camera, zone and explanation</small>
                    </span>
                    {exporting === "incidents" ? <span className="spinner spinner--sm" /> : <IconDownload size={16} />}
                  </button>
                  <button
                    type="button"
                    className="export-card"
                    disabled={!can("export_data") || Boolean(exporting)}
                    onClick={() => void exportFile("events")}
                  >
                    <span className="export-card__icon"><IconActivity size={18} /></span>
                    <span>
                      <strong>AI event ledger</strong>
                      <small>CSV · every detection with confidence and track</small>
                    </span>
                    {exporting === "events" ? <span className="spinner spinner--sm" /> : <IconDownload size={16} />}
                  </button>
                  <button
                    type="button"
                    className="export-card"
                    disabled={!can("export_data") || Boolean(exporting)}
                    onClick={() => void exportFile("json")}
                  >
                    <span className="export-card__icon"><IconShield size={18} /></span>
                    <span>
                      <strong>Evidence package</strong>
                      <small>JSON · incidents, factors, alerts and recording paths</small>
                    </span>
                    {exporting === "json" ? <span className="spinner spinner--sm" /> : <IconDownload size={16} />}
                  </button>
                </div>
                {!can("export_data") && (
                  <p className="safety-note">
                    <IconWarning size={15} />
                    Your role can read reports but not export evidence.
                  </p>
                )}
              </Panel>

              <Panel title="Executive summary" subtitle="Generated from the selected range">
                <ul className="plain-list report-summary">
                  <li>
                    <IconTarget size={14} />
                    <span>
                      <strong>{totals.incidents}</strong> verified incidents from <strong>{totals.events}</strong> AI events. The
                      verification stage filtered <strong>{totals.verification_reduction}%</strong> before raising an alarm.
                    </span>
                  </li>
                  <li>
                    <IconWarning size={14} />
                    <span>
                      <strong>{totals.critical}</strong> critical and <strong>{totals.high}</strong> high incidents required the
                      bilingual alarm chain.
                    </span>
                  </li>
                  <li>
                    <IconClock size={14} />
                    <span>
                      Operators acknowledged in <strong>{totals.avg_response_minutes} min</strong> on average and closed incidents in{" "}
                      <strong>{totals.avg_resolution_minutes} min</strong>.
                    </span>
                  </li>
                  <li>
                    <IconCheck size={14} />
                    <span>
                      <strong>{totals.false_alarms}</strong> false alarm(s) recorded ({totals.false_alarm_rate}% of incidents) — use
                      these to tune zone polygons and dwell times.
                    </span>
                  </li>
                </ul>
              </Panel>

              <Panel title="Report scope" subtitle="What is and is not included">
                <div className="fact-grid fact-grid--single">
                  <div><dt>Range</dt><dd>{formatDate(report.range.start)} → {formatDate(report.range.end)}</dd></div>
                  <div><dt>Timezone</dt><dd>Server local time</dd></div>
                  <div><dt>Source</dt><dd>Incident & event ledger</dd></div>
                  <div><dt>Evidence</dt><dd>Media referenced by path, not embedded</dd></div>
                </div>
                <p className="safety-note">
                  <IconCamera size={15} />
                  Reports describe AI-assisted observations. An operator remains responsible for the final security decision.
                </p>
              </Panel>

              <Panel title="Severity key">
                <div className="severity-key">
                  {(["critical", "high", "medium", "normal"] as Level[]).map((level) => (
                    <div key={level} className="severity-key__row">
                      <span className={cx("severity-key__dot", `severity-key__dot--${level}`)} />
                      <strong>{LEVEL_LABELS[level]}</strong>
                      <small>
                        {level === "critical" ? "Siren + admin" : level === "high" ? "Voice + operator" : level === "medium" ? "Warning + clip" : "Log only"}
                      </small>
                    </div>
                  ))}
                </div>
              </Panel>
            </aside>
          </div>
        </>
      ) : null}
    </div>
  );
}

function daysBetween(range: { start: string; end: string }): number {
  const startDate = new Date(`${range.start}T00:00:00`);
  const endDate = new Date(`${range.end}T00:00:00`);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return 0;
  return Math.round((endDate.getTime() - startDate.getTime()) / 86400000) + 1;
}

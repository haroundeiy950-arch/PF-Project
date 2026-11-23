import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, streamUrl } from "../api";
import { useAuth } from "../context/AuthContext";
import { useRealtime } from "../context/RealtimeContext";
import { useDocumentTitle, useNow, useResource } from "../hooks/useResource";
import { speak } from "../voice";
import {
  countdown,
  cx,
  formatCountdown,
  formatDateTime,
  formatDuration,
  formatRelative,
  formatTime,
  humanize,
  LEVEL_DESCRIPTIONS,
  LEVEL_LABELS,
} from "../lib/format";
import type { Alert, Incident } from "../types";
import {
  IconActivity,
  IconAlerts,
  IconCamera,
  IconCheck,
  IconClock,
  IconClose,
  IconFlag,
  IconPeople,
  IconPlay,
  IconRefresh,
  IconShield,
  IconStop,
  IconTarget,
  IconVolume,
  IconWarning,
} from "../components/Icons";
import {
  EmptyState,
  ErrorState,
  LevelBadge,
  LoadingState,
  Modal,
  Panel,
  ScoreRing,
  StatusBadge,
  TonePill,
} from "../components/UI";

const FACTOR_ORDER = ["zone", "target", "time", "dwell", "face", "repetition", "behavior"];
const FACTOR_LABELS: Record<string, string> = {
  zone: "Zone sensitivity",
  target: "Target type",
  time: "Time of day",
  dwell: "Dwell time",
  face: "Face status",
  repetition: "Event repetition",
  behavior: "Behavior analysis",
};

function Countdown({ detectedAt, status }: { detectedAt: string; status: string }) {
  const now = useNow(1000);
  const remaining = status === "open" ? countdown(new Date(detectedAt).getTime() + 30000) : 0;
  const total = 30;
  const elapsed = Math.min(total, Math.max(0, total - remaining));
  const percent = (elapsed / total) * 100;
  return (
    <div className={cx("countdown", status === "open" && remaining === 0 && "countdown--due")}>
      <div className="countdown__ring" style={{ "--progress": `${percent}%` } as CSSProperties}>
        <div className="countdown__inner">
          <strong>{status === "open" ? formatCountdown(remaining) : "HELD"}</strong>
          <small>{status === "open" ? (remaining === 0 ? "ESCALATED" : "TO SIREN") : status.replace("_", " ")}</small>
        </div>
      </div>
      <div className="countdown__body">
        <span>AI verification gate</span>
        <strong>{status === "open" ? "Operator response required" : "Alarm chain stopped"}</strong>
        <small>
          {status === "open"
            ? "Acknowledging stops repetition; ignoring escalates to the administrator and siren."
            : "This incident is closed for alarm purposes but remains in the evidence log."}
        </small>
        <span className="countdown__stamp">Now {formatTime(new Date(now).toISOString(), true)}</span>
      </div>
    </div>
  );
}

function VerificationChain({ incident }: { incident: Incident }) {
  const factors = incident.factors ?? {};
  const contributions = (factors.contributions ?? {}) as Record<string, number>;
  const breakdown = (factors.breakdown ?? {}) as Record<string, number>;
  const checks = [
    {
      label: "Object detected",
      hint: `${humanize(incident.target_type)} · track ${incident.track_id || "—"}`,
      done: true,
    },
    {
      label: "Zone presence confirmed",
      hint: incident.zone_name ? `${incident.zone_name} (${humanize(incident.zone_type)})` : "Outside mapped zones",
      done: Boolean(incident.zone_name),
    },
    {
      label: "Dwell time satisfied",
      hint:
        typeof factors.dwell_seconds === "number"
          ? `${Number(factors.dwell_seconds).toFixed(1)}s observed`
          : "Motion persistence verified",
      done: true,
    },
    {
      label: "Multi-frame verification",
      hint:
        typeof factors.frames_seen === "number"
          ? `${factors.frames_seen} consecutive frames`
          : "Frame count recorded in the event ledger",
      done: true,
    },
    {
      label: "Risk score threshold met",
      hint: `Score ${incident.risk_score}/100 · ${incident.level_label}`,
      done: incident.risk_score >= 30,
    },
    {
      label: "Evidence snapshot stored",
      hint: incident.snapshot_url ? "Snapshot attached to incident" : "Snapshot pending",
      done: Boolean(incident.snapshot_url),
    },
  ];

  return (
    <div className="verify">
      <ul className="verify__list">
        {checks.map((check) => (
          <li key={check.label} className={cx("verify__item", check.done ? "is-done" : "is-pending")}>
            <span className="verify__mark">{check.done ? <IconCheck size={13} /> : <IconClock size={13} />}</span>
            <span>
              <strong>{check.label}</strong>
              <small>{check.hint}</small>
            </span>
          </li>
        ))}
      </ul>
      <div className="factor-list">
        {FACTOR_ORDER.map((key) => {
          const value = contributions[key] ?? breakdown[key] ?? 0;
          const max = Math.max(1, ...FACTOR_ORDER.map((name) => contributions[name] ?? breakdown[name] ?? 0));
          return (
            <div className="factor" key={key}>
              <div className="factor__head">
                <span>{FACTOR_LABELS[key]}</span>
                <strong>{Math.round(Number(value) * 10) / 10}</strong>
              </div>
              <div className="factor__track">
                <span style={{ width: `${(Number(value) / max) * 100}%` }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AlertMessages({
  alerts,
  onSpeak,
  onStop,
}: {
  alerts: Alert[];
  onSpeak: (message: string, language: string) => void;
  onStop: () => void;
}) {
  const voiceAlerts = alerts.filter((alert) => alert.channel === "voice");
  const others = alerts.filter((alert) => alert.channel !== "voice");
  if (!alerts.length) {
    return <EmptyState title="No alerts dispatched" message="The alarm chain has not produced any channel messages yet." />;
  }
  return (
    <div className="alert-messages">
      {voiceAlerts.map((alert) => (
        <div className={cx("voice-bubble", alert.language === "ar" && "voice-bubble--ar")} key={alert.id} dir={alert.language === "ar" ? "rtl" : "ltr"}>
          <div className="voice-bubble__head">
            <span className="voice-bubble__lang">{alert.language === "ar" ? "العربية · AR" : "ENGLISH · EN"}</span>
            <TonePill tone={alert.status === "acknowledged" ? "green" : alert.status === "playing" ? "red" : "amber"}>
              {alert.status.replace(/_/g, " ")}
            </TonePill>
          </div>
          <p>{alert.message}</p>
          <div className="voice-bubble__actions">
            <button
              type="button"
              className="btn btn--ghost btn--xs"
              disabled={!alert.message}
              onClick={() => onSpeak(alert.message, alert.language)}
            >
              <IconVolume size={13} /> Speak
            </button>
            <span className="muted">{alert.played_at ? `Played ${formatTime(alert.played_at, true)}` : "Not played yet"}</span>
          </div>
        </div>
      ))}
      {voiceAlerts.length > 1 && (
        <button type="button" className="btn btn--danger btn--sm" onClick={onStop}>
          <IconStop size={14} /> Silence repeating warnings
        </button>
      )}
      {others.map((alert) => (
        <div className="alert-channel" key={alert.id}>
          <span className={cx("alert-channel__icon", `is-${alert.channel}`)}>
            {alert.channel === "siren" ? <IconAlerts size={15} /> : <IconActivity size={15} />}
          </span>
          <span>
            <strong>{alert.channel === "siren" ? "Local siren" : "Remote notification"}</strong>
            <small>{alert.detail || alert.message}</small>
          </span>
          <TonePill tone={alert.status === "sent" || alert.status === "playing" ? "cyan" : "muted"}>{alert.status}</TonePill>
        </div>
      ))}
    </div>
  );
}

export default function ThreatScreen() {
  useDocumentTitle("AI Live Threat Screen");
  const params = useParams<{ incidentId?: string }>();
  const navigate = useNavigate();
  const { can } = useAuth();
  const { statsVersion, activeCount, speakIncident, stopAllAlerts, pushToast } = useRealtime();
  const now = useNow(1000);
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [action, setAction] = useState<"acknowledge" | "resolve" | "false_alarm" | null>(null);
  const [dismissed, setDismissed] = useState<number[]>([]);
  const [showEvidence, setShowEvidence] = useState(false);

  const active = useResource(() => api.incidents.active(), [statsVersion]);
  const routeId = params.incidentId ? Number(params.incidentId) : null;
  const queue = (active.data?.items ?? []).filter((item) => !dismissed.includes(item.id));
  const selectedId = routeId ?? active.data?.primary?.id ?? null;
  const detail = useResource<Incident | null>(
    () => (selectedId ? api.incidents.get(selectedId) : Promise.resolve(null)),
    [selectedId, statsVersion],
  );
  const incident = detail.data ?? active.data?.items.find((item) => item.id === selectedId) ?? null;

  const responseSeconds = useMemo(() => {
    if (!incident) return 0;
    if (incident.acknowledged_at) {
      return Math.max(0, (new Date(incident.acknowledged_at).getTime() - new Date(incident.detected_at).getTime()) / 1000);
    }
    return Math.max(0, (now - new Date(incident.detected_at).getTime()) / 1000);
  }, [incident, now]);

  useEffect(() => {
    if (!incident && selectedId && !detail.loading) {
      navigate("/threat", { replace: true });
    }
  }, [incident, selectedId, detail.loading, navigate]);

  const openAction = (value: "acknowledge" | "resolve" | "false_alarm") => {
    setNote("");
    setAction(value);
  };

  const submitAction = async () => {
    if (!incident || !action) return;
    setBusy(action);
    try {
      if (action === "acknowledge") {
        await api.incidents.acknowledge(incident.id, note || "Acknowledged from AI threat screen");
        pushToast({ title: "Alarm acknowledged", message: `${incident.code} · warning repetition stopped`, tone: "success" });
      } else if (action === "resolve") {
        await api.incidents.resolve(incident.id, note || "Threat verified and resolved");
        pushToast({ title: "Incident resolved", message: `${incident.code} closed`, tone: "success" });
      } else {
        await api.incidents.falseAlarm(incident.id, note || "Marked as false alarm after review");
        pushToast({ title: "Marked as false alarm", message: `${incident.code} added to false-alarm analytics`, tone: "info" });
      }
      setAction(null);
      active.reload();
      detail.reload();
    } catch (error) {
      pushToast({
        title: "Action failed",
        message: error instanceof Error ? error.message : "The server rejected the request",
        tone: "danger",
      });
    } finally {
      setBusy("");
    }
  };

  const replay = async () => {
    if (!incident) return;
    setBusy("replay");
    try {
      await api.alerts.replay(incident.id);
      speakIncident(incident);
      pushToast({ title: "Warnings re-queued", message: "English and Arabic warnings will play again", tone: "warning" });
      detail.reload();
    } catch (error) {
      pushToast({
        title: "Replay failed",
        message: error instanceof Error ? error.message : "Incident may already be closed",
        tone: "danger",
      });
    } finally {
      setBusy("");
    }
  };

  const speakAlert = (message: string, language: string) => {
    speak([{ language, text: message }]);
  };

  if (active.loading && !active.data) return <LoadingState label="Synchronising live threat channel…" />;
  if (active.error && !active.data) return <ErrorState message={active.error} retry={active.reload} />;

  if (!incident) {
    return (
      <div className="page page--threat">
        <div className="standby">
          <div className="standby__radar">
            <span className="standby__sweep" />
            <span className="standby__ring standby__ring--1" />
            <span className="standby__ring standby__ring--2" />
            <span className="standby__ring standby__ring--3" />
            <IconShield size={30} />
          </div>
          <span className="eyebrow">AI LIVE THREAT SCREEN · STANDBY</span>
          <h2>Perimeter secure</h2>
          <p>
            No active threats. The verification engine is watching every camera, and bilingual warnings are queued
            automatically if a verified intrusion occurs.
          </p>
          <div className="standby__facts">
            <div>
              <strong>{activeCount}</strong>
              <span>Active threats</span>
            </div>
            <div>
              <strong>EN / AR</strong>
              <span>Bilingual warnings</span>
            </div>
            <div>
              <strong>AI</strong>
              <span>Verification armed</span>
            </div>
          </div>
          <div className="btn-row">
            <Link to="/dashboard" className="btn btn--primary">
              Return to dashboard
            </Link>
            <Link to="/automations" className="btn btn--ghost">
              Review emergency chain
            </Link>
          </div>
        </div>
        {queue.length > 0 && (
          <Panel title="Recently cleared queue" subtitle="Incidents that were handled while you were away">
            <div className="threat-queue">
              {queue.map((item) => (
                <button type="button" key={item.id} className="threat-queue__item" onClick={() => navigate(`/threat/${item.id}`)}>
                  <LevelBadge level={item.level} />
                  <span>
                    <strong>{item.title}</strong>
                    <small>{item.code} · {item.camera_code}</small>
                  </span>
                  <span className="risk-inline">{item.risk_score}</span>
                </button>
              ))}
            </div>
          </Panel>
        )}
      </div>
    );
  }

  const isDanger = incident.level === "critical" || incident.level === "high";
  const status = incident.status;

  return (
    <div className={cx("page", "page--threat", isDanger && "page--danger")}>
      <div className={cx("threat-banner", `threat-banner--${incident.level}`)}>
        <span className="threat-banner__pulse" />
        <IconWarning size={20} />
        <strong>{LEVEL_LABELS[incident.level].toUpperCase()} DANGER</strong>
        <span>{incident.title}</span>
        <span className="threat-banner__meta">
          {incident.code} · {incident.camera_code} · {formatRelative(incident.detected_at)}
        </span>
        <div className="threat-banner__right">
          <LevelBadge level={incident.level} pulse={status === "open"} />
          <StatusBadge status={status} />
        </div>
      </div>

      <div className="threat-layout">
        <div className="threat-layout__main">
          <div className={cx("threat-stage", `threat-stage--${incident.level}`)}>
            <div className="threat-stage__media">
              {incident.camera_id ? (
                <img src={streamUrl(incident.camera_id)} alt={`${incident.camera_name} live AI feed`} />
              ) : (
                <div className="threat-stage__no-feed">Camera feed unavailable</div>
              )}
              <span className="danger-corner danger-corner--tl" />
              <span className="danger-corner danger-corner--tr" />
              <span className="danger-corner danger-corner--bl" />
              <span className="danger-corner danger-corner--br" />
              <span className="threat-stage__scan" />
              <div className="threat-stage__flash">{isDanger && status === "open" ? "DANGER" : "MONITORING"}</div>
              <div className="threat-stage__hud">
                <span className="live-chip live-chip--sm">
                  <span className="live-chip__dot" /> AI LIVE FEED
                </span>
                <span>{incident.camera_code} · {incident.camera_name}</span>
                <span>{incident.camera_location}</span>
                <span className="mono">{formatTime(new Date(now).toISOString(), true)}</span>
              </div>
              <div className="threat-stage__box">
                <span>TRACK {incident.track_id || "—"}</span>
                <strong>{humanize(incident.target_type).toUpperCase()}</strong>
                <small>RISK {incident.risk_score}/100</small>
              </div>
              {incident.snapshot_url && (
                <button type="button" className="threat-stage__evidence" onClick={() => setShowEvidence(true)}>
                  <IconCamera size={14} /> Evidence snapshot
                </button>
              )}
            </div>
            <div className="threat-stage__strip">
              <span><IconCamera size={13} /> {incident.camera_code}</span>
              <span><IconTarget size={13} /> {incident.zone_name ?? "No zone"}</span>
              <span><IconClock size={13} /> Detected {formatDateTime(incident.detected_at, true)}</span>
              <span><IconActivity size={13} /> Response {formatDuration(responseSeconds)}</span>
              <span className="mono">{incident.face_status.toUpperCase()}</span>
            </div>
          </div>

          <Panel
            title="Incident analysis"
            subtitle="Explainable AI decision trail · Section 11 risk model"
            actions={<TonePill tone="red">RISK {incident.risk_score} / 100</TonePill>}
          >
            <div className="analysis">
              <div className="analysis__score">
                <ScoreRing score={incident.risk_score} level={incident.level} size={150} />
                <div className={cx("analysis__level", `text-${incident.level}`)}>{LEVEL_LABELS[incident.level]}</div>
                <p>{LEVEL_DESCRIPTIONS[incident.level]}</p>
                <span className="mono muted">VERIFICATION ENGINE v1.0</span>
              </div>
              <div className="analysis__body">
                <p className="analysis__explanation">{incident.explanation}</p>
                <dl className="fact-grid fact-grid--wide">
                  <div>
                    <dt>Threat type</dt>
                    <dd>{incident.type_label}</dd>
                  </div>
                  <div>
                    <dt>Camera / zone</dt>
                    <dd>{incident.camera_code} · {incident.zone_name ?? "Outside zone"}</dd>
                  </div>
                  <div>
                    <dt>Target &amp; track</dt>
                    <dd>{humanize(incident.target_type)} · {incident.track_id || "—"}</dd>
                  </div>
                  <div>
                    <dt>Face recognition</dt>
                    <dd>{humanize(incident.face_status)}</dd>
                  </div>
                  <div>
                    <dt>Events grouped</dt>
                    <dd>{incident.event_count ?? 0} detections</dd>
                  </div>
                  <div>
                    <dt>Evidence</dt>
                    <dd>{incident.recordings?.length ? `${incident.recordings.length} recording(s)` : "Snapshot only"}</dd>
                  </div>
                </dl>
                <VerificationChain incident={incident} />
              </div>
            </div>
          </Panel>

          <Panel
            title="Bilingual alarm chain"
            subtitle="Voice warning · notification · siren · acknowledgement"
            accent="red"
            actions={
              <div className="btn-row">
                <button type="button" className="btn btn--ghost btn--xs" onClick={() => speakIncident(incident)}>
                  <IconVolume size={13} /> Play warning
                </button>
                <button type="button" className="btn btn--ghost btn--xs" onClick={stopAllAlerts}>
                  <IconStop size={13} /> Silence
                </button>
                {status !== "resolved" && status !== "false_alarm" && can("acknowledge_alarms") && (
                  <button type="button" className="btn btn--ghost btn--xs" disabled={busy === "replay"} onClick={() => void replay()}>
                    <IconRefresh size={13} /> Replay
                  </button>
                )}
              </div>
            }
          >
            <AlertMessages alerts={incident.alerts ?? []} onSpeak={speakAlert} onStop={stopAllAlerts} />
          </Panel>

          <Panel title="Incident event trail" subtitle="Every verified detection grouped under this incident" bodyClassName="panel__body--flush">
            <IncidentEvents incidentId={incident.id} refreshKey={statsVersion} />
          </Panel>
        </div>

        <aside className="threat-layout__side">
          <Panel title="Response window" subtitle="Operator confirmation gate" accent={status === "open" ? "red" : "green"}>
            <Countdown detectedAt={incident.detected_at} status={status} />
            {can("acknowledge_alarms") ? (
              <div className="response-actions">
                {status === "open" && (
                  <button type="button" className="btn btn--danger btn--block" onClick={() => openAction("acknowledge")}>
                    <IconShield size={16} /> Acknowledge alarm
                  </button>
                )}
                {status !== "resolved" && status !== "false_alarm" && (
                  <>
                    <button type="button" className="btn btn--primary btn--block" onClick={() => openAction("resolve")}>
                      <IconCheck size={16} /> Resolve incident
                    </button>
                    <button type="button" className="btn btn--ghost btn--block" onClick={() => openAction("false_alarm")}>
                      <IconFlag size={16} /> Mark false alarm
                    </button>
                  </>
                )}
                {(status === "resolved" || status === "false_alarm") && (
                  <div className="response-closed">
                    <IconCheck size={16} />
                    <span>
                      <strong>Incident closed</strong>
                      <small>{status === "false_alarm" ? "Learned as a false alarm" : "Confirmed and archived"}</small>
                    </span>
                  </div>
                )}
              </div>
            ) : (
              <p className="muted permission-note">
                <IconWarning size={14} /> Your role can view this threat but cannot acknowledge alarms.
              </p>
            )}
            <div className="response-facts">
              <div>
                <span>Detected</span>
                <strong>{formatDateTime(incident.detected_at, true)}</strong>
              </div>
              <div>
                <span>Acknowledged</span>
                <strong>{incident.acknowledged_at ? formatDateTime(incident.acknowledged_at, true) : "Pending"}</strong>
              </div>
              <div>
                <span>Response time</span>
                <strong>{formatDuration(responseSeconds)}</strong>
              </div>
              <div>
                <span>Alarm state</span>
                <strong>{status.replace("_", " ").toUpperCase()}</strong>
              </div>
            </div>
          </Panel>

          <Panel
            title="Active threat queue"
            subtitle={`${queue.length} incident${queue.length === 1 ? "" : "s"} awaiting review`}
            actions={
              <button type="button" className="btn btn--ghost btn--xs" onClick={active.reload}>
                <IconRefresh size={13} /> Sync
              </button>
            }
            bodyClassName="panel__body--flush"
          >
            {queue.length ? (
              <div className="threat-queue">
                {queue.map((item) => (
                  <div key={item.id} className={cx("threat-queue__row", item.id === incident.id && "is-active")}>
                    <button type="button" className="threat-queue__item" onClick={() => navigate(`/threat/${item.id}`)}>
                      <span className={cx("threat-queue__level", `level-${item.level}`)}>{item.risk_score}</span>
                      <span>
                        <strong>{item.title}</strong>
                        <small>
                          {item.camera_code} · {item.zone_name ?? "outside zone"} · {formatRelative(item.detected_at)}
                        </small>
                      </span>
                      <LevelBadge level={item.level} />
                    </button>
                    <button
                      type="button"
                      className="icon-btn"
                      title="Dismiss from local queue"
                      onClick={() => setDismissed((current) => [...current, item.id])}
                    >
                      <IconClose size={14} />
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title="Queue empty" message="No other active threats are waiting for an operator." />
            )}
          </Panel>

          <Panel title="Evidence & actions" subtitle="Snapshots, clips and recordings">
            <div className="evidence-actions">
              {incident.snapshot_url ? (
                <a className="evidence-thumb" href={incident.snapshot_url} target="_blank" rel="noreferrer">
                  <img src={incident.snapshot_url} alt="Incident evidence snapshot" />
                  <span><IconCamera size={13} /> Open snapshot</span>
                </a>
              ) : (
                <div className="evidence-thumb evidence-thumb--empty">
                  <IconCamera size={22} />
                  <span>Snapshot pending</span>
                </div>
              )}
              <Link to="/playback" className="btn btn--ghost btn--block">
                <IconPlay size={15} /> Open evidence playback
              </Link>
              <Link to="/events" className="btn btn--ghost btn--block">
                <IconActivity size={15} /> Search event ledger
              </Link>
              <Link to="/automations" className="btn btn--ghost btn--block">
                <IconAlerts size={15} /> Inspect alarm chain
              </Link>
            </div>
          </Panel>

          <Panel title="Safety note" subtitle="Human-in-the-loop policy" accent="amber">
            <p className="safety-note">
              <IconWarning size={16} />
              This screen is an AI decision aid. Face recognition never raises a danger level by itself, and an operator
              must confirm every alarm before the emergency response is finalised.
            </p>
          </Panel>
        </aside>
      </div>

      <Modal
        open={action !== null}
        onClose={() => setAction(null)}
        title={action === "acknowledge" ? "Acknowledge incident" : action === "resolve" ? "Resolve incident" : "Mark as false alarm"}
        subtitle={incident ? `${incident.code} · ${incident.title}` : undefined}
        size="md"
        footer={
          <div className="modal__footer-row">
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => setAction(null)}>
              Cancel
            </button>
            <button
              type="button"
              className={action === "false_alarm" ? "btn btn--ghost btn--sm" : "btn btn--danger btn--sm"}
              disabled={Boolean(busy)}
              onClick={() => void submitAction()}
            >
              {busy ? <span className="spinner spinner--sm" /> : <IconCheck size={14} />} Confirm
            </button>
          </div>
        }
      >
        <div className="form-stack">
          <p className="muted">
            {action === "acknowledge"
              ? "Acknowledging stops the repeating voice warnings and records your operator response in the audit trail."
              : action === "resolve"
                ? "Resolving closes the incident and archives the evidence. Use this after the situation is confirmed safe."
                : "False alarms are kept for analytics. They reduce the reported false-alarm rate and improve verification tuning."}
          </p>
          <label className="field">
            <span>Operator note</span>
            <textarea
              rows={4}
              value={note}
              maxLength={400}
              placeholder="Describe what you observed, who responded, or why this is a false alarm…"
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
          <div className="operator-tile">
            <IconPeople size={16} />
            <span>
              <strong>{incident.camera_name}</strong>
              <small>{incident.camera_location} · risk {incident.risk_score}/100</small>
            </span>
          </div>
        </div>
      </Modal>

      <Modal
        open={showEvidence}
        onClose={() => setShowEvidence(false)}
        title="Incident evidence snapshot"
        subtitle={incident.snapshot_url ?? undefined}
        size="xl"
        footer={
          <div className="modal__footer-row">
            <span className="muted">{formatDateTime(incident.detected_at, true)} · {incident.code}</span>
            {incident.snapshot_url && (
              <a className="btn btn--primary btn--sm" href={incident.snapshot_url} download>
                Download snapshot
              </a>
            )}
          </div>
        }
      >
        {incident.snapshot_url ? (
          <div className="evidence-preview">
            <img src={incident.snapshot_url} alt="Full incident evidence" />
          </div>
        ) : (
          <EmptyState title="No snapshot" message="The pipeline could not store an evidence frame for this incident." />
        )}
      </Modal>
    </div>
  );
}

function IncidentEvents({ incidentId, refreshKey }: { incidentId: number; refreshKey: number }) {
  const events = useResource(() => api.incidents.events(incidentId), [incidentId, refreshKey]);
  if (events.loading && !events.data) return <LoadingState label="Loading detection trail…" />;
  if (events.error) return <ErrorState message={events.error} retry={events.reload} />;
  const items = events.data?.items ?? [];
  if (!items.length) return <EmptyState title="No grouped events" message="The incident was created from a single detection." />;
  return (
    <div className="data-table data-table--compact">
      <div className="data-table__head trail-row">
        <span>Time</span>
        <span>Detection</span>
        <span>Track</span>
        <span>Confidence</span>
        <span>Threat</span>
      </div>
      {items.map((event) => (
        <div className="data-table__row trail-row" key={event.id}>
          <span className="cell-time">{formatTime(event.occurred_at, true)}</span>
          <span className="cell-stack">
            <strong>{humanize(event.event_type)}</strong>
            <small>{humanize(event.target_type)} · {humanize(event.zone_name ?? "no zone")}</small>
          </span>
          <span className="mono">{event.track_id || "—"}</span>
          <span className="confidence">
            <span className="confidence__bar"><i style={{ width: `${Math.round(event.confidence * 100)}%` }} /></span>
            {Math.round(event.confidence * 100)}%
          </span>
          <span>{event.is_threat ? <TonePill tone="red">THREAT</TonePill> : <TonePill tone="muted">LOG</TonePill>}</span>
        </div>
      ))}
    </div>
  );
}

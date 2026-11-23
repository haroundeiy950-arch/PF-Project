import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { useRealtime } from "../context/RealtimeContext";
import { useDocumentTitle, useResource } from "../hooks/useResource";
import { speak, speechSupported } from "../voice";
import { cx, formatRelative, formatTime, humanize } from "../lib/format";
import type { Alert, AlertTemplate } from "../types";
import {
  IconAlerts,
  IconCheck,
  IconClock,
  IconPlay,
  IconRefresh,
  IconSettings,
  IconShield,
  IconStop,
  IconVolume,
  IconVolumeOff,
  IconWarning,
} from "../components/Icons";
import {
  EmptyState,
  ErrorState,
  LevelBadge,
  LoadingState,
  Pagination,
  Panel,
  TonePill,
  Toggle,
} from "../components/UI";

const CHANNELS = [
  { value: "", label: "All channels" },
  { value: "voice", label: "Voice warnings" },
  { value: "notification", label: "Notifications" },
  { value: "siren", label: "Sirens" },
];

const STATUSES = [
  { value: "", label: "All statuses" },
  { value: "not_started", label: "Not started" },
  { value: "playing", label: "Playing" },
  { value: "sent", label: "Sent" },
  { value: "stopped", label: "Stopped" },
  { value: "acknowledged", label: "Acknowledged" },
];

const PAGE_SIZE = 20;

function statusTone(status: string): "red" | "amber" | "green" | "cyan" | "muted" {
  if (status === "playing") return "red";
  if (status === "not_started") return "amber";
  if (status === "acknowledged") return "green";
  if (status === "sent") return "cyan";
  return "muted";
}

export default function Alerts() {
  useDocumentTitle("Alert Center");
  const { can } = useAuth();
  const {
    pendingAlerts,
    refreshPending,
    speakAlert,
    stopAllAlerts,
    voiceEnabled,
    toggleVoice,
    sirenEnabled,
    setSirenEnabled,
    pushToast,
    statsVersion,
  } = useRealtime();
  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState<number | null>(null);

  const templates = useResource(() => api.alerts.templates(), []);
  const settings = useResource(() => api.settings.get(), [statsVersion]);
  const filterKey = [channel, status, offset].join("|");
  const alerts = useResource(
    () =>
      api.alerts.list({
        channel: channel || undefined,
        status: status || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    [filterKey, statsVersion],
  );

  const counts = useMemo(() => {
    const items = alerts.data?.items ?? [];
    return {
      voice: items.filter((item) => item.channel === "voice").length,
      notifications: items.filter((item) => item.channel === "notification").length,
      sirens: items.filter((item) => item.channel === "siren").length,
    };
  }, [alerts.data]);

  const play = async (alert: Alert) => {
    setBusy(alert.id);
    try {
      await speakAlert(alert);
      pushToast({ title: "Warning playing", message: alert.language === "ar" ? "Arabic warning synthesised" : "English warning synthesised", tone: "warning" });
      alerts.reload();
      await refreshPending();
    } catch (error) {
      pushToast({ title: "Could not play", message: error instanceof Error ? error.message : "Voice engine unavailable", tone: "danger" });
    } finally {
      setBusy(null);
    }
  };

  const stop = async (alert: Alert) => {
    setBusy(alert.id);
    try {
      stopAllAlerts();
      await api.alerts.stop(alert.id);
      alerts.reload();
      await refreshPending();
    } catch (error) {
      pushToast({ title: "Could not stop alert", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setBusy(null);
    }
  };

  const acknowledge = async (alert: Alert) => {
    setBusy(alert.id);
    try {
      await api.alerts.acknowledge(alert.id);
      pushToast({ title: "Alert acknowledged", message: `${alert.channel} · ${alert.language.toUpperCase()}`, tone: "success" });
      alerts.reload();
      await refreshPending();
    } catch (error) {
      pushToast({ title: "Could not acknowledge", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setBusy(null);
    }
  };

  const resend = async (alert: Alert) => {
    setBusy(alert.id);
    try {
      await api.alerts.resend(alert.id);
      pushToast({ title: "Notification re-sent", message: "Control room and administrator notified", tone: "success" });
      alerts.reload();
    } catch (error) {
      pushToast({ title: "Could not resend", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setBusy(null);
    }
  };

  const speakTemplate = (template: AlertTemplate, language: "en" | "ar") => {
    speak([{ language, text: template[language] }]);
  };

  const settingsData = settings.data?.settings;
  const alerting = settingsData?.alarm;
  const voice = settingsData?.voice;

  return (
    <div className="page page--alerts">
      <div className="page-toolbar">
        <div className="page-toolbar__left">
          <span className={cx("live-chip", pendingAlerts.length > 0 && "live-chip--danger")}>
            <span className="live-chip__dot" /> ALARM CHAIN {pendingAlerts.length > 0 ? "ACTIVE" : "STANDBY"}
          </span>
          <span className="muted">
            {pendingAlerts.length} warning{pendingAlerts.length === 1 ? "" : "s"} awaiting playback · EN + AR bilingual ·
            siren {sirenEnabled ? "armed" : "disabled"}
          </span>
        </div>
        <div className="page-toolbar__actions">
          <button type="button" className={cx("btn btn--sm", voiceEnabled ? "btn--ghost" : "btn--primary")} onClick={toggleVoice}>
            {voiceEnabled ? <IconVolume size={15} /> : <IconVolumeOff size={15} />}
            {voiceEnabled ? "Voice armed" : "Voice muted"}
          </button>
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => void refreshPending()}>
            <IconRefresh size={14} /> Refresh queue
          </button>
        </div>
      </div>

      <div className="alarm-readiness">
        <div className={cx("readiness", voiceEnabled && "is-ready")}>
          <span className="readiness__icon"><IconVolume size={19} /></span>
          <span>
            <small>Voice warnings</small>
            <strong>{voiceEnabled ? "Armed" : "Muted"}</strong>
            <em>{speechSupported() ? "Browser speech synthesis ready" : "Speech API unavailable in this browser"}</em>
          </span>
          <button type="button" className="btn btn--ghost btn--xs" onClick={toggleVoice}>
            {voiceEnabled ? "Mute" : "Arm"}
          </button>
        </div>
        <div className={cx("readiness", sirenEnabled && "is-ready")}>
          <span className="readiness__icon"><IconAlerts size={19} /></span>
          <span>
            <small>Emergency siren</small>
            <strong>{sirenEnabled ? "Armed" : "Disabled"}</strong>
            <em>{alerting?.siren_enabled ? "Backend siren channel enabled" : "Enable in Settings → Voice & siren"}</em>
          </span>
          <button type="button" className="btn btn--ghost btn--xs" onClick={() => { setSirenEnabled(!sirenEnabled); pushToast({ title: sirenEnabled ? "Siren muted locally" : "Siren armed locally", message: "Critical alerts will trigger the audio siren", tone: sirenEnabled ? "info" : "warning" }); }}>
            {sirenEnabled ? "Disarm" : "Arm"}
          </button>
        </div>
        <div className="readiness">
          <span className="readiness__icon"><IconShield size={19} /></span>
          <span>
            <small>Repeat interval</small>
            <strong>{voice?.repeat_seconds ?? 20}s</strong>
            <em>{voice?.languages?.join(" / ").toUpperCase() ?? "EN / AR"} · until acknowledged</em>
          </span>
          <Link to="/settings" className="btn btn--ghost btn--xs">
            <IconSettings size={13} /> Tune
          </Link>
        </div>
        <div className={cx("readiness", alerting?.notify_admin && "is-ready")}>
          <span className="readiness__icon"><IconWarning size={19} /></span>
          <span>
            <small>Remote notification</small>
            <strong>{alerting?.notify_admin ? "Admin notified" : "Disabled"}</strong>
            <em>{alerting?.webhook_url ? "Webhook configured" : "No external webhook"}</em>
          </span>
          <Link to="/settings" className="btn btn--ghost btn--xs">Configure</Link>
        </div>
      </div>

      <Panel
        title="Pending bilingual warnings"
        subtitle="Live queue from the emergency response chain · plays automatically when a screen is armed"
        accent={pendingAlerts.length ? "red" : "green"}
        actions={<TonePill tone={pendingAlerts.length ? "red" : "green"}>{pendingAlerts.length} QUEUED</TonePill>}
      >
        {pendingAlerts.length ? (
          <div className="pending-alerts">
            {pendingAlerts.map((alert) => (
              <div className={cx("pending-alert", alert.language === "ar" && "pending-alert--ar")} key={alert.id} dir={alert.language === "ar" ? "rtl" : "ltr"}>
                <div className="pending-alert__top">
                  <span className={cx("pending-alert__lang", alert.language === "ar" && "is-ar")}>
                    {alert.language === "ar" ? "ARABIC WARNING" : "ENGLISH WARNING"}
                  </span>
                  {alert.incident_level && <LevelBadge level={alert.incident_level} pulse />}
                  <span className="pending-alert__time">
                    <IconClock size={13} /> {alert.detected_at ? formatRelative(alert.detected_at) : "queued"}
                  </span>
                </div>
                <p className="pending-alert__message">{alert.message}</p>
                <div className="pending-alert__meta">
                  <span className="mono">{alert.incident_code ?? `INC-${alert.incident_id}`}</span>
                  <span>{alert.incident_title}</span>
                  <span>{alert.status.replace(/_/g, " ")}</span>
                </div>
                <div className="pending-alert__actions">
                  <button type="button" className="btn btn--danger btn--sm" disabled={busy === alert.id} onClick={() => void play(alert)}>
                    {busy === alert.id ? <span className="spinner spinner--sm" /> : <IconPlay size={14} />} Play warning
                  </button>
                  {can("acknowledge_alarms") && (
                    <button type="button" className="btn btn--ghost btn--sm" disabled={busy === alert.id} onClick={() => void acknowledge(alert)}>
                      <IconCheck size={14} /> Acknowledge
                    </button>
                  )}
                  {alert.incident_id && (
                    <Link className="btn btn--ghost btn--sm" to={`/threat/${alert.incident_id}`}>
                      Open threat screen
                    </Link>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<IconShield size={28} />}
            title="No warnings queued"
            message="Every verified incident has been played and acknowledged. New threats will appear here instantly."
          />
        )}
      </Panel>

      <Panel
        title="Alert history"
        subtitle="Every channel dispatch with delivery state and audit reference"
        actions={
          <div className="btn-row">
            <span className="mono muted">{alerts.data?.total ?? 0} RECORDS</span>
            <button type="button" className="btn btn--ghost btn--xs" onClick={alerts.reload}>
              <IconRefresh size={13} />
            </button>
          </div>
        }
        bodyClassName="panel__body--flush"
      >
        <div className="filter-bar">
          <select className="select" value={channel} onChange={(event) => { setChannel(event.target.value); setOffset(0); }}>
            {CHANNELS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          <select className="select" value={status} onChange={(event) => { setStatus(event.target.value); setOffset(0); }}>
            {STATUSES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          <span className="filter-bar__count">
            {counts.voice} voice · {counts.notifications} notifications · {counts.sirens} sirens on this page
          </span>
        </div>

        {alerts.loading && !alerts.data ? (
          <LoadingState label="Loading alert history…" />
        ) : alerts.error ? (
          <ErrorState message={alerts.error} retry={alerts.reload} />
        ) : alerts.data?.items.length ? (
          <>
            <div className="data-table">
              <div className="data-table__head alerts-row">
                <span>Channel</span>
                <span>Incident</span>
                <span>Message</span>
                <span>Language</span>
                <span>Status</span>
                <span>Created</span>
                <span />
              </div>
              {alerts.data.items.map((alert) => (
                <div className="data-table__row alerts-row" key={alert.id}>
                  <span className="cell-stack">
                    <strong className="channel-name">
                      {alert.channel === "voice" ? <IconVolume size={14} /> : alert.channel === "siren" ? <IconAlerts size={14} /> : <IconWarning size={14} />}
                      {humanize(alert.channel)}
                    </strong>
                    <small>#{alert.id} · {alert.sent_to || "operator screen"}</small>
                  </span>
                  <span className="cell-stack">
                    {alert.incident_id ? (
                      <Link to={`/threat/${alert.incident_id}`} className="table-link">
                        {alert.incident_code ?? `Incident ${alert.incident_id}`}
                      </Link>
                    ) : (
                      <strong>—</strong>
                    )}
                    <small>{alert.incident_level ? <LevelBadge level={alert.incident_level} /> : "unknown level"}</small>
                  </span>
                  <span className="cell-clip" dir={alert.language === "ar" ? "rtl" : "ltr"} title={alert.message}>
                    {alert.message}
                  </span>
                  <span className="mono">{alert.language.toUpperCase()}</span>
                  <span><TonePill tone={statusTone(alert.status)}>{alert.status.replace(/_/g, " ")}</TonePill></span>
                  <span className="cell-time">
                    {formatTime(alert.created_at, true)}
                    <small>{formatRelative(alert.created_at)}</small>
                  </span>
                  <span className="row-actions">
                    {alert.channel === "voice" && (
                      <>
                        <button type="button" className="icon-btn" disabled={busy === alert.id} title="Play warning" onClick={() => void play(alert)}>
                          <IconPlay size={14} />
                        </button>
                        <button type="button" className="icon-btn" disabled={busy === alert.id} title="Stop warning" onClick={() => void stop(alert)}>
                          <IconStop size={14} />
                        </button>
                      </>
                    )}
                    {alert.channel !== "voice" && alert.channel !== "siren" && can("acknowledge_alarms") && (
                      <button type="button" className="icon-btn" disabled={busy === alert.id} title="Resend notification" onClick={() => void resend(alert)}>
                        <IconRefresh size={14} />
                      </button>
                    )}
                    {alert.status !== "acknowledged" && can("acknowledge_alarms") && (
                      <button type="button" className="icon-btn icon-btn--success" disabled={busy === alert.id} title="Acknowledge alert" onClick={() => void acknowledge(alert)}>
                        <IconCheck size={14} />
                      </button>
                    )}
                  </span>
                </div>
              ))}
            </div>
            <Pagination total={alerts.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        ) : (
          <EmptyState title="No alerts recorded" message="The alarm chain has not dispatched any messages for this filter." />
        )}
      </Panel>

      <Panel title="Bilingual warning templates" subtitle="Automatically filled with camera number and location" bodyClassName="panel__body--flush">
        {templates.loading && !templates.data ? (
          <LoadingState label="Loading voice templates…" />
        ) : templates.error ? (
          <ErrorState message={templates.error} retry={templates.reload} />
        ) : (
          <div className="templates">
            {templates.data?.templates.map((template) => (
              <div className="template" key={template.threat_type}>
                <div className="template__head">
                  <strong>{template.label}</strong>
                  <TonePill tone="muted">{template.threat_type}</TonePill>
                </div>
                <div className="template__lang">
                  <span className="template__tag">EN</span>
                  <p>{template.en}</p>
                  <button type="button" className="btn btn--ghost btn--xs" onClick={() => speakTemplate(template, "en")}>
                    <IconVolume size={13} /> Play
                  </button>
                </div>
                <div className="template__lang template__lang--ar" dir="rtl">
                  <span className="template__tag">AR</span>
                  <p>{template.ar}</p>
                  <button type="button" className="btn btn--ghost btn--xs" onClick={() => speakTemplate(template, "ar")}>
                    <IconVolume size={13} /> تشغيل
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Alarm policy" subtitle="How the response chain behaves" accent="amber">
        <div className="policy-grid">
          <div className="policy">
            <span className="policy__step">1</span>
            <strong>Verified detection</strong>
            <p>Multi-frame confirmation and zone presence must both pass before an incident exists.</p>
          </div>
          <div className="policy">
            <span className="policy__step">2</span>
            <strong>Bilingual warning</strong>
            <p>English and Arabic warnings are queued together. The operator screen speaks them in order.</p>
          </div>
          <div className="policy">
            <span className="policy__step">3</span>
            <strong>Escalation</strong>
            <p>Warnings repeat every {voice?.repeat_seconds ?? 20}s until an operator acknowledges the incident.</p>
          </div>
          <div className="policy">
            <span className="policy__step">4</span>
            <strong>Evidence &amp; audit</strong>
            <p>Snapshot, clip, alert log and acknowledgement are stored with the incident for later review.</p>
          </div>
        </div>
        <div className="policy-toggle">
          <Toggle
            checked={sirenEnabled}
            onChange={(value) => {
              setSirenEnabled(value);
              pushToast({ title: value ? "Siren armed" : "Siren disarmed", message: "This affects siren playback on this browser", tone: value ? "warning" : "info" });
            }}
            label="Siren playback in this browser"
            description="Plays a local audio siren for critical incidents when the alarm chain triggers."
          />
          <Toggle
            checked={voiceEnabled}
            onChange={toggleVoice}
            label="Bilingual voice synthesis"
            description="Speaks queued English and Arabic warnings using the browser speech engine."
          />
        </div>
      </Panel>
    </div>
  );
}

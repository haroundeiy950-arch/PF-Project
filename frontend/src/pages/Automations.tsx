import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { useRealtime } from "../context/RealtimeContext";
import { useDocumentTitle, useResource } from "../hooks/useResource";
import { LEVEL_LABELS, cx, humanize } from "../lib/format";
import { speak } from "../voice";
import type { AlertTemplate, AppSettings, Level, RiskPreview } from "../types";
import {
  IconActivity,
  IconAlerts,
  IconAutomations,
  IconCheck,
  IconCpu,
  IconLink,
  IconPlay,
  IconRefresh,
  IconSettings,
  IconShield,
  IconTarget,
  IconVolume,
  IconWarning,
} from "../components/Icons";
import {
  BarList,
  ErrorState,
  LevelBadge,
  LoadingState,
  Panel,
  ScoreRing,
  TonePill,
  Toggle,
} from "../components/UI";

const CHAIN = [
  {
    key: "detect",
    title: "AI detection",
    detail: "YOLO / demo detector finds a person, vehicle or face in the frame and a tracker assigns a stable track ID.",
    state: "always",
  },
  {
    key: "verify",
    title: "Multi-frame verification",
    detail: "The target must persist for the minimum frames and dwell time before it can become an incident. Static objects are discarded.",
    state: "always",
  },
  {
    key: "score",
    title: "Risk scoring",
    detail: "Zone, target, time, dwell, face, repetition and behaviour are weighted into a 0–100 score with a written explanation.",
    state: "always",
  },
  {
    key: "voice",
    title: "Bilingual warning",
    detail: "English and Arabic voice warnings are queued with camera number and name. Repetition stops the moment an operator acknowledges.",
    state: "policy",
  },
  {
    key: "record",
    title: "Evidence capture",
    detail: "Snapshot plus a pre/post-event clip are attached to the incident, then listed in Playback and Reports.",
    state: "policy",
  },
  {
    key: "escalate",
    title: "Emergency escalation",
    detail: "Critical incidents sound the siren, notify the administrator and, when configured, call the webhook.",
    state: "policy",
  },
];

const LEVEL_ACTIONS: Record<
  Level,
  { tone: "green" | "cyan" | "amber" | "red"; actions: string[] }
> = {
  normal: {
    tone: "green",
    actions: ["Log the event", "Keep monitoring", "No siren, no voice warning"],
  },
  medium: {
    tone: "cyan",
    actions: ["Record a clip around the event", "Raise a dashboard warning", "Add to the event ledger"],
  },
  high: {
    tone: "amber",
    actions: [
      "English + Arabic voice warning",
      "Notify the control-room operator",
      "Attach snapshot and clip",
      "Start the acknowledgment countdown",
    ],
  },
  critical: {
    tone: "red",
    actions: [
      "Flashing DANGER threat screen",
      "Siren for 8 seconds",
      "English + Arabic voice warning",
      "Notify the administrator",
      "Escalate to the emergency webhook",
    ],
  },
};

function fillTemplate(template: AlertTemplate, language: "en" | "ar"): string {
  return template[language]
    .replace(/\{camera_number\}/g, "CAM-01")
    .replace(/\{camera_name\}/g, "Main Gate");
}

interface SimulatorState {
  zone_type: "restricted" | "limited" | "public";
  target_type: "person" | "vehicle" | "animal" | "unknown";
  hour: number;
  dwell_seconds: number;
  dwell_target: number;
  face_status: "known" | "unknown" | "none" | "low_quality";
  repetition: number;
  behavior: "normal" | "loitering" | "erratic" | "running";
  inside_zone: boolean;
}

const DEFAULT_SIM: SimulatorState = {
  zone_type: "restricted",
  target_type: "person",
  hour: 2,
  dwell_seconds: 9,
  dwell_target: 2,
  face_status: "unknown",
  repetition: 3,
  behavior: "loitering",
  inside_zone: true,
};

export default function Automations() {
  useDocumentTitle("Emergency Automation");
  const { can } = useAuth();
  const { sirenEnabled, setSirenEnabled, pushToast, statsVersion } = useRealtime();
  const [sim, setSim] = useState<SimulatorState>(DEFAULT_SIM);
  const [alarmDraft, setAlarmDraft] = useState<AppSettings["alarm"] | null>(null);
  const [voiceDraft, setVoiceDraft] = useState<AppSettings["voice"] | null>(null);
  const [saving, setSaving] = useState("");

  const settings = useResource(() => api.settings.get(), [statsVersion]);
  const templates = useResource(() => api.alerts.templates(), []);
  const preview = useResource<RiskPreview>(() => api.settings.preview(sim), [JSON.stringify(sim)]);

  const alarm = alarmDraft ?? settings.data?.settings.alarm;
  const voice = voiceDraft ?? settings.data?.settings.voice;
  const thresholds = settings.data?.settings.risk_thresholds ?? { medium: 30, high: 60, critical: 85 };
  const weights = settings.data?.settings.risk_weights ?? {};

  const weightTotal = useMemo(
    () => Object.values(weights).reduce((total, value) => total + Number(value), 0),
    [weights],
  );

  const patchSim = <K extends keyof SimulatorState>(key: K, value: SimulatorState[K]) => {
    setSim((current) => ({ ...current, [key]: value }));
  };

  const saveAlarm = async (next: AppSettings["alarm"]) => {
    if (!can("manage_settings")) {
      pushToast({ title: "Read-only role", message: "An administrator must change alarm policy.", tone: "warning" });
      return;
    }
    setSaving("alarm");
    setAlarmDraft(next);
    try {
      await api.settings.updateGroup("alarm", next);
      setSirenEnabled(Boolean(next.siren_enabled));
      pushToast({ title: "Alarm policy saved", message: "Camera workers pick up the policy within seconds.", tone: "success" });
      settings.reload();
    } catch (error) {
      setAlarmDraft(null);
      pushToast({
        title: "Could not save alarm policy",
        message: error instanceof Error ? error.message : "Request failed",
        tone: "danger",
      });
    } finally {
      setSaving("");
    }
  };

  const saveVoice = async (next: AppSettings["voice"]) => {
    if (!can("manage_settings")) {
      pushToast({ title: "Read-only role", message: "An administrator must change voice policy.", tone: "warning" });
      return;
    }
    setSaving("voice");
    setVoiceDraft(next);
    try {
      await api.settings.updateGroup("voice", next);
      pushToast({ title: "Voice policy saved", message: "Bilingual warnings updated.", tone: "success" });
      settings.reload();
    } catch (error) {
      setVoiceDraft(null);
      pushToast({
        title: "Could not save voice policy",
        message: error instanceof Error ? error.message : "Request failed",
        tone: "danger",
      });
    } finally {
      setSaving("");
    }
  };

  const result = preview.data;
  const level: Level = result?.level ?? "normal";
  const forecast = LEVEL_ACTIONS[level];
  const templatesList = templates.data?.templates ?? [];

  return (
    <div className="page page--automations">
      <div className="page-toolbar">
        <div className="page-toolbar__left">
          <span className={cx("live-chip", sirenEnabled && "live-chip--danger")}>
            <span className="live-chip__dot" /> RESPONSE CHAIN {sirenEnabled ? "ARMED" : "MONITOR"}
          </span>
          <span className="muted">
            AI verification → risk scoring → bilingual warning → acknowledgment → emergency escalation
          </span>
        </div>
        <div className="page-toolbar__actions">
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => { settings.reload(); templates.reload(); preview.reload(); }}>
            <IconRefresh size={14} /> Reload policy
          </button>
          <Link to="/alerts" className="btn btn--ghost btn--sm">
            <IconAlerts size={14} /> Alert queue
          </Link>
          <Link to="/settings" className="btn btn--primary btn--sm">
            <IconSettings size={14} /> Configure
          </Link>
        </div>
      </div>

      <div className="stat-strip">
        <div className={cx("stat-tile", sirenEnabled ? "stat-tile--red" : "stat-tile--green")}>
          <span className="stat-tile__icon"><IconVolume size={18} /></span>
          <span>
            <small>Voice warnings</small>
            <strong>{voice?.enabled ? "Armed" : "Muted"}</strong>
            <em>{(voice?.languages ?? ["en"]).map((code) => code.toUpperCase()).join(" + ")} · repeat {voice?.repeat_seconds ?? 20}s</em>
          </span>
        </div>
        <div className={cx("stat-tile", sirenEnabled ? "stat-tile--red" : "stat-tile--green")}>
          <span className="stat-tile__icon"><IconWarning size={18} /></span>
          <span>
            <small>Emergency siren</small>
            <strong>{sirenEnabled ? "Armed" : "Disabled"}</strong>
            <em>Critical incidents only</em>
          </span>
        </div>
        <div className="stat-tile stat-tile--cyan">
          <span className="stat-tile__icon"><IconTarget size={18} /></span>
          <span>
            <small>Critical threshold</small>
            <strong>{thresholds.critical}</strong>
            <em>Escalates to admin + siren</em>
          </span>
        </div>
        <div className="stat-tile stat-tile--amber">
          <span className="stat-tile__icon"><IconAutomations size={18} /></span>
          <span>
            <small>Voice templates</small>
            <strong>{templates.data?.templates.length ?? "—"}</strong>
            <em>{weightTotal} risk points configured</em>
          </span>
        </div>
      </div>

      <div className="automation-layout">
        <div className="automation-layout__main">
          <Panel
            title="Alarm escalation chain"
            subtitle="Every incident passes through the same verifiable sequence"
            accent="red"
          >
            <ol className="chain">
              {CHAIN.map((step, index) => (
                <li key={step.key} className="chain__step">
                  <span className="chain__index">{String(index + 1).padStart(2, "0")}</span>
                  <div className="chain__body">
                    <div className="chain__head">
                      <strong>{step.title}</strong>
                      {step.state === "always" ? (
                        <TonePill tone="cyan">ALWAYS ON</TonePill>
                      ) : (
                        <TonePill tone="amber">POLICY</TonePill>
                      )}
                    </div>
                    <p>{step.detail}</p>
                  </div>
                  <span className="chain__state">
                    <IconCheck size={15} /> active
                  </span>
                </li>
              ))}
            </ol>
          </Panel>

          <Panel
            title="Response matrix"
            subtitle="What the system does at each verified risk level"
            bodyClassName="panel__body--flush"
          >
            <div className="response-matrix">
              {(["critical", "high", "medium", "normal"] as Level[]).map((item) => (
                <div key={item} className={cx("response-row", `response-row--${item}`)}>
                  <div className="response-row__level">
                    <LevelBadge level={item} />
                    <span className="mono">≥ {thresholds[item] ?? 0}</span>
                  </div>
                  <div className="response-row__actions">
                    {LEVEL_ACTIONS[item].actions.map((action) => (
                      <span key={action} className="response-chip">{action}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <p className="safety-note safety-note--pad">
              <IconShield size={15} />
              Voice repetition stops at acknowledgment. A critical incident still needs a human decision before it is resolved or
              marked as a false alarm.
            </p>
          </Panel>

          <Panel
            title="Bilingual voice templates"
            subtitle="Camera number and name are filled in automatically at alert time"
            actions={<span className="mono muted">{templatesList.length} templates</span>}
          >
            {templates.loading && !templates.data ? (
              <LoadingState label="Loading voice templates…" />
            ) : templates.error ? (
              <ErrorState message={templates.error} retry={templates.reload} />
            ) : (
              <div className="voice-templates">
                {templatesList.map((template) => (
                  <div className="voice-template" key={template.threat_type}>
                    <div className="voice-template__head">
                      <strong>{template.label}</strong>
                      <span className="mono muted">{humanize(template.threat_type)}</span>
                    </div>
                    <div className="voice-template__row">
                      <span className="voice-template__lang">EN</span>
                      <p>{template.en}</p>
                      <button
                        type="button"
                        className="icon-btn"
                        title="Play English warning"
                        onClick={() => speak([{ language: "en", text: fillTemplate(template, "en") }])}
                      >
                        <IconPlay size={14} />
                      </button>
                    </div>
                    <div className="voice-template__row voice-template__row--ar" dir="rtl">
                      <span className="voice-template__lang">AR</span>
                      <p>{template.ar}</p>
                      <button
                        type="button"
                        className="icon-btn"
                        title="Play Arabic warning"
                        onClick={() => speak([{ language: "ar", text: fillTemplate(template, "ar") }])}
                      >
                        <IconPlay size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>

        <aside className="automation-layout__side">
          <Panel
            title="Risk simulator"
            subtitle="Score an imaginary detection without touching a camera"
            accent="red"
            actions={
              <button type="button" className="icon-btn" onClick={preview.reload} title="Re-evaluate">
                <IconRefresh size={15} />
              </button>
            }
          >
            <div className="simulator">
              <div className="simulator__verdict">
                {preview.loading && !result ? (
                  <span className="spinner" />
                ) : result ? (
                  <>
                    <ScoreRing score={result.score} level={result.level} size={116} />
                    <div>
                      <span className="eyebrow">Predicted verdict</span>
                      <strong>{LEVEL_LABELS[result.level]}</strong>
                      <p>{result.explanation}</p>
                    </div>
                  </>
                ) : (
                  <span className="muted">Adjust the scenario to preview a score.</span>
                )}
              </div>

              {preview.error && <ErrorState message={preview.error} retry={preview.reload} />}

              <div className="simulator__form">
                <label className="field">
                  <span>Zone type</span>
                  <select className="select" value={sim.zone_type} onChange={(event) => patchSim("zone_type", event.target.value as SimulatorState["zone_type"])}>
                    <option value="restricted">Restricted area</option>
                    <option value="limited">Limited access</option>
                    <option value="public">Public area</option>
                  </select>
                </label>
                <label className="field">
                  <span>Target</span>
                  <select className="select" value={sim.target_type} onChange={(event) => patchSim("target_type", event.target.value as SimulatorState["target_type"])}>
                    <option value="person">Person</option>
                    <option value="vehicle">Vehicle</option>
                    <option value="animal">Animal</option>
                    <option value="unknown">Unknown</option>
                  </select>
                </label>
                <label className="field">
                  <span>Hour of day · {String(sim.hour).padStart(2, "0")}:00</span>
                  <input type="range" min={0} max={23} value={sim.hour} onChange={(event) => patchSim("hour", Number(event.target.value))} />
                </label>
                <label className="field">
                  <span>Dwell time · {sim.dwell_seconds}s</span>
                  <input type="range" min={0} max={60} value={sim.dwell_seconds} onChange={(event) => patchSim("dwell_seconds", Number(event.target.value))} />
                </label>
                <label className="field">
                  <span>Face status</span>
                  <select className="select" value={sim.face_status} onChange={(event) => patchSim("face_status", event.target.value as SimulatorState["face_status"])}>
                    <option value="unknown">Unknown face</option>
                    <option value="known">Known / authorized</option>
                    <option value="low_quality">Low quality</option>
                    <option value="none">No face visible</option>
                  </select>
                </label>
                <label className="field">
                  <span>Behaviour</span>
                  <select className="select" value={sim.behavior} onChange={(event) => patchSim("behavior", event.target.value as SimulatorState["behavior"])}>
                    <option value="normal">Normal movement</option>
                    <option value="loitering">Loitering</option>
                    <option value="erratic">Erratic movement</option>
                    <option value="running">Running</option>
                  </select>
                </label>
                <label className="field">
                  <span>Repetition · {sim.repetition}×</span>
                  <input type="range" min={1} max={8} value={sim.repetition} onChange={(event) => patchSim("repetition", Number(event.target.value))} />
                </label>
                <Toggle
                  checked={sim.inside_zone}
                  onChange={(value) => patchSim("inside_zone", value)}
                  label="Inside the zone polygon"
                  description="Turn off to model a target outside the zone."
                />
              </div>

              {result && (
                <>
                  <div className="simulator__actions">
                    <span className={cx("tone-pill", `tone-pill--${forecast.tone}`)}>AUTOMATION FORECAST</span>
                    <div className="response-chips">
                      {forecast.actions.map((action) => (
                        <span key={action} className="response-chip">{action}</span>
                      ))}
                    </div>
                  </div>
                  <BarList
                    color={result.level === "critical" ? "red" : result.level === "high" ? "amber" : "cyan"}
                    items={Object.values(result.factors).map((factor) => ({
                      label: factor.label,
                      value: Math.round(factor.contribution * 10) / 10,
                      hint: `weight ${factor.weight} · normalized ${Math.round(factor.normalized * 100)}%`,
                    }))}
                  />
                </>
              )}
            </div>
          </Panel>

          <Panel title="Live alarm policy" subtitle="Saved instantly to every camera worker">
            {settings.loading && !settings.data ? (
              <LoadingState label="Loading policy…" />
            ) : settings.error ? (
              <ErrorState message={settings.error} retry={settings.reload} />
            ) : alarm && voice ? (
              <div className="policy-stack">
                <Toggle
                  checked={alarm.siren_enabled}
                  onChange={(value) => void saveAlarm({ ...alarm, siren_enabled: value })}
                  label="Emergency siren"
                  description="Sounds for 8 seconds on a critical incident."
                  disabled={saving === "alarm"}
                />
                <Toggle
                  checked={alarm.notify_admin}
                  onChange={(value) => void saveAlarm({ ...alarm, notify_admin: value })}
                  label="Notify administrator"
                  description="Sends an alarm notification to every administrator."
                  disabled={saving === "alarm"}
                />
                <Toggle
                  checked={voice.enabled}
                  onChange={(value) => void saveVoice({ ...voice, enabled: value })}
                  label="Bilingual voice warnings"
                  description="English and Arabic templates for every verified threat."
                  disabled={saving === "voice"}
                />
                <div className="policy-field">
                  <span>Repeat interval</span>
                  <div className="policy-field__row">
                    <input
                      type="range"
                      min={5}
                      max={120}
                      step={5}
                      value={voice.repeat_seconds}
                      onChange={(event) => void saveVoice({ ...voice, repeat_seconds: Number(event.target.value) })}
                      disabled={saving === "voice"}
                    />
                    <strong>{voice.repeat_seconds}s</strong>
                  </div>
                  <small>Repeating stops as soon as an operator acknowledges.</small>
                </div>
                <div className="policy-field">
                  <span>Warning languages</span>
                  <div className="check-row">
                    {[
                      { code: "en", label: "English" },
                      { code: "ar", label: "العربية" },
                    ].map((language) => (
                      <label className="check-field check-field--compact" key={language.code}>
                        <input
                          type="checkbox"
                          checked={voice.languages.includes(language.code)}
                          onChange={(event) => {
                            const next = event.target.checked
                              ? [...voice.languages, language.code]
                              : voice.languages.filter((item) => item !== language.code);
                            void saveVoice({ ...voice, languages: next.length ? next : ["en"] });
                          }}
                          disabled={saving === "voice"}
                        />
                        <span>{language.label}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="policy-link">
                  <IconLink size={15} />
                  <span>
                    Webhook: <strong>{alarm.webhook_url || "not configured"}</strong>
                  </span>
                  <Link to="/settings" className="btn btn--ghost btn--xs">Edit</Link>
                </div>
                {!can("manage_settings") && (
                  <p className="safety-note">
                    <IconWarning size={15} />
                    Your role can view this policy but not change it.
                  </p>
                )}
              </div>
            ) : (
              <span className="muted">Policy unavailable.</span>
            )}
          </Panel>

          <Panel title="Escalation thresholds" subtitle="Risk score boundaries" accent="amber">
            <div className="threshold-list">
              {[
                { level: "critical" as Level, min: thresholds.critical, detail: "Siren + admin + emergency webhook" },
                { level: "high" as Level, min: thresholds.high, detail: "Voice warning + operator notification" },
                { level: "medium" as Level, min: thresholds.medium, detail: "Dashboard warning + clip" },
                { level: "normal" as Level, min: 0, detail: "Logged, no alarm" },
              ].map((row) => (
                <div className={cx("threshold-row", `threshold-row--${row.level}`)} key={row.level}>
                  <LevelBadge level={row.level} />
                  <span className="mono">≥ {row.min}</span>
                  <small>{row.detail}</small>
                </div>
              ))}
            </div>
            <p className="safety-note">
              <IconCpu size={15} />
              Thresholds are enforced on the server. Changing them affects new incidents only; existing scores are immutable.
            </p>
          </Panel>

          <Panel title="Operator responsibility" subtitle="Human-in-the-loop safeguards">
            <ul className="plain-list">
              <li><IconActivity size={14} /> Every incident keeps its arithmetic explanation.</li>
              <li><IconCheck size={14} /> Acknowledgment requires an authenticated user.</li>
              <li><IconWarning size={14} /> False alarms are recorded for model tuning.</li>
              <li><IconShield size={14} /> Face recognition stays consent-first.</li>
            </ul>
          </Panel>
        </aside>
      </div>
    </div>
  );
}

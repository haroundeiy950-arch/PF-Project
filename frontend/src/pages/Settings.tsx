import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { useRealtime } from "../context/RealtimeContext";
import { useDocumentTitle, useResource } from "../hooks/useResource";
import {
  cx,
  formatDate,
  formatDateTime,
  humanize,
  initials,
} from "../lib/format";
import type { AppSettings, AuditEntry, PermissionRole, SettingsMetadata, SystemInfo, User } from "../types";
import {
  IconActivity,
  IconAlerts,
  IconCamera,
  IconCheck,
  IconClose,
  IconCpu,
  IconDatabase,
  IconEdit,
  IconLock,
  IconPlus,
  IconRefresh,
  IconSettings,
  IconShield,
  IconTrash,
  IconUser,
  IconVolume,
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
  Toggle,
} from "../components/UI";

type SettingsTab = "general" | "risk" | "alarm" | "ai" | "users" | "audit";

const TABS: { key: SettingsTab; label: string; icon: typeof IconSettings; permission?: string }[] = [
  { key: "general", label: "General", icon: IconSettings },
  { key: "risk", label: "Risk & verification", icon: IconCpu },
  { key: "alarm", label: "Alarm & voice", icon: IconVolume },
  { key: "ai", label: "AI & recording", icon: IconCamera },
  { key: "users", label: "Users & roles", icon: IconUser, permission: "manage_users" },
  { key: "audit", label: "Audit log", icon: IconShield, permission: "view_audit" },
];

const AUDIT_PAGE = 40;

interface UserFormValues {
  username: string;
  full_name: string;
  email: string;
  password: string;
  role: string;
  is_active: boolean;
}

function UserDialog({
  open,
  user,
  roles,
  busy,
  onClose,
  onSubmit,
}: {
  open: boolean;
  user: User | null;
  roles: { name: string; label: string }[];
  busy: boolean;
  onClose: () => void;
  onSubmit: (values: UserFormValues) => Promise<void>;
}) {
  const [username, setUsername] = useState(user?.username ?? "");
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState(user?.role?.name ?? "viewer");
  const [active, setActive] = useState(user?.is_active ?? true);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!user && username.trim().length < 3) {
      setError("Username must be at least 3 characters.");
      return;
    }
    if (!user && password.length < 6) {
      setError("Set an initial password of at least 6 characters.");
      return;
    }
    if (password && password.length < 6) {
      setError("A new password must be at least 6 characters.");
      return;
    }
    setError("");
    await onSubmit({
      username: username.trim().toLowerCase(),
      full_name: fullName.trim(),
      email: email.trim(),
      password,
      role,
      is_active: active,
    });
  };

  return (
    <Modal
      open={open}
      title={user ? `Edit ${user.username}` : "Create user"}
      subtitle={user ? user.role.label : "Role-based access for the control center"}
      onClose={onClose}
      size="md"
      footer={
        <div className="modal__footer-row">
          <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>Cancel</button>
          <button type="submit" form="user-form" className="btn btn--primary btn--sm" disabled={busy}>
            {busy ? <span className="spinner spinner--sm" /> : <IconCheck size={14} />}
            {user ? "Save user" : "Create user"}
          </button>
        </div>
      }
    >
      <form id="user-form" className="form-stack" onSubmit={submit}>
        {error && <div className="form-error"><IconWarning size={15} /> {error}</div>}
        <div className="form-grid">
          <label className="field">
            <span>Username *</span>
            <input
              value={username}
              required
              minLength={3}
              maxLength={60}
              disabled={Boolean(user)}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="e.g. night.operator"
            />
          </label>
          <label className="field">
            <span>Role</span>
            <select className="select" value={role} onChange={(event) => setRole(event.target.value)}>
              {roles.map((item) => <option key={item.name} value={item.name}>{item.label}</option>)}
            </select>
          </label>
        </div>
        <label className="field">
          <span>Full name</span>
          <input value={fullName} maxLength={120} onChange={(event) => setFullName(event.target.value)} placeholder="e.g. Layla Haddad" />
        </label>
        <label className="field">
          <span>Email</span>
          <input type="email" value={email} maxLength={160} onChange={(event) => setEmail(event.target.value)} placeholder="operator@example.com" />
        </label>
        <label className="field">
          <span>{user ? "Reset password (optional)" : "Initial password *"}</span>
          <input
            type="password"
            value={password}
            minLength={6}
            onChange={(event) => setPassword(event.target.value)}
            placeholder={user ? "Leave blank to keep the current password" : "At least 6 characters"}
            autoComplete="new-password"
          />
        </label>
        <Toggle
          checked={active}
          onChange={setActive}
          label="Account active"
          description={user ? "Disabling keeps audit history and acknowledgments intact." : "Inactive accounts cannot sign in."}
        />
      </form>
    </Modal>
  );
}

export default function Settings() {
  useDocumentTitle("System Settings");
  const { can, user, refresh } = useAuth();
  const { pushToast, statsVersion } = useRealtime();
  const [tab, setTab] = useState<SettingsTab>("general");
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [busyAction, setBusyAction] = useState("");
  const [userDialog, setUserDialog] = useState<{ open: boolean; user: User | null }>({ open: false, user: null });
  const [userBusy, setUserBusy] = useState(false);
  const [confirmUser, setConfirmUser] = useState<User | null>(null);
  const [auditAction, setAuditAction] = useState("");
  const [auditOffset, setAuditOffset] = useState(0);
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);

  const canManage = can("manage_settings");
  const canUsers = can("manage_users");
  const canAudit = can("view_audit");

  const settings = useResource(() => api.settings.get(), [statsVersion]);
  const systemInfo = useResource(() => api.system.info(), [statsVersion]);
  const users = useResource(
    () => (canUsers ? api.users.list() : Promise.resolve({ items: [] as User[], total: 0 })),
    [canUsers, statsVersion],
  );
  const matrix = useResource(
    () =>
      canUsers
        ? api.users.matrix()
        : Promise.resolve({ permissions: [] as string[], roles: [] as PermissionRole[] }),
    [canUsers, statsVersion],
  );
  const auditActions = useResource(
    () => (canAudit ? api.users.auditActions() : Promise.resolve({ items: [] as { action: string; count: number }[] })),
    [canAudit],
  );
  const auditPage = useResource(
    () =>
      canAudit
        ? api.users.audit({ action: auditAction || undefined, limit: AUDIT_PAGE, offset: auditOffset })
        : Promise.resolve({ items: [] as AuditEntry[], total: 0, limit: AUDIT_PAGE, offset: 0 }),
    [canAudit, auditAction, auditOffset, statsVersion],
  );

  useEffect(() => {
    if (!settings.data) return;
    setDraft(JSON.parse(JSON.stringify(settings.data.settings)) as AppSettings);
  }, [settings.data]);

  const metadata: SettingsMetadata | null = settings.data?.metadata ?? null;
  const dirty = useMemo(
    () => Boolean(draft && settings.data && JSON.stringify(draft) !== JSON.stringify(settings.data.settings)),
    [draft, settings.data],
  );

  const weightTotal = useMemo(
    () => (draft ? Object.values(draft.risk_weights).reduce((total, value) => total + Number(value), 0) : 0),
    [draft],
  );

  const patch = <K extends keyof AppSettings>(key: K, value: Partial<AppSettings[K]>) => {
    setDraft((current) =>
      current ? ({ ...current, [key]: { ...current[key], ...value } } as AppSettings) : current,
    );
  };

  const revert = () => {
    if (settings.data) setDraft(JSON.parse(JSON.stringify(settings.data.settings)) as AppSettings);
  };

  const save = async () => {
    if (!draft || !canManage) return;
    if (draft.risk_thresholds.medium >= draft.risk_thresholds.high || draft.risk_thresholds.high >= draft.risk_thresholds.critical) {
      pushToast({
        title: "Check the thresholds",
        message: "Risk thresholds must increase: medium < high < critical.",
        tone: "warning",
      });
      setTab("risk");
      return;
    }
    setSaving(true);
    try {
      const response = await api.settings.update(draft);
      setDraft(JSON.parse(JSON.stringify(response.settings)) as AppSettings);
      pushToast({ title: "Settings saved", message: response.message, tone: "success" });
      settings.reload();
    } catch (error) {
      pushToast({
        title: "Could not save settings",
        message: error instanceof Error ? error.message : "Request failed",
        tone: "danger",
      });
    } finally {
      setSaving(false);
    }
  };

  const runRetention = async () => {
    setBusyAction("retention");
    try {
      const result = await api.settings.runRetention();
      pushToast({ title: "Retention complete", message: result.message, tone: "success" });
    } catch (error) {
      pushToast({ title: "Retention failed", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setBusyAction("");
    }
  };

  const restartPipeline = async () => {
    setBusyAction("pipeline");
    try {
      const result = await api.system.restartPipeline();
      pushToast({ title: "Pipeline restarted", message: result.message, tone: "info" });
    } catch (error) {
      pushToast({ title: "Restart failed", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setBusyAction("");
    }
  };

  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      pushToast({ title: "Passwords do not match", message: "Re-type the new password.", tone: "warning" });
      return;
    }
    setPasswordBusy(true);
    try {
      await api.auth.changePassword(oldPassword, newPassword);
      setOldPassword("");
      setNewPassword("");
      setConfirmPassword("");
      pushToast({ title: "Password changed", message: "Use the new password on your next sign-in.", tone: "success" });
    } catch (error) {
      pushToast({ title: "Could not change password", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setPasswordBusy(false);
    }
  };

  const saveUser = async (values: UserFormValues) => {
    setUserBusy(true);
    try {
      if (userDialog.user) {
        const payload: Record<string, unknown> = {
          full_name: values.full_name,
          email: values.email,
          role: values.role,
          is_active: values.is_active,
        };
        if (values.password) payload.password = values.password;
        await api.users.update(userDialog.user.id, payload);
        pushToast({ title: "User updated", message: values.username || userDialog.user.username, tone: "success" });
        if (user?.id === userDialog.user.id) await refresh();
      } else {
        await api.users.create(values);
        pushToast({ title: "User created", message: `${values.username} · ${values.role}`, tone: "success" });
      }
      setUserDialog({ open: false, user: null });
      users.reload();
      settings.reload();
    } catch (error) {
      pushToast({ title: "Could not save user", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setUserBusy(false);
    }
  };

  const deactivateUser = async () => {
    if (!confirmUser) return;
    setUserBusy(true);
    try {
      await api.users.remove(confirmUser.id);
      pushToast({ title: "Account disabled", message: `${confirmUser.username} can no longer sign in.`, tone: "success" });
      setConfirmUser(null);
      users.reload();
    } catch (error) {
      pushToast({ title: "Could not disable user", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setUserBusy(false);
    }
  };

  const tabs = TABS.filter((item) => !item.permission || can(item.permission));
  const info: SystemInfo | null = systemInfo.data;

  return (
    <div className="page page--settings">
      <div className="page-toolbar">
        <div className="page-toolbar__left">
          <span className={cx("live-chip", dirty && "live-chip--danger")}>
            <span className="live-chip__dot" /> CONFIGURATION {dirty ? "MODIFIED" : "IN SYNC"}
          </span>
          <span className="muted">
            {metadata ? `${metadata.roles.length} roles · ${metadata.permissions.length} permissions · v${String(metadata.environment.app_version ?? "1.0")}` : "Loading configuration…"}
          </span>
        </div>
        <div className="page-toolbar__actions">
          {!canManage && <TonePill tone="muted"><IconLock size={12} /> READ-ONLY</TonePill>}
          <button type="button" className="btn btn--ghost btn--sm" onClick={revert} disabled={!dirty || saving}>
            <IconRefresh size={14} /> Discard
          </button>
          <button type="button" className="btn btn--primary btn--sm" onClick={() => void save()} disabled={!dirty || saving || !canManage}>
            {saving ? <span className="spinner spinner--sm" /> : <IconCheck size={14} />} Save changes
          </button>
        </div>
      </div>

      <div className="settings-shell">
        <nav className="settings-nav">
          {tabs.map((item) => (
            <button
              key={item.key}
              type="button"
              className={cx("settings-nav__item", tab === item.key && "settings-nav__item--active")}
              onClick={() => setTab(item.key)}
            >
              <item.icon size={16} />
              <span>{item.label}</span>
            </button>
          ))}
          <div className="settings-nav__foot">
            <span className="mono">ENV {String(metadata?.environment.environment ?? "local")}</span>
            <span className="mono">DB SQLITE/PG</span>
          </div>
        </nav>

        <div className="settings-body">
          {settings.loading && !draft ? (
            <LoadingState label="Loading configuration…" />
          ) : settings.error ? (
            <ErrorState message={settings.error} retry={settings.reload} />
          ) : !draft ? (
            <EmptyState title="Configuration unavailable" message="The settings service did not return a configuration document." />
          ) : (
            <>
              {tab === "general" && (
                <div className="settings-grid">
                  <Panel title="Site identity" subtitle="Shown in reports and the control-room header">
                    <div className="form-stack">
                      <div className="form-grid">
                        <label className="field">
                          <span>Company / organisation</span>
                          <input
                            value={draft.company.name}
                            maxLength={120}
                            onChange={(event) => patch("company", { name: event.target.value })}
                            disabled={!canManage}
                          />
                        </label>
                        <label className="field">
                          <span>Site name</span>
                          <input
                            value={draft.company.site}
                            maxLength={160}
                            onChange={(event) => patch("company", { site: event.target.value })}
                            disabled={!canManage}
                          />
                        </label>
                      </div>
                      <div className="form-grid">
                        <label className="field">
                          <span>Timezone</span>
                          <input
                            value={draft.company.timezone}
                            maxLength={60}
                            onChange={(event) => patch("company", { timezone: event.target.value })}
                            disabled={!canManage}
                            placeholder="local or Africa/Cairo"
                          />
                        </label>
                        <label className="field">
                          <span>Environment</span>
                          <input value={String(metadata?.environment.environment ?? "—")} disabled />
                        </label>
                      </div>
                      <label className="field">
                        <span>Operator notice</span>
                        <textarea
                          rows={3}
                          value={draft.company.notice}
                          maxLength={500}
                          onChange={(event) => patch("company", { notice: event.target.value })}
                          disabled={!canManage}
                          placeholder="Shown to operators, e.g. privacy and escalation policy…"
                        />
                      </label>
                    </div>
                  </Panel>

                  <Panel title="Runtime environment" subtitle="Server-provided values, read-only">
                    {info ? (
                      <div className="fact-grid fact-grid--single">
                        <div><dt>Application</dt><dd>{info.app_name} v{info.version}</dd></div>
                        <div><dt>Python</dt><dd className="mono">{info.python}</dd></div>
                        <div><dt>Platform</dt><dd className="mono">{info.platform}</dd></div>
                        <div><dt>Detector</dt><dd>{info.detector_mode} · demo {info.demo_mode ? "on" : "off"}</dd></div>
                        <div><dt>Pipeline</dt><dd>{info.pipeline_enabled ? "enabled" : "disabled"} · supervisor {info.supervisor_running ? "running" : "stopped"}</dd></div>
                        <div><dt>Face engine</dt><dd>{info.face_engine.backend ?? "not available"} · {info.face_engine.enabled ? "enabled" : "disabled"}</dd></div>
                        <div><dt>Storage</dt><dd>{info.storage.storage_gb} GB used by media · {info.storage.free_gb} GB free</dd></div>
                        <div><dt>Server time</dt><dd>{formatDateTime(info.server_time, true)}</dd></div>
                      </div>
                    ) : (
                      <LoadingState label="Reading server info…" />
                    )}
                  </Panel>

                  <Panel title="Your session" subtitle="Account and security">
                    <div className="session-card">
                      <span className="avatar">{initials(user?.full_name || user?.username)}</span>
                      <div>
                        <strong>{user?.full_name || user?.username}</strong>
                        <small>{user?.role?.label} · @{user?.username}</small>
                        <small>{user?.email || "No email recorded"}</small>
                      </div>
                      <TonePill tone={user?.is_active ? "green" : "muted"}>{user?.is_active ? "ACTIVE" : "DISABLED"}</TonePill>
                    </div>
                    <div className="fact-grid fact-grid--single compact-facts">
                      <div><dt>Last login</dt><dd>{user?.last_login_at ? formatDateTime(user.last_login_at, true) : "—"}</dd></div>
                      <div><dt>Created</dt><dd>{formatDate(user?.created_at)}</dd></div>
                      <div><dt>Permissions</dt><dd>{user?.role?.permissions.length ?? 0} granted</dd></div>
                    </div>
                  </Panel>

                  <Panel title="Change your password" subtitle="PBKDF2-HMAC-SHA256 · minimum 6 characters">
                    <form className="form-stack" onSubmit={changePassword}>
                      <label className="field">
                        <span>Current password</span>
                        <input type="password" value={oldPassword} required onChange={(event) => setOldPassword(event.target.value)} autoComplete="current-password" />
                      </label>
                      <div className="form-grid">
                        <label className="field">
                          <span>New password</span>
                          <input type="password" value={newPassword} required minLength={6} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" />
                        </label>
                        <label className="field">
                          <span>Confirm new password</span>
                          <input type="password" value={confirmPassword} required minLength={6} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" />
                        </label>
                      </div>
                      <div className="btn-row">
                        <button type="submit" className="btn btn--primary btn--sm" disabled={passwordBusy || !oldPassword || !newPassword}>
                          {passwordBusy ? <span className="spinner spinner--sm" /> : <IconLock size={14} />} Update password
                        </button>
                        <span className="muted">Signing in again is not required.</span>
                      </div>
                    </form>
                  </Panel>

                  <Panel title="System actions" subtitle="Maintenance tasks" accent="amber">
                    <div className="action-stack">
                      <div className="action-row">
                        <span><IconRefresh size={16} /><strong>Restart AI pipeline</strong><small>Stops and restarts every camera worker. Live feeds reconnect automatically.</small></span>
                        <button type="button" className="btn btn--ghost btn--sm" onClick={() => void restartPipeline()} disabled={!canManage || busyAction === "pipeline"}>
                          {busyAction === "pipeline" ? <span className="spinner spinner--sm" /> : <IconRefresh size={14} />} Restart
                        </button>
                      </div>
                      <div className="action-row">
                        <span><IconDatabase size={16} /><strong>Run retention now</strong><small>Deletes recordings older than {draft.recording.retention_days} days and frees disk space.</small></span>
                        <button type="button" className="btn btn--ghost btn--sm" onClick={() => void runRetention()} disabled={!canManage || busyAction === "retention"}>
                          {busyAction === "retention" ? <span className="spinner spinner--sm" /> : <IconTrash size={14} />} Clean up
                        </button>
                      </div>
                    </div>
                    <p className="safety-note">
                      <IconWarning size={15} />
                      These actions are audited. Restarting the pipeline briefly interrupts live AI detections.
                    </p>
                  </Panel>
                </div>
              )}

              {tab === "risk" && (
                <div className="settings-grid">
                  <Panel
                    title="Risk weight model"
                    subtitle="Seven factors combine into the 0–100 score"
                    accent={weightTotal === 100 ? "cyan" : "red"}
                    actions={<TonePill tone={weightTotal === 100 ? "green" : "amber"}>TOTAL {weightTotal} / 100</TonePill>}
                  >
                    <div className="weight-list">
                      {(metadata?.risk_factors ?? []).map((factor) => (
                        <div className="weight-row" key={factor.key}>
                          <div className="weight-row__label">
                            <strong>{factor.label}</strong>
                            <small>{factor.key} · default {factor.default}</small>
                          </div>
                          <input
                            type="range"
                            min={0}
                            max={45}
                            value={Number(draft.risk_weights[factor.key] ?? 0)}
                            onChange={(event) => patch("risk_weights", { [factor.key]: Number(event.target.value) })}
                            disabled={!canManage}
                          />
                          <input
                            type="number"
                            min={0}
                            max={100}
                            value={Number(draft.risk_weights[factor.key] ?? 0)}
                            onChange={(event) => patch("risk_weights", { [factor.key]: Number(event.target.value) })}
                            className="weight-row__number"
                            disabled={!canManage}
                          />
                        </div>
                      ))}
                    </div>
                    <p className="safety-note">
                      <IconCpu size={15} />
                      The total should equal 100 for a calibrated score. Any value is normalised by the server before scoring.
                    </p>
                  </Panel>

                  <Panel title="Risk thresholds" subtitle="Level boundaries applied to new incidents">
                    <div className="form-grid form-grid--three">
                      {(["medium", "high", "critical"] as const).map((level) => (
                        <label className="field" key={level}>
                          <span>{humanize(level)} · minimum score</span>
                          <input
                            type="number"
                            min={1}
                            max={100}
                            value={Number(draft.risk_thresholds[level] ?? 0)}
                            onChange={(event) => patch("risk_thresholds", { [level]: Number(event.target.value) })}
                            disabled={!canManage}
                          />
                        </label>
                      ))}
                    </div>
                    <div className="threshold-preview">
                      {[
                        { level: "normal", max: Number(draft.risk_thresholds.medium) - 1, tone: "green" as const },
                        { level: "medium", max: Number(draft.risk_thresholds.high) - 1, tone: "cyan" as const },
                        { level: "high", max: Number(draft.risk_thresholds.critical) - 1, tone: "amber" as const },
                        { level: "critical", max: 100, tone: "red" as const },
                      ].map((row) => (
                        <div key={row.level} className={cx("threshold-preview__row", `threshold-preview__row--${row.level}`)}>
                          <strong>{humanize(row.level)}</strong>
                          <span className="mono">
                            {row.level === "normal" ? "0" : `≥ ${Number(draft.risk_thresholds[row.level as "medium" | "high" | "critical"] ?? 0)}`}
                            {" → "}
                            {row.level === "critical" ? "100" : `≤ ${row.max}`}
                          </span>
                          <TonePill tone={row.tone}>{row.level === "critical" ? "siren + admin" : row.level === "high" ? "voice warning" : row.level === "medium" ? "record + warn" : "log only"}</TonePill>
                        </div>
                      ))}
                    </div>
                    <p className="safety-note">
                      <IconWarning size={15} />
                      Thresholds must increase: medium &lt; high &lt; critical. The server rejects invalid combinations.
                    </p>
                  </Panel>

                  <Panel title="Verification rules" subtitle="What counts as a real incident">
                    <div className="form-stack">
                      <div className="form-grid form-grid--three">
                        <label className="field">
                          <span>Minimum frames</span>
                          <input
                            type="number"
                            min={1}
                            max={120}
                            value={Number(draft.verification.min_frames ?? 6)}
                            onChange={(event) => patch("verification", { min_frames: Number(event.target.value) })}
                            disabled={!canManage}
                          />
                        </label>
                        <label className="field">
                          <span>Minimum dwell (s)</span>
                          <input
                            type="number"
                            min={0}
                            max={120}
                            step={0.5}
                            value={Number(draft.verification.min_dwell_seconds ?? 2)}
                            onChange={(event) => patch("verification", { min_dwell_seconds: Number(event.target.value) })}
                            disabled={!canManage}
                          />
                        </label>
                        <label className="field">
                          <span>Cooldown (s)</span>
                          <input
                            type="number"
                            min={0}
                            max={3600}
                            value={Number(draft.verification.cooldown_seconds ?? 90)}
                            onChange={(event) => patch("verification", { cooldown_seconds: Number(event.target.value) })}
                            disabled={!canManage}
                          />
                        </label>
                      </div>
                      <label className="field">
                        <span>Incident grouping window (s)</span>
                        <input
                          type="number"
                          min={0}
                          max={3600}
                          value={Number(draft.verification.group_window_seconds ?? 120)}
                          onChange={(event) => patch("verification", { group_window_seconds: Number(event.target.value) })}
                          disabled={!canManage}
                        />
                        <small className="field__hint">
                          Repeated detections of the same target inside this window join one incident instead of spamming the queue.
                        </small>
                      </label>
                      <Toggle
                        checked={Boolean(draft.verification.escalation_only)}
                        onChange={(value) => patch("verification", { escalation_only: value })}
                        label="Escalation-only alarms"
                        description="Only raise a new alarm when the risk level escalates; otherwise update the open incident quietly."
                        disabled={!canManage}
                      />
                    </div>
                  </Panel>

                  <Panel title="How the score is explained" subtitle="Auditability requirement">
                    <ul className="plain-list">
                      <li><IconCheck size={14} /> Each factor records its weight, normalized value and contribution.</li>
                      <li><IconCheck size={14} /> The incident stores the full breakdown and a human-readable explanation.</li>
                      <li><IconCheck size={14} /> Changing weights never rewrites historical incident scores.</li>
                      <li><IconCheck size={14} /> The AI Threat Screen shows the arithmetic next to the evidence.</li>
                    </ul>
                    <div className="formula-card">
                      <span className="mono">score = Σ (normalized_factor × weight)</span>
                      <small>Clamped to 0–100, then mapped through the thresholds on the left.</small>
                    </div>
                  </Panel>
                </div>
              )}

              {tab === "alarm" && (
                <div className="settings-grid">
                  <Panel title="Voice warning policy" subtitle="English + Arabic delivery">
                    <div className="form-stack">
                      <Toggle
                        checked={draft.voice.enabled}
                        onChange={(value) => patch("voice", { enabled: value })}
                        label="Bilingual voice warnings"
                        description="Speak warnings in the control room when a verified threat is raised."
                        disabled={!canManage}
                      />
                      <label className="field">
                        <span>Repeat interval · {draft.voice.repeat_seconds}s</span>
                        <input
                          type="range"
                          min={5}
                          max={120}
                          step={5}
                          value={Number(draft.voice.repeat_seconds)}
                          onChange={(event) => patch("voice", { repeat_seconds: Number(event.target.value) })}
                          disabled={!canManage}
                        />
                        <small className="field__hint">Repeating stops immediately when an operator acknowledges.</small>
                      </label>
                      <div className="field">
                        <span>Languages</span>
                        <div className="check-row">
                          {(metadata?.languages ?? []).map((language) => (
                            <label className="check-field check-field--compact" key={language.code}>
                              <input
                                type="checkbox"
                                checked={draft.voice.languages.includes(language.code)}
                                onChange={(event) => {
                                  const next = event.target.checked
                                    ? [...draft.voice.languages, language.code]
                                    : draft.voice.languages.filter((code) => code !== language.code);
                                  patch("voice", { languages: next.length ? next : ["en"] });
                                }}
                                disabled={!canManage}
                              />
                              <span>{language.label} · {language.voice}</span>
                            </label>
                          ))}
                        </div>
                      </div>
                      <div className="formula-card">
                        <span className="mono">EN / AR TEMPLATES</span>
                        <small>
                          {metadata?.voice_template_count ?? "—"} threat-specific scripts. Camera number and name are filled in at
                          runtime. Template wording is stored in <code>backend/constants.py</code>.
                        </small>
                      </div>
                    </div>
                  </Panel>

                  <Panel title="Siren & escalation" subtitle="Critical-level emergency chain" accent="red">
                    <div className="form-stack">
                      <Toggle
                        checked={draft.alarm.siren_enabled}
                        onChange={(value) => patch("alarm", { siren_enabled: value })}
                        label="Emergency siren"
                        description="Sound the control-room siren for critical incidents."
                        disabled={!canManage}
                      />
                      <Toggle
                        checked={draft.alarm.notify_admin}
                        onChange={(value) => patch("alarm", { notify_admin: value })}
                        label="Notify administrators"
                        description="Create an administrator notification alert for every critical incident."
                        disabled={!canManage}
                      />
                      <label className="field">
                        <span>Emergency webhook URL</span>
                        <input
                          value={draft.alarm.webhook_url}
                          maxLength={500}
                          onChange={(event) => patch("alarm", { webhook_url: event.target.value })}
                          disabled={!canManage}
                          placeholder="https://hooks.example.com/sentinel"
                        />
                        <small className="field__hint">
                          Optional. Receives the incident payload when a critical alarm is raised. Keep the endpoint inside your
                          trusted network.
                        </small>
                      </label>
                    </div>
                  </Panel>

                  <Panel title="End-to-end alarm chain" subtitle="Inspect and test the live behaviour">
                    <ol className="chain chain--compact">
                      {[
                        "Verify the target across frames",
                        "Score the incident with the live weights",
                        "Queue EN + AR voice warnings",
                        "Capture snapshot and clip",
                        "Wait for operator acknowledgment",
                        "Escalate critical alarms to the administrator",
                      ].map((step, index) => (
                        <li className="chain__step" key={step}>
                          <span className="chain__index">{String(index + 1).padStart(2, "0")}</span>
                          <div className="chain__body"><div className="chain__head"><strong>{step}</strong></div></div>
                        </li>
                      ))}
                    </ol>
                    <p className="safety-note">
                      <IconAlerts size={15} />
                      Use Automations to simulate a risk score and preview the exact actions that would fire.
                    </p>
                  </Panel>

                  <Panel title="Alert history shortcuts" subtitle="Jump to operational views">
                    <div className="shortcut-grid">
                      <Link to="/alerts" className="shortcut"><IconAlerts size={18} /><strong>Alert center</strong><small>Pending warnings, playback, acknowledgment</small></Link>
                      <Link to="/automations" className="shortcut"><IconActivity size={18} /><strong>Automations</strong><small>Simulator, response matrix, templates</small></Link>
                      <Link to="/threat" className="shortcut"><IconWarning size={18} /><strong>Threat screen</strong><small>Live threat queue and DANGER overlay</small></Link>
                    </div>
                  </Panel>
                </div>
              )}

              {tab === "ai" && (
                <div className="settings-grid">
                  <Panel title="AI detector" subtitle="Detection and face recognition">
                    <div className="form-stack">
                      <div className="form-grid">
                        <label className="field">
                          <span>Detector mode</span>
                          <select className="select" value={draft.ai.detector_mode} onChange={(event) => patch("ai", { detector_mode: event.target.value })} disabled={!canManage}>
                            <option value="auto">Auto · YOLO when available</option>
                            <option value="yolo">YOLO only</option>
                            <option value="demo">Demo detector</option>
                          </select>
                        </label>
                        <label className="field">
                          <span>Target FPS · {draft.ai.target_fps}</span>
                          <input
                            type="range"
                            min={1}
                            max={30}
                            value={Number(draft.ai.target_fps)}
                            onChange={(event) => patch("ai", { target_fps: Number(event.target.value) })}
                            disabled={!canManage}
                          />
                        </label>
                      </div>
                      <Toggle
                        checked={draft.ai.face_recognition_enabled}
                        onChange={(value) => patch("ai", { face_recognition_enabled: value })}
                        label="Face recognition"
                        description="Match unknown faces against the consented registry. Requires the optional InsightFace dependency."
                        disabled={!canManage}
                      />
                      <Toggle
                        checked={draft.ai.demo_mode}
                        onChange={(value) => patch("ai", { demo_mode: value })}
                        label="Synthetic demo feeds"
                        description="Render camera scenes in software so the system runs without RTSP hardware."
                        disabled={!canManage}
                      />
                    </div>
                  </Panel>

                  <Panel title="Evidence recording" subtitle="Clips, snapshots and retention">
                    <div className="form-stack">
                      <Toggle
                        checked={draft.recording.enabled}
                        onChange={(value) => patch("recording", { enabled: value })}
                        label="Recording enabled"
                        description="Save event snapshots and short MP4 clips for verified incidents."
                        disabled={!canManage}
                      />
                      <div className="form-grid form-grid--three">
                        <label className="field">
                          <span>Pre-event (s)</span>
                          <input
                            type="number"
                            min={0}
                            max={60}
                            value={Number(draft.recording.pre_event_seconds)}
                            onChange={(event) => patch("recording", { pre_event_seconds: Number(event.target.value) })}
                            disabled={!canManage}
                          />
                        </label>
                        <label className="field">
                          <span>Post-event (s)</span>
                          <input
                            type="number"
                            min={0}
                            max={60}
                            value={Number(draft.recording.post_event_seconds)}
                            onChange={(event) => patch("recording", { post_event_seconds: Number(event.target.value) })}
                            disabled={!canManage}
                          />
                        </label>
                        <label className="field">
                          <span>Retention (days)</span>
                          <input
                            type="number"
                            min={1}
                            max={365}
                            value={Number(draft.recording.retention_days)}
                            onChange={(event) => patch("recording", { retention_days: Number(event.target.value) })}
                            disabled={!canManage}
                          />
                        </label>
                      </div>
                      <small className="field__hint">
                        Retention runs on the maintenance schedule and can be triggered from General → System actions.
                      </small>
                    </div>
                  </Panel>

                  <Panel title="Storage budget" subtitle="Disk usage and planning">
                    {info ? (
                      <div className="storage-panel">
                        <Gauge value={info.storage.percent} label="Disk utilisation" tone={info.storage.percent > 90 ? "red" : info.storage.percent > 75 ? "amber" : "cyan"} />
                        <div className="storage-stats">
                          <div><span>Media volume</span><strong>{info.storage.storage_gb} GB</strong></div>
                          <div><span>Free space</span><strong>{info.storage.free_gb} GB</strong></div>
                          <div><span>2 Mbps / camera / day</span><strong>{info.storage_estimate.per_camera_gb_per_day_2mbps} GB</strong></div>
                          <div><span>4 Mbps / camera / day</span><strong>{info.storage_estimate.per_camera_gb_per_day_4mbps} GB</strong></div>
                        </div>
                        <p className="safety-note">
                          <IconDatabase size={15} />
                          Continuous RTSP recording at 4 Mbps needs roughly {info.storage_estimate.per_camera_gb_per_day_4mbps} GB per
                          camera per day. This build records event clips rather than 24/7 footage.
                        </p>
                      </div>
                    ) : (
                      <LoadingState label="Reading storage…" />
                    )}
                  </Panel>

                  <Panel title="Runtime flags" subtitle="Effective server configuration">
                    <div className="fact-grid fact-grid--single compact-facts">
                      <div><dt>Pipeline enabled</dt><dd>{String(metadata?.environment.pipeline_enabled ?? "—")}</dd></div>
                      <div><dt>Demo mode</dt><dd>{String(metadata?.environment.demo_mode ?? "—")}</dd></div>
                      <div><dt>Face recognition</dt><dd>{String(metadata?.environment.face_recognition_enabled ?? "—")}</dd></div>
                      <div><dt>Recording</dt><dd>{String(metadata?.environment.recording_enabled ?? "—")}</dd></div>
                      <div><dt>Server time</dt><dd>{info ? formatDateTime(info.server_time, true) : "—"}</dd></div>
                    </div>
                  </Panel>
                </div>
              )}

              {tab === "users" && (
                <div className="settings-grid settings-grid--wide">
                  <Panel
                    title="Control-center users"
                    subtitle="Role-based access, soft deactivation and password resets"
                    actions={
                      <button type="button" className="btn btn--primary btn--sm" onClick={() => setUserDialog({ open: true, user: null })}>
                        <IconPlus size={14} /> New user
                      </button>
                    }
                    bodyClassName="panel__body--flush"
                    className="span-2"
                  >
                    {users.loading && !users.data ? (
                      <LoadingState label="Loading users…" />
                    ) : users.error ? (
                      <ErrorState message={users.error} retry={users.reload} />
                    ) : users.data?.items.length ? (
                      <div className="data-table data-table--compact user-table">
                        <div className="data-table__head user-row">
                          <span>User</span>
                          <span>Role</span>
                          <span>Status</span>
                          <span>Last login</span>
                          <span>Created</span>
                          <span />
                        </div>
                        {users.data.items.map((item) => (
                          <div className="data-table__row user-row" key={item.id}>
                            <span className="cell-stack user-cell">
                              <span className="avatar avatar--xs">{initials(item.full_name || item.username)}</span>
                              <span>
                                <strong>{item.full_name || item.username}{item.id === user?.id ? " (you)" : ""}</strong>
                                <small>@{item.username} · {item.email || "no email"}</small>
                              </span>
                            </span>
                            <span><TonePill tone={item.role.name === "admin" ? "red" : item.role.name === "operator" ? "cyan" : "muted"}>{item.role.label}</TonePill></span>
                            <span><TonePill tone={item.is_active ? "green" : "muted"}>{item.is_active ? "ACTIVE" : "DISABLED"}</TonePill></span>
                            <span className="cell-time">{item.last_login_at ? formatDateTime(item.last_login_at, true) : "never"}</span>
                            <span className="cell-time">{formatDate(item.created_at)}</span>
                            <span className="row-actions">
                              <button type="button" className="icon-btn" title="Edit user" onClick={() => setUserDialog({ open: true, user: item })}>
                                <IconEdit size={15} />
                              </button>
                              <button
                                type="button"
                                className="icon-btn icon-btn--danger"
                                title="Disable user"
                                disabled={!item.is_active || item.id === user?.id}
                                onClick={() => setConfirmUser(item)}
                              >
                                <IconTrash size={15} />
                              </button>
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <EmptyState icon={<IconUser size={28} />} title="No users" message="Create the first control-center account." />
                    )}
                  </Panel>

                  <Panel title="Role matrix" subtitle="Server-enforced permission sets" bodyClassName="panel__body--flush" className="span-2">
                    {matrix.loading && !matrix.data ? (
                      <LoadingState label="Loading roles…" />
                    ) : matrix.data?.roles.length ? (
                      <div className="matrix-table">
                        <div className="matrix-table__head">
                          <span>Permission</span>
                          {matrix.data.roles.map((role) => <span key={role.name}>{role.label}</span>)}
                        </div>
                        {matrix.data.permissions.map((permission) => (
                          <div className="matrix-table__row" key={permission}>
                            <span>
                              <strong>{humanize(permission)}</strong>
                              <small className="mono">{permission}</small>
                            </span>
                            {matrix.data?.roles.map((role) => (
                              <span key={role.name} className={cx("matrix-check", role.permissions.includes(permission) && "matrix-check--on")}>
                                {role.permissions.includes(permission) ? <IconCheck size={14} /> : <IconClose size={13} />}
                              </span>
                            ))}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <EmptyState title="Permission matrix unavailable" />
                    )}
                  </Panel>

                  <Panel title="Access notes" subtitle="Operational guardrails" className="span-2">
                    <div className="role-cards">
                      {(metadata?.roles ?? []).map((role) => (
                        <div className="role-card" key={role.name}>
                          <div className="role-card__head">
                            <strong>{role.label}</strong>
                            <span className="mono muted">{role.permissions.length} permissions</span>
                          </div>
                          <p>{role.description}</p>
                          <div className="role-card__perms">
                            {role.permissions.slice(0, 6).map((permission) => (
                              <span className="mono" key={permission}>{permission}</span>
                            ))}
                            {role.permissions.length > 6 && <span className="mono">+{role.permissions.length - 6}</span>}
                          </div>
                        </div>
                      ))}
                    </div>
                  </Panel>
                </div>
              )}

              {tab === "audit" && (
                <div className="settings-grid settings-grid--wide">
                  <Panel
                    title="Audit trail"
                    subtitle="Immutable record of operator and system actions"
                    className="span-2"
                    bodyClassName="panel__body--flush"
                    actions={
                      <div className="btn-row">
                        <select
                          className="select select--sm"
                          value={auditAction}
                          onChange={(event) => { setAuditAction(event.target.value); setAuditOffset(0); }}
                        >
                          <option value="">All actions</option>
                          {(auditActions.data?.items ?? []).map((item) => (
                            <option key={item.action} value={item.action}>{item.action} ({item.count})</option>
                          ))}
                        </select>
                        <button type="button" className="btn btn--ghost btn--sm" onClick={auditPage.reload}>
                          <IconRefresh size={14} /> Refresh
                        </button>
                      </div>
                    }
                  >
                    {auditPage.loading && !auditPage.data ? (
                      <LoadingState label="Reading audit log…" />
                    ) : auditPage.error ? (
                      <ErrorState message={auditPage.error} retry={auditPage.reload} />
                    ) : auditPage.data?.items.length ? (
                      <>
                        <div className="data-table data-table--compact audit-table">
                          <div className="data-table__head audit-row">
                            <span>Time</span>
                            <span>User</span>
                            <span>Action</span>
                            <span>Target</span>
                            <span>Detail</span>
                            <span>IP</span>
                          </div>
                          {auditPage.data.items.map((entry) => (
                            <div className="data-table__row audit-row" key={entry.id}>
                              <span className="cell-time">{formatDateTime(entry.created_at, true)}<small>{formatDate(entry.created_at)}</small></span>
                              <span className="cell-stack"><strong>{entry.username || "system"}</strong><small>user #{entry.user_id ?? "—"}</small></span>
                              <span><TonePill tone={entry.action.includes("delete") || entry.action.includes("deactivate") ? "red" : entry.action.includes("create") ? "cyan" : "muted"}>{entry.action}</TonePill></span>
                              <span className="mono">{entry.target || "—"}</span>
                              <span className="audit-detail">{entry.detail || "—"}</span>
                              <span className="mono muted">{entry.ip_address || "—"}</span>
                            </div>
                          ))}
                        </div>
                        <Pagination total={auditPage.data.total} limit={AUDIT_PAGE} offset={auditOffset} onChange={setAuditOffset} />
                      </>
                    ) : (
                      <EmptyState
                        icon={<IconShield size={28} />}
                        title="No audit entries"
                        message="Actions will appear here as operators use the system."
                      />
                    )}
                  </Panel>

                  <Panel title="Audit action totals" subtitle="Grouped by action" className="span-2">
                    {auditActions.data?.items.length ? (
                      <div className="audit-actions">
                        {auditActions.data.items
                          .slice()
                          .sort((left, right) => right.count - left.count)
                          .map((item) => (
                            <button
                              key={item.action}
                              type="button"
                              className={cx("audit-action", auditAction === item.action && "audit-action--active")}
                              onClick={() => { setAuditAction(item.action); setAuditOffset(0); }}
                            >
                              <span className="mono">{item.action}</span>
                              <strong>{item.count}</strong>
                            </button>
                          ))}
                      </div>
                    ) : (
                      <EmptyState title="No audit activity yet" />
                    )}
                    <p className="safety-note">
                      <IconLock size={15} />
                      Audit entries are append-only. Deleting a user or camera never removes its audit history.
                    </p>
                  </Panel>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {userDialog.open && (
        <UserDialog
          key={userDialog.user?.id ?? "new-user"}
          open
          user={userDialog.user}
          roles={(metadata?.roles ?? []).map((role) => ({ name: role.name, label: role.label }))}
          busy={userBusy}
          onClose={() => setUserDialog({ open: false, user: null })}
          onSubmit={saveUser}
        />
      )}

      <Modal
        open={Boolean(confirmUser)}
        onClose={() => setConfirmUser(null)}
        title={confirmUser ? `Disable ${confirmUser.username}?` : "Disable account"}
        subtitle="The account can be re-activated later; history is preserved."
        size="sm"
        footer={
          <div className="modal__footer-row">
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => setConfirmUser(null)} disabled={userBusy}>Cancel</button>
            <button type="button" className="btn btn--danger btn--sm" onClick={() => void deactivateUser()} disabled={userBusy}>
              {userBusy ? <span className="spinner spinner--sm" /> : <IconTrash size={14} />} Disable account
            </button>
          </div>
        }
      >
        <p className="confirm-text">
          {confirmUser?.full_name || confirmUser?.username} will be signed out and blocked from future sign-ins. Existing
          acknowledgments and audit entries stay linked to this account.
        </p>
      </Modal>
    </div>
  );
}

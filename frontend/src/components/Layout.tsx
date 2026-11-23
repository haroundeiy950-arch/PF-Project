/** Application shell: sidebar, command bar, realtime ribbon and toasts. */

import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useRealtime } from "../context/RealtimeContext";
import { formatDateTime, formatTime, initials, LEVEL_LABELS } from "../lib/format";
import { cn } from "../lib/className";
import { cancelSpeech } from "../voice";
import {
  IconActivity,
  IconAlerts,
  IconAutomations,
  IconClose,
  IconDashboard,
  IconDevices,
  IconEvents,
  IconLogout,
  IconMenu,
  IconPeople,
  IconPlayback,
  IconReports,
  IconSettings,
  IconShield,
  IconTarget,
  IconVehicles,
  IconVolume,
  IconVolumeOff,
} from "./Icons";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: IconDashboard },
  { to: "/threat", label: "AI Threat Screen", icon: IconTarget, live: true },
  { to: "/events", label: "Events", icon: IconEvents },
  { to: "/alerts", label: "Alerts", icon: IconAlerts, badge: "pending" },
  { to: "/playback", label: "Playback", icon: IconPlayback },
  { to: "/people", label: "People", icon: IconPeople },
  { to: "/vehicles", label: "Vehicles", icon: IconVehicles },
  { to: "/automations", label: "Automations", icon: IconAutomations },
  { to: "/devices", label: "Devices", icon: IconDevices },
  { to: "/reports", label: "Reports", icon: IconReports },
  { to: "/settings", label: "Settings", icon: IconSettings },
];

const TITLES: Record<string, { title: string; eyebrow: string }> = {
  "/dashboard": { title: "Perimeter Overview", eyebrow: "Live command dashboard" },
  "/threat": { title: "AI Live Threat Screen", eyebrow: "Real-time threat intelligence" },
  "/events": { title: "Detection Events", eyebrow: "AI event ledger" },
  "/alerts": { title: "Alert Center", eyebrow: "Alarm & voice warnings" },
  "/playback": { title: "Evidence Playback", eyebrow: "Recordings & snapshots" },
  "/people": { title: "Authorized People", eyebrow: "Face recognition registry" },
  "/vehicles": { title: "Vehicle Activity", eyebrow: "Target classification" },
  "/automations": { title: "Emergency Automation", eyebrow: "Response chain" },
  "/devices": { title: "Cameras & Zones", eyebrow: "Device management" },
  "/reports": { title: "Security Reports", eyebrow: "Analytics & evidence export" },
  "/settings": { title: "System Settings", eyebrow: "Configuration & access control" },
};

function Clock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <div className="clock">
      <strong>{formatTime(now.toISOString(), true)}</strong>
      <span>{formatDateTime(now.toISOString()).slice(0, 10)} · LOCAL</span>
    </div>
  );
}

export function Layout() {
  const { user, logout } = useAuth();
  const { connected, pendingAlerts, voiceEnabled, toggleVoice, lastIncident, clearLastIncident, toasts, dismissToast, activeCount } =
    useRealtime();
  const location = useLocation();
  const navigate = useNavigate();
  const [navOpen, setNavOpen] = useState(false);
  const meta = TITLES[location.pathname] ?? TITLES["/dashboard"];

  useEffect(() => {
    setNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!lastIncident) return;
    const timer = window.setTimeout(() => clearLastIncident(), 30000);
    return () => window.clearTimeout(timer);
  }, [lastIncident, clearLastIncident]);

  return (
    <div className="app-shell">
      <aside className={cn("sidebar", navOpen && "sidebar--open")}>
        <Link to="/dashboard" className="brand" onClick={() => setNavOpen(false)}>
          <span className="brand__mark">
            <IconShield size={24} />
          </span>
          <span className="brand__text">
            <strong>SENTINEL</strong>
            <small>PERIMETER CONTROL</small>
          </span>
        </Link>

        <div className="sidebar__section-label">COMMAND CENTER</div>
        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => cn("nav__item", isActive && "nav__item--active")}
            >
              <item.icon size={17} />
              <span>{item.label}</span>
              {item.live && <span className="nav__live">LIVE</span>}
              {item.badge === "pending" && pendingAlerts.length > 0 && (
                <span className="nav__badge">{pendingAlerts.length}</span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar__status">
          <div className="sidebar__status-head">
            <span>SYSTEM STATUS</span>
            <span className={cn("status-dot", connected ? "status-dot--online" : "status-dot--offline")} />
          </div>
          <div className="sidebar__status-row">
            <span>Mode</span>
            <strong>{activeCount > 0 ? "Alert" : "Auto"}</strong>
          </div>
          <div className="sidebar__status-row">
            <span>Realtime</span>
            <strong>{connected ? "Connected" : "Reconnecting"}</strong>
          </div>
          <div className="sidebar__status-row">
            <span>Active threats</span>
            <strong className={activeCount > 0 ? "text-danger" : ""}>{activeCount}</strong>
          </div>
          <div className="sidebar__battery">
            <span style={{ width: `${connected ? 92 : 24}%` }} />
          </div>
        </div>

        <div className="sidebar__user">
          <span className="avatar">{initials(user?.full_name || user?.username)}</span>
          <div>
            <strong>{user?.full_name || user?.username}</strong>
            <small>{user?.role?.label ?? "Observer"}</small>
          </div>
          <button
            type="button"
            className="icon-btn icon-btn--danger"
            title="Sign out"
            onClick={() => {
              cancelSpeech();
              void logout().then(() => navigate("/login"));
            }}
          >
            <IconLogout size={17} />
          </button>
        </div>
      </aside>

      {navOpen && <button type="button" className="sidebar-scrim" aria-label="Close menu" onClick={() => setNavOpen(false)} />}

      <div className="main">
        <header className="topbar">
          <button type="button" className="icon-btn topbar__menu" onClick={() => setNavOpen(true)} aria-label="Open menu">
            <IconMenu size={20} />
          </button>
          <div className="topbar__title">
            <span className="eyebrow">{meta.eyebrow}</span>
            <h1>{meta.title}</h1>
          </div>

          <div className="topbar__right">
            <span className={cn("conn-pill", connected ? "conn-pill--on" : "conn-pill--off")}>
              <span className="status-dot" />
              {connected ? "REALTIME" : "OFFLINE"}
            </span>
            <Clock />
            <button
              type="button"
              className={cn("icon-btn", voiceEnabled && "icon-btn--active")}
              onClick={toggleVoice}
              title={voiceEnabled ? "Mute voice warnings" : "Enable voice warnings"}
            >
              {voiceEnabled ? <IconVolume size={18} /> : <IconVolumeOff size={18} />}
            </button>
            <Link to="/alerts" className="icon-btn alert-bell" title="Pending voice alerts">
              <IconAlerts size={18} />
              {pendingAlerts.length > 0 && <span className="alert-bell__count">{pendingAlerts.length}</span>}
            </Link>
            <div className="topbar__profile">
              <span className="avatar avatar--sm">{initials(user?.full_name || user?.username)}</span>
              <div>
                <strong>{user?.username}</strong>
                <small>{user?.role?.label}</small>
              </div>
            </div>
          </div>
        </header>

        {lastIncident && (
          <div className={cn("live-ribbon", `live-ribbon--${lastIncident.incident.level}`)}>
            <span className="live-ribbon__pulse" />
            <span className="live-ribbon__tag">{LEVEL_LABELS[lastIncident.incident.level]} THREAT</span>
            <strong>{lastIncident.incident.title}</strong>
            <span className="live-ribbon__meta">
              {lastIncident.incident.camera_code} · {lastIncident.incident.zone_name ?? lastIncident.incident.camera_location} · Risk{" "}
              {lastIncident.incident.risk_score}/100 · {formatTime(lastIncident.incident.detected_at, true)}
            </span>
            <button type="button" className="btn btn--danger btn--sm" onClick={() => navigate(`/threat/${lastIncident.incident.id}`)}>
              Open threat screen
            </button>
            <button type="button" className="icon-btn" onClick={clearLastIncident} aria-label="Dismiss threat banner">
              <IconClose size={16} />
            </button>
          </div>
        )}

        <main className="content">
          <Outlet />
        </main>

        <footer className="app-footer">
          <span>
            <IconActivity size={13} /> Sentinel AI v1.0 · {user?.role?.label ?? "Observer"} session
          </span>
          <span>AI-assisted monitoring. Operators remain responsible for final decisions.</span>
          <span className="app-footer__mono">EN / AR · VOICE ARMED</span>
        </footer>
      </div>

      <div className="toast-stack" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={cn("toast", `toast--${toast.tone}`)}>
            <div className="toast__stripe" />
            <div className="toast__body">
              <strong>{toast.title}</strong>
              {toast.message && <p>{toast.message}</p>}
              {toast.incidentId && (
                <button type="button" className="toast__link" onClick={() => navigate(`/threat/${toast.incidentId}`)}>
                  View AI threat screen →
                </button>
              )}
            </div>
            <button type="button" className="icon-btn" onClick={() => dismissToast(toast.id)} aria-label="Dismiss notification">
              <IconClose size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

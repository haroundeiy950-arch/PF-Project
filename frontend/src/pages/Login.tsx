import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api";
import { useAuth } from "../context/AuthContext";
import { IconAlerts, IconCamera, IconCheck, IconLock, IconShield, IconTarget, IconVolume } from "../components/Icons";

const DEMO = [
  { username: "admin", password: "admin123", role: "Administrator" },
  { username: "operator", password: "operator123", role: "Security Operator" },
  { username: "viewer", password: "viewer123", role: "Viewer" },
];

export default function Login() {
  const { login, busy } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [error, setError] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      await login(username, password);
      navigate("/dashboard", { replace: true });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Unable to reach the security server.");
    }
  };

  return (
    <div className="login">
      <div className="login__visual">
        <div className="login__grid" />
        <div className="login__radar">
          <span className="login__radar-sweep" />
          <span className="login__radar-ring login__radar-ring--1" />
          <span className="login__radar-ring login__radar-ring--2" />
          <span className="login__radar-ring login__radar-ring--3" />
          <span className="login__radar-blip login__radar-blip--a" />
          <span className="login__radar-blip login__radar-blip--b" />
        </div>

        <div className="login__brand">
          <span className="brand__mark brand__mark--lg">
            <IconShield size={30} />
          </span>
          <div>
            <span className="eyebrow">AI SMART SECURITY CAMERA SYSTEM</span>
            <h1>SENTINEL AI</h1>
            <p>Perimeter Control Center</p>
          </div>
        </div>

        <div className="login__features">
          <div>
            <IconCamera size={18} />
            <span>
              <strong>Live AI monitoring</strong>
              <small>Object, motion, face and intrusion detection</small>
            </span>
          </div>
          <div>
            <IconTarget size={18} />
            <span>
              <strong>Verified threat engine</strong>
              <small>Transparent risk score from 0 to 100</small>
            </span>
          </div>
          <div>
            <IconVolume size={18} />
            <span>
              <strong>Bilingual voice alarms</strong>
              <small>Instant English and Arabic warnings</small>
            </span>
          </div>
          <div>
            <IconAlerts size={18} />
            <span>
              <strong>Emergency response chain</strong>
              <small>Siren, notification, evidence and audit trail</small>
            </span>
          </div>
        </div>

        <div className="login__foot">
          <span className="status-dot status-dot--online" /> DEMO SYSTEM ONLINE · 4 CAMERAS ARMED
        </div>
      </div>

      <div className="login__panel">
        <div className="login__card">
          <div className="login__card-head">
            <span className="eyebrow">SECURE OPERATOR ACCESS</span>
            <h2>Sign in to command center</h2>
            <p>Authorized security personnel only. All sessions are logged.</p>
          </div>

          <form onSubmit={submit} className="login__form">
            <label className="field">
              <span>Username</span>
              <input
                autoFocus
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="operator"
                required
              />
            </label>

            <label className="field">
              <span>Password</span>
              <div className="field__password">
                <input
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="••••••••"
                  required
                />
                <button type="button" className="field__reveal" onClick={() => setShowPassword((value) => !value)}>
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
            </label>

            {error && (
              <div className="login__error">
                <IconAlerts size={16} />
                {error}
              </div>
            )}

            <button type="submit" className="btn btn--primary btn--block" disabled={busy}>
              {busy ? <span className="spinner spinner--sm" /> : <IconLock size={16} />}
              {busy ? "Verifying credentials…" : "Authenticate"}
            </button>
          </form>

          <div className="login__demo">
            <span className="login__demo-title">DEMO ACCOUNTS</span>
            {DEMO.map((account) => (
              <button
                type="button"
                key={account.username}
                className={username === account.username ? "login__demo-row is-active" : "login__demo-row"}
                onClick={() => {
                  setUsername(account.username);
                  setPassword(account.password);
                  setError("");
                }}
              >
                <span>
                  <strong>{account.username}</strong>
                  <small>{account.role}</small>
                </span>
                <code>{account.password}</code>
                {username === account.username && <IconCheck size={15} />}
              </button>
            ))}
          </div>

          <p className="login__notice">
            This system monitors and records activity. By signing in you acknowledge the CCTV notice and the
            organisation&apos;s privacy policy.
          </p>
        </div>
      </div>
    </div>
  );
}

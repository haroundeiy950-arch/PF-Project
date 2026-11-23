import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, api, websocketUrl } from "../api";
import { useAuth } from "./AuthContext";
import type { Alert, HealthSnapshot, Incident, RealtimeMessage } from "../types";
import { cancelSpeech, playSiren, speak, stopSiren } from "../voice";

export type ToastTone = "info" | "success" | "warning" | "danger";

export interface Toast {
  id: number;
  title: string;
  message?: string;
  tone: ToastTone;
  incidentId?: number;
}

interface RealtimeContextValue {
  connected: boolean;
  statsVersion: number;
  pendingAlerts: Alert[];
  activeCount: number;
  health: HealthSnapshot | null;
  lastIncident: { incident: Incident; receivedAt: number } | null;
  clearLastIncident: () => void;
  refreshPending: () => Promise<void>;
  speakAlert: (alert: Alert, markPlaying?: boolean) => Promise<void>;
  speakIncident: (incident: Incident) => void;
  stopAllAlerts: () => void;
  voiceEnabled: boolean;
  toggleVoice: () => void;
  sirenEnabled: boolean;
  setSirenEnabled: (value: boolean) => void;
  toasts: Toast[];
  pushToast: (toast: Omit<Toast, "id">) => void;
  dismissToast: (id: number) => void;
}

const RealtimeContext = createContext<RealtimeContextValue | null>(null);
const VOICE_PREF = "sentinel.voice";

function messagePayloads(data: unknown): { language: string; text: string }[] {
  if (!Array.isArray(data)) return [];
  return data
    .filter((item): item is Alert => Boolean(item) && typeof item === "object")
    .filter((item) => item.channel === "voice" && item.message)
    .sort((left, right) => (left.language === "en" ? -1 : right.language === "en" ? 1 : 0))
    .map((item) => ({ language: item.language, text: item.message }));
}

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  const [connected, setConnected] = useState(false);
  const [statsVersion, setStatsVersion] = useState(0);
  const [pendingAlerts, setPendingAlerts] = useState<Alert[]>([]);
  const [activeCount, setActiveCount] = useState(0);
  const [health, setHealth] = useState<HealthSnapshot | null>(null);
  const [lastIncident, setLastIncident] = useState<{ incident: Incident; receivedAt: number } | null>(null);
  const [voiceEnabled, setVoiceEnabled] = useState<boolean>(() => localStorage.getItem(VOICE_PREF) !== "off");
  const [sirenEnabled, setSirenEnabled] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const spokenAlerts = useRef<Set<number>>(new Set());
  const toastCounter = useRef(1);
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<number | null>(null);
  const attemptRef = useRef(0);
  const firstConnectRef = useRef(true);
  const voiceRef = useRef(voiceEnabled);
  const sirenRef = useRef(sirenEnabled);

  useEffect(() => {
    voiceRef.current = voiceEnabled;
  }, [voiceEnabled]);
  useEffect(() => {
    sirenRef.current = sirenEnabled;
  }, [sirenEnabled]);

  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const pushToast = useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = toastCounter.current++;
      setToasts((current) => [...current.slice(-4), { ...toast, id }]);
      window.setTimeout(() => dismissToast(id), toast.tone === "danger" ? 10000 : 6000);
    },
    [dismissToast],
  );

  const refreshPending = useCallback(async () => {
    try {
      const response = await api.alerts.pending();
      setPendingAlerts(response.items);
    } catch {
      /* transient network errors are retried by the next poll */
    }
  }, []);

  const speakAlert = useCallback(
    async (alert: Alert, markPlaying = true) => {
      if (!voiceRef.current || !alert.message) return;
      if (alert.language === "ar") {
        speak([{ language: "ar", text: alert.message }]);
      } else if (alert.language === "en") {
        speak([{ language: "en", text: alert.message }]);
      } else {
        speak([{ language: alert.language, text: alert.message }]);
      }
      if (markPlaying && !spokenAlerts.current.has(alert.id)) {
        spokenAlerts.current.add(alert.id);
        try {
          await api.alerts.play(alert.id);
        } catch {
          /* the alert may already be closed */
        }
      }
    },
    [],
  );

  const speakIncident = useCallback((incident: Incident) => {
    if (!voiceRef.current) return;
    const messages =
      incident.alerts && incident.alerts.some((alert) => alert.channel === "voice")
        ? messagePayloads(incident.alerts)
        : [
            {
              language: "en",
              text: `Warning! ${incident.type_label} detected at ${incident.camera_name ?? "camera"}. Risk score ${incident.risk_score} of 100. Immediate attention required.`,
            },
          ];
    if (messages.length) speak(messages);
    if (sirenRef.current && incident.level === "critical") playSiren(8);
  }, []);

  const stopAllAlerts = useCallback(() => {
    cancelSpeech();
    stopSiren();
  }, []);

  const toggleVoice = useCallback(() => {
    setVoiceEnabled((current) => {
      const next = !current;
      localStorage.setItem(VOICE_PREF, next ? "on" : "off");
      if (!next) cancelSpeech();
      return next;
    });
  }, []);

  const handleMessage = useCallback(
    (message: RealtimeMessage) => {
      switch (message.type) {
        case "connected": {
          const data = message.data as {
            active_incidents?: number;
            health?: HealthSnapshot;
          };
          setActiveCount(data.active_incidents ?? 0);
          if (data.health) setHealth(data.health);
          break;
        }
        case "incident.created": {
          const incident = message.data as Incident;
          setLastIncident({ incident, receivedAt: Date.now() });
          setActiveCount((current) => current + 1);
          setStatsVersion((value) => value + 1);
          pushToast({
            title: `${incident.level_label} · ${incident.code}`,
            message: `${incident.title} — risk ${incident.risk_score}/100`,
            tone:
              incident.level === "critical"
                ? "danger"
                : incident.level === "high"
                  ? "warning"
                  : "info",
            incidentId: incident.id,
          });
          if (incident.alerts?.some((alert) => alert.channel === "voice")) {
            const alerts = incident.alerts.filter((alert) => alert.channel === "voice");
            alerts.forEach((alert) => spokenAlerts.current.add(alert.id));
            if (voiceRef.current) speak(messagePayloads(alerts));
            if (sirenRef.current && incident.level === "critical") playSiren(8);
          } else {
            speakIncident(incident);
          }
          refreshPending();
          break;
        }
        case "incident.updated":
        case "incident.acknowledged":
        case "incident.resolved": {
          const incident = message.data as Incident;
          setStatsVersion((value) => value + 1);
          if (message.type === "incident.resolved") {
            setActiveCount((current) => Math.max(0, current - 1));
          }
          if (message.type === "incident.acknowledged") {
            cancelSpeech();
            pushToast({
              title: "Alarm acknowledged",
              message: `${incident.code} · alarm repetition stopped`,
              tone: "success",
            });
          }
          break;
        }
        case "alert.updated":
        case "alert.playing":
        case "incident.deleted": {
          refreshPending();
          setStatsVersion((value) => value + 1);
          break;
        }
        case "health.updated": {
          setHealth(message.data as HealthSnapshot);
          break;
        }
        case "stats.refresh": {
          setStatsVersion((value) => value + 1);
          break;
        }
        default:
          break;
      }
    },
    [pushToast, refreshPending, speakIncident],
  );

  useEffect(() => {
    if (!token) {
      setConnected(false);
      return;
    }

    let disposed = false;

    const connect = () => {
      if (disposed) return;
      let socket: WebSocket;
      try {
        socket = new WebSocket(websocketUrl());
      } catch {
        return;
      }
      socketRef.current = socket;
      socket.onopen = () => {
        attemptRef.current = 0;
        setConnected(true);
        if (firstConnectRef.current) {
          firstConnectRef.current = false;
          refreshPending().then(() => {
            // Recover warnings that were queued while this screen was closed.
            api.alerts
              .pending()
              .then((response) => {
                if (!voiceRef.current) return;
                const newest = response.items.slice(0, 2);
                const messages = newest.flatMap((alert) => ({ language: alert.language, text: alert.message }));
                if (messages.length) speak(messages);
              })
              .catch(() => undefined);
          });
        }
      };
      socket.onmessage = (event) => {
        try {
          handleMessage(JSON.parse(event.data) as RealtimeMessage);
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (disposed) return;
        attemptRef.current += 1;
        const delay = Math.min(15000, 1000 * 2 ** Math.min(4, attemptRef.current));
        reconnectTimer.current = window.setTimeout(connect, delay);
      };
      socket.onerror = () => socket.close();
    };

    connect();
    const ping = window.setInterval(() => {
      const socket = socketRef.current;
      if (socket && socket.readyState === WebSocket.OPEN) socket.send("ping");
    }, 25000);
    const poll = window.setInterval(() => {
      refreshPending();
      api.system
        .health()
        .then(setHealth)
        .catch(() => undefined);
    }, 30000);

    return () => {
      disposed = true;
      if (reconnectTimer.current !== null) window.clearTimeout(reconnectTimer.current);
      window.clearInterval(ping);
      window.clearInterval(poll);
      socketRef.current?.close();
      socketRef.current = null;
      setConnected(false);
    };
  }, [token, handleMessage, refreshPending]);

  useEffect(() => {
    if (!token) return;
    api.settings
      .get()
      .then((response) => setSirenEnabled(Boolean(response.settings.alarm.siren_enabled)))
      .catch(() => undefined);
    api.dashboard
      .get()
      .then((dashboard) => {
        setActiveCount(dashboard.active.total);
        setHealth(dashboard.health);
      })
      .catch((error) => {
        if (error instanceof ApiError) return;
      });
  }, [token]);

  useEffect(() => () => cancelSpeech(), []);

  const value = useMemo<RealtimeContextValue>(
    () => ({
      connected,
      statsVersion,
      pendingAlerts,
      activeCount,
      health,
      lastIncident,
      clearLastIncident: () => setLastIncident(null),
      refreshPending,
      speakAlert,
      speakIncident,
      stopAllAlerts,
      voiceEnabled,
      toggleVoice,
      sirenEnabled,
      setSirenEnabled,
      toasts,
      pushToast,
      dismissToast,
    }),
    [
      connected,
      statsVersion,
      pendingAlerts,
      activeCount,
      health,
      lastIncident,
      refreshPending,
      speakAlert,
      speakIncident,
      stopAllAlerts,
      voiceEnabled,
      toggleVoice,
      sirenEnabled,
      toasts,
      pushToast,
      dismissToast,
    ],
  );

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>;
}

export function useRealtime(): RealtimeContextValue {
  const context = useContext(RealtimeContext);
  if (!context) throw new Error("useRealtime must be used inside RealtimeProvider");
  return context;
}

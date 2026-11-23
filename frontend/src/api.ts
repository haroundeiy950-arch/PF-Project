/** Typed API client. Handles auth, JSON errors, uploads and file downloads. */

import type {
  ActiveIncidents,
  Alert,
  AlertTemplates,
  AppSettings,
  AuditEntry,
  Camera,
  CameraDiscovery,
  CameraMeta,
  Dashboard,
  EventItem,
  EvidenceAudit,
  HealthSnapshot,
  Incident,
  LiveDeviceSelection,
  LoginResponse,
  Paged,
  Person,
  Recording,
  ReportOverview,
  RiskPreview,
  SettingsResponse,
  SystemInfo,
  User,
  Zone,
  ZoneMeta,
} from "./types";

const TOKEN_KEY = "sentinel.token";
const USER_KEY = "sentinel.user";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export const tokenStore = {
  get: (): string | null => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  },
};

export const userStore = {
  get: (): User | null => {
    const raw = localStorage.getItem(USER_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as User;
    } catch {
      return null;
    }
  },
  set: (user: User) => localStorage.setItem(USER_KEY, JSON.stringify(user)),
};

function detailFrom(payload: unknown, fallback: string): string {
  if (!payload) return fallback;
  if (typeof payload === "string") return payload;
  if (typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    const detail = record.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return String(item);
        })
        .join(" · ");
    }
    if (typeof record.message === "string") return record.message;
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!(init.body instanceof FormData) && init.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, { ...init, headers });
  if (response.status === 401 && !path.includes("/auth/login")) {
    window.dispatchEvent(new CustomEvent("sentinel:unauthorized"));
  }
  if (!response.ok) {
    let payload: unknown = null;
    const text = await response.text();
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      payload = text;
    }
    throw new ApiError(response.status, detailFrom(payload, response.statusText || "Request failed"));
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

function jsonBody(value: unknown): RequestInit {
  return { method: "POST", body: JSON.stringify(value) };
}

async function download(path: string, filename: string): Promise<void> {
  const token = tokenStore.get();
  const response = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    throw new ApiError(response.status, "Export failed");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function streamUrl(cameraId: number): string {
  const token = tokenStore.get();
  return `/api/cameras/${cameraId}/stream${token ? `?token=${encodeURIComponent(token)}` : ""}`;
}

export function snapshotUrl(cameraId: number): string {
  const token = tokenStore.get();
  return `/api/cameras/${cameraId}/snapshot${token ? `?token=${encodeURIComponent(token)}` : ""}`;
}

export function websocketUrl(): string {
  const token = tokenStore.get() ?? "";
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/ws?token=${encodeURIComponent(token)}`;
}

export const api = {
  auth: {
    login: (username: string, password: string) =>
      request<LoginResponse>("/api/auth/login", jsonBody({ username, password })),
    me: () => request<User>("/api/auth/me"),
    changePassword: (current_password: string, new_password: string) =>
      request<{ message: string }>(
        "/api/auth/change-password",
        jsonBody({ current_password, new_password }),
      ),
    logout: () => request<{ message: string }>("/api/auth/logout", { method: "POST" }),
  },

  dashboard: {
    get: () => request<Dashboard>("/api/dashboard"),
    timeline: (hours = 24) => request<{ items: unknown[]; hours: number }>(`/api/dashboard/timeline?hours=${hours}`),
    health: () => request<HealthSnapshot>("/api/dashboard/health"),
  },

  cameras: {
    list: () => request<{ items: Camera[]; total: number; supervisor_running: boolean }>("/api/cameras"),
    meta: () => request<CameraMeta>("/api/cameras/meta"),
    discover: () => request<CameraDiscovery>("/api/cameras/discover"),
    selectLiveDevice: (id: number, index: number) =>
      request<LiveDeviceSelection>(
        `/api/cameras/${id}/live-device`,
        jsonBody({ index }),
      ),
    autoLiveDevice: (id: number) =>
      request<LiveDeviceSelection>(`/api/cameras/${id}/auto-device`, { method: "POST" }),
    get: (id: number) => request<Camera>(`/api/cameras/${id}`),
    create: (value: Partial<Camera>) =>
      request<Camera>("/api/cameras", jsonBody(value)),
    update: (id: number, value: Partial<Camera>) =>
      request<Camera>(`/api/cameras/${id}`, { method: "PATCH", body: JSON.stringify(value) }),
    remove: (id: number) => request<{ message: string }>(`/api/cameras/${id}`, { method: "DELETE" }),
    restart: (id: number) =>
      request<{ message: string; status: string }>(`/api/cameras/${id}/restart`, { method: "POST" }),
    capture: (id: number) =>
      request<Recording>(`/api/recordings/snapshot/${id}`, { method: "POST" }),
    detections: (id: number) =>
      request<Record<string, unknown>>(`/api/cameras/${id}/detections`),
  },

  zones: {
    list: (cameraId?: number) =>
      request<{ items: Zone[]; total: number }>(`/api/zones${query({ camera_id: cameraId })}`),
    meta: () => request<ZoneMeta>("/api/zones/meta"),
    create: (value: Partial<Zone>) => request<Zone>("/api/zones", jsonBody(value)),
    update: (id: number, value: Partial<Zone>) =>
      request<Zone>(`/api/zones/${id}`, { method: "PATCH", body: JSON.stringify(value) }),
    remove: (id: number) =>
      request<{ message: string }>(`/api/zones/${id}`, { method: "DELETE" }),
  },

  incidents: {
    active: () => request<ActiveIncidents>("/api/incidents/active"),
    list: (params: Record<string, string | number | undefined> = {}) =>
      request<Paged<Incident>>(`/api/incidents${query(params)}`),
    get: (id: number) => request<Incident>(`/api/incidents/${id}`),
    events: (id: number) => request<{ items: EventItem[]; total: number }>(`/api/incidents/${id}/events`),
    summary: () => request<Record<string, unknown>>("/api/incidents/summary"),
    acknowledge: (id: number, note = "") =>
      request<Incident>(`/api/incidents/${id}/acknowledge`, jsonBody({ note })),
    resolve: (id: number, note = "") =>
      request<Incident>(`/api/incidents/${id}/resolve`, jsonBody({ note })),
    falseAlarm: (id: number, note = "") =>
      request<Incident>(`/api/incidents/${id}/false-alarm`, jsonBody({ note })),
    remove: (id: number) => request<{ message: string }>(`/api/incidents/${id}`, { method: "DELETE" }),
  },

  alerts: {
    pending: () => request<{ items: Alert[]; total: number }>("/api/alerts/pending"),
    list: (params: Record<string, string | number | undefined> = {}) =>
      request<Paged<Alert>>(`/api/alerts${query(params)}`),
    templates: () => request<AlertTemplates>("/api/alerts/templates"),
    play: (id: number) => request<Alert>(`/api/alerts/${id}/play`, { method: "POST" }),
    stop: (id: number) => request<Alert>(`/api/alerts/${id}/stop`, { method: "POST" }),
    acknowledge: (id: number) =>
      request<Alert>(`/api/alerts/${id}/acknowledge`, { method: "POST" }),
    replay: (incidentId: number) =>
      request<{ items: Alert[]; total: number }>(`/api/alerts/incidents/${incidentId}/replay`, {
        method: "POST",
      }),
    resend: (id: number) =>
      request<{ message: string }>(`/api/alerts/${id}/resend`, { method: "POST" }),
  },

  events: {
    list: (params: Record<string, string | number | boolean | undefined> = {}) =>
      request<Paged<EventItem>>(`/api/events${query(params)}`),
    stats: (hours = 24) =>
      request<{
        window_hours: number;
        by_type: { event_type: string; count: number }[];
        by_target: { target_type: string; count: number }[];
        by_camera: { camera_id: number; camera_name: string; count: number }[];
      }>(`/api/events/stats?hours=${hours}`),
    get: (id: number) => request<EventItem>(`/api/events/${id}`),
  },

  recordings: {
    list: (params: Record<string, string | number | undefined> = {}) =>
      request<Paged<Recording>>(`/api/recordings${query(params)}`),
    stats: () =>
      request<{
        total_count: number;
        total_size_bytes: number;
        total_size_gb: number;
        by_kind: { kind: string; count: number; size_bytes: number }[];
        disk: {
          total_gb: number;
          used_gb: number;
          free_gb: number;
          percent: number;
          storage_gb: number;
        };
      }>("/api/recordings/stats"),
    audit: (repair = false) =>
      request<EvidenceAudit>(`/api/recordings/audit?repair=${repair}`, { method: "POST" }),
    remove: (id: number) =>
      request<{ message: string }>(`/api/recordings/${id}`, { method: "DELETE" }),
  },

  persons: {
    list: (q?: string) =>
      request<{ items: Person[]; total: number; consented: number; with_embedding: number }>(
        `/api/persons${query({ q })}`,
      ),
    meta: () =>
      request<{
        face_engine: import("./types").FaceEngineStatus;
        consent_notice: string;
        max_photo_mb: number;
        accepted_formats: string[];
      }>("/api/persons/meta"),
    create: (form: FormData) => request<Person>("/api/persons", { method: "POST", body: form }),
    update: (id: number, value: Partial<Person>) =>
      request<Person>(`/api/persons/${id}`, { method: "PATCH", body: JSON.stringify(value) }),
    photo: (id: number, form: FormData) =>
      request<Person>(`/api/persons/${id}/photo`, { method: "POST", body: form }),
    reenroll: (id: number) =>
      request<{ message: string; has_embedding: boolean }>(`/api/persons/${id}/reenroll`, {
        method: "POST",
      }),
    remove: (id: number) =>
      request<{ message: string }>(`/api/persons/${id}`, { method: "DELETE" }),
  },

  reports: {
    overview: (start?: string, end?: string) =>
      request<ReportOverview>(`/api/reports/overview${query({ start, end })}`),
    incidentsCsv: (start?: string, end?: string) =>
      download(`/api/reports/incidents.csv${query({ start, end })}`, "sentinel-incidents.csv"),
    eventsCsv: (start?: string, end?: string) =>
      download(`/api/reports/events.csv${query({ start, end })}`, "sentinel-events.csv"),
    exportJson: (start?: string, end?: string) =>
      download(`/api/reports/export${query({ start, end })}`, "sentinel-evidence.json"),
  },

  settings: {
    get: () => request<SettingsResponse>("/api/settings"),
    risk: () => request<{
      weights: Record<string, number>;
      thresholds: Record<string, number>;
      verification: Record<string, number | boolean>;
      factors: Record<string, { label: string; description: string; default_weight: number }>;
    }>("/api/settings/risk"),
    preview: (factors: object) =>
      request<RiskPreview>("/api/settings/risk/preview", jsonBody(factors)),
    update: (values: Partial<AppSettings>) =>
      request<{ settings: AppSettings; message: string }>("/api/settings", {
        method: "PUT",
        body: JSON.stringify(values),
      }),
    updateGroup: (key: string, value: Record<string, unknown>) =>
      request<{ key: string; value: unknown }>(`/api/settings/${key}`, {
        method: "PATCH",
        body: JSON.stringify({ value }),
      }),
    runRetention: () =>
      request<{ message: string; removed: number }>("/api/settings/retention/run", { method: "POST" }),
  },

  users: {
    list: () => request<{ items: User[]; total: number }>("/api/users"),
    create: (value: {
      username: string;
      full_name: string;
      email: string;
      password: string;
      role: string;
      is_active: boolean;
    }) => request<User>("/api/users", jsonBody(value)),
    update: (id: number, value: Record<string, unknown>) =>
      request<User>(`/api/users/${id}`, { method: "PATCH", body: JSON.stringify(value) }),
    remove: (id: number) => request<{ message: string }>(`/api/users/${id}`, { method: "DELETE" }),
    roles: () =>
      request<{ items: import("./types").PermissionRole[] }>("/api/roles"),
    matrix: () =>
      request<{
        permissions: string[];
        roles: import("./types").PermissionRole[];
      }>("/api/roles/matrix"),
    audit: (params: Record<string, string | number | undefined> = {}) =>
      request<Paged<AuditEntry>>(`/api/audit-logs${query(params)}`),
    auditActions: () =>
      request<{ items: { action: string; count: number }[] }>("/api/audit-logs/actions"),
  },

  system: {
    health: () => request<HealthSnapshot>("/api/system/health"),
    info: () => request<SystemInfo>("/api/system/info"),
    levels: () => request<{ items: { value: string; label: string; min: number; description: string }[] }>(
      "/api/system/levels",
    ),
    ping: () => request<{ status: string; time: string }>("/api/system/ping"),
    restartPipeline: () =>
      request<{ message: string }>("/api/system/pipeline/restart", { method: "POST" }),
  },
};

/** Consume a `text/csv` style response as a browser download (optional path). */
export { download };

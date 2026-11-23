/** Shared API contracts for the Sentinel AI control center. */

export type Level = "normal" | "medium" | "high" | "critical";
export type IncidentStatus = "open" | "acknowledged" | "resolved" | "false_alarm";
export type ZoneType = "restricted" | "limited" | "public";

export interface PermissionRole {
  id: number;
  name: string;
  label: string;
  description: string;
  permissions: string[];
}

export interface User {
  id: number;
  username: string;
  full_name: string;
  email: string;
  is_active: boolean;
  role: PermissionRole;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface Camera {
  id: number;
  name: string;
  code: string;
  location: string;
  rtsp_url: string;
  source_type: "demo" | "rtsp" | "file" | "webcam" | string;
  status: string;
  is_enabled: boolean;
  fps: number;
  resolution: string;
  last_seen_at: string | null;
  notes: string;
  zones_count: number;
  active_threats: number;
  stream_url: string;
  snapshot_url: string;
  runtime_fps?: number;
  runtime_frames?: number;
  threat_level?: Level;
  risk_score?: number;
  last_frame_at?: string | null;
}

export interface CameraDevice {
  index: number;
  label: string;
  width: number;
  height: number;
  fps: number;
  has_signal: boolean;
  brightness: number;
  variance: number;
  backend?: string;
  frames_read?: number;
  note?: string;
}

export interface CameraMeta {
  source_types: { value: string; label: string }[];
  resolutions: string[];
  detector_modes: string[];
  demo_mode: boolean;
  live_only: boolean;
  evidence_enabled: boolean;
  evidence_saved: boolean;
  live_camera_index: number;
  webcam_backend?: string;
  continuous_recording_enabled?: boolean;
  continuous_segment_seconds?: number;
  save_motion_snapshots?: boolean;
  max_fps: number;
}

export interface CameraDiscovery {
  items: CameraDevice[];
  live_only: boolean;
  active_index: number;
  recommended_index?: number | null;
  live_devices?: number;
  total_devices?: number;
  hidden_inactive?: number;
  backend?: string;
}

export interface LiveDeviceSelection {
  message: string;
  index: number;
  devices?: CameraDevice[];
}

export interface Zone {
  id: number;
  camera_id: number;
  name: string;
  zone_type: ZoneType;
  points: number[][];
  schedule_start: string;
  schedule_end: string;
  schedule_label?: string;
  days: number[];
  min_dwell_seconds: number;
  min_frames: number;
  cooldown_seconds: number;
  is_enabled: boolean;
  color: string;
  camera_name?: string | null;
}

export interface RiskFactorsStored {
  contributions?: Record<string, number>;
  breakdown?: Record<string, number>;
  dwell_seconds?: number;
  behavior?: string;
  frames_seen?: number;
  [key: string]: unknown;
}

export interface Incident {
  id: number;
  code: string;
  camera_id: number;
  zone_id: number | null;
  incident_type: string;
  title: string;
  risk_score: number;
  level: Level;
  level_label: string;
  status: IncidentStatus;
  explanation: string;
  factors: RiskFactorsStored;
  target_type: string;
  track_id: string;
  face_status: string;
  detected_at: string;
  acknowledged_at: string | null;
  acknowledged_by_id: number | null;
  resolved_at: string | null;
  snapshot_url: string | null;
  clip_url: string | null;
  camera_name: string | null;
  camera_code: string | null;
  camera_location: string | null;
  zone_name: string | null;
  zone_type: ZoneType | null;
  type_label: string;
  meta: Record<string, unknown>;
  alerts?: Alert[];
  recordings?: Recording[];
  acknowledgements?: Acknowledgement[];
  event_count?: number;
  minutes_open?: number;
  acknowledged_by?: string | null;
}

export interface ActiveIncidents {
  items: Incident[];
  total: number;
  primary: Incident | null;
  critical_count: number;
  high_count: number;
}

export interface AlertTemplate {
  threat_type: string;
  label: string;
  en: string;
  ar: string;
}

export interface AlertTemplates {
  languages: { code: string; label: string; voice: string }[];
  channels: { value: string; label: string }[];
  threats: { value: string; label: string }[];
  templates: AlertTemplate[];
}

export interface EventItem {
  id: number;
  camera_id: number;
  zone_id: number | null;
  incident_id: number | null;
  event_type: string;
  target_type: string;
  confidence: number;
  bbox: number[];
  track_id: string;
  is_threat: boolean;
  snapshot_url: string | null;
  meta: Record<string, unknown>;
  occurred_at: string;
  camera_name: string | null;
  zone_name: string | null;
}

export interface Alert {
  id: number;
  incident_id: number;
  channel: "voice" | "notification" | "siren" | string;
  language: string;
  message: string;
  status: string;
  sent_to: string;
  played_at: string | null;
  acknowledged_at: string | null;
  detail: string;
  created_at: string;
  incident_code?: string;
  incident_title?: string;
  incident_level?: Level;
  incident_status?: IncidentStatus;
  camera_id?: number;
  snapshot_url?: string | null;
  detected_at?: string;
}

export interface Recording {
  id: number;
  incident_id: number | null;
  camera_id: number;
  kind: "clip" | "snapshot" | "continuous" | string;
  url: string | null;
  path: string;
  started_at: string;
  ended_at: string;
  duration_seconds: number;
  size_bytes: number;
  created_at: string;
  camera_name?: string | null;
  camera_code?: string | null;
  incident_code?: string;
  incident_level?: Level;
}

export interface EvidenceAuditIssue {
  kind: "recording" | "referenced_media" | "orphan" | string;
  path: string;
  sources: string[];
  problem: string;
  active: boolean;
  expected: boolean;
  fixed?: boolean;
}

export interface EvidenceAudit {
  healthy: boolean;
  repair: boolean;
  checked_files: number;
  summary: {
    recording_rows: number;
    referenced_files: number;
    issues: number;
    expected_active: number;
    fixed: number;
    unresolved: number;
  };
  issues: EvidenceAuditIssue[];
  fixed: EvidenceAuditIssue[];
}

export interface Acknowledgement {
  id: number;
  incident_id: number;
  user_id: number;
  user_name: string | null;
  note: string;
  acknowledged_at: string;
}

export interface Person {
  id: number;
  full_name: string;
  title: string;
  consent_given: boolean;
  consent_at: string | null;
  photo_url: string | null;
  is_active: boolean;
  notes: string;
  has_embedding: boolean;
  created_at: string;
}

export interface FaceEngineStatus {
  enabled: boolean;
  available?: boolean;
  backend?: string;
  threshold: number;
  note: string;
  [key: string]: unknown;
}

export interface AuditEntry {
  id: number;
  user_id: number | null;
  username: string;
  action: string;
  target: string;
  detail: string;
  ip_address: string;
  created_at: string;
}

export interface SystemInfo {
  app_name: string;
  version: string;
  environment: string;
  python: string;
  platform: string;
  pipeline_enabled: boolean;
  supervisor_running: boolean;
  demo_mode: boolean;
  live_only?: boolean;
  evidence_enabled?: boolean;
  evidence_saved?: boolean;
  live_camera_index?: number;
  webcam_backend?: string;
  continuous_recording_enabled?: boolean;
  continuous_segment_seconds?: number;
  save_motion_snapshots?: boolean;
  detector_mode: string;
  face_recognition_enabled: boolean;
  face_engine: FaceEngineStatus;
  recording_enabled: boolean;
  retention_days: number;
  voice_enabled: boolean;
  siren_enabled: boolean;
  storage: {
    total_gb: number;
    used_gb: number;
    free_gb: number;
    percent: number;
    storage_gb: number;
  };
  storage_estimate: Record<string, number>;
  timezone: string;
  server_time: string;
}

export interface HealthSnapshot {
  status: "healthy" | "warning" | "critical" | "idle" | string;
  cpu_percent: number;
  memory_percent: number;
  disk_percent: number;
  storage_gb: number;
  disk_free_gb?: number;
  cameras_online: number;
  cameras_total: number;
  uptime_seconds: number;
  websocket_clients?: number;
  fps_total: number;
  pipeline_running?: boolean;
  recorded_today_gb?: number;
  cameras?: Record<string, CameraRuntimeStatus>;
  checked_at: string;
}

export interface CameraRuntimeStatus {
  status: string;
  fps?: number;
  frames?: number;
  threat_level?: Level;
  risk_score?: number;
  last_frame_at?: string;
  [key: string]: unknown;
}

export interface DashboardKpis {
  active_threats: number;
  incidents_today: number;
  events_today: number;
  critical_today: number;
  false_alarms_today: number;
  false_alarm_rate: number;
  avg_response_minutes: number;
  verified_reduction: number;
  cameras_online: number;
  cameras_total: number;
  storage_gb: number;
  storage_percent: number;
  uptime_seconds: number;
}

export interface DashboardCamera {
  id: number;
  name: string;
  code: string;
  location: string;
  source_type: string;
  is_enabled: boolean;
  status: string;
  fps: number;
  threat_level: Level;
  risk_score: number;
  active_threats: number;
  last_seen_at: string | null;
  stream_url: string;
  snapshot_url: string;
}

export interface TimelinePoint {
  hour: string;
  timestamp?: string;
  incidents: number;
  events: number;
}

export interface LevelCount {
  level: Level;
  label: string;
  count: number;
}

export interface TypeCount {
  incident_type: string;
  label: string;
  count: number;
}

export interface WeeklyPoint {
  date: string;
  label: string;
  incidents: number;
  critical: number;
}

export interface TopZone {
  zone_name: string;
  zone_type: ZoneType;
  camera_code: string;
  incidents: number;
}

export interface ActivityEntry {
  id: number;
  username: string;
  action: string;
  target: string;
  detail: string;
  created_at: string;
}

export interface Dashboard {
  generated_at: string;
  kpis: DashboardKpis;
  active: {
    items: Incident[];
    total: number;
    primary: Incident | null;
    critical_count: number;
    high_count: number;
  };
  recent_incidents: Incident[];
  recent_events: EventItem[];
  timeline: TimelinePoint[];
  level_distribution: LevelCount[];
  type_distribution: TypeCount[];
  weekly: WeeklyPoint[];
  cameras: DashboardCamera[];
  health: HealthSnapshot;
  top_zones: TopZone[];
  activity: ActivityEntry[];
  alerting: {
    voice_enabled: boolean;
    siren_enabled: boolean;
    languages: string[];
    repeat_seconds: number;
  };
}

export interface AppSettings {
  risk_weights: Record<string, number>;
  risk_thresholds: Record<string, number>;
  verification: Record<string, number | boolean>;
  voice: { enabled: boolean; repeat_seconds: number; languages: string[] };
  alarm: { siren_enabled: boolean; webhook_url: string; notify_admin: boolean };
  recording: {
    enabled: boolean;
    pre_event_seconds: number;
    post_event_seconds: number;
    retention_days: number;
  };
  ai: {
    detector_mode: string;
    face_recognition_enabled: boolean;
    target_fps: number;
    demo_mode: boolean;
  };
  company: { name: string; site: string; timezone: string; notice: string };
}

export interface SettingsMetadata {
  risk_factors: { key: string; label: string; default: number }[];
  levels: { value: Level; label: string }[];
  zone_types: { value: ZoneType; label: string }[];
  threat_types: { value: string; label: string }[];
  languages: { code: string; label: string; voice: string }[];
  permissions: string[];
  roles: { name: string; label: string; description: string; permissions: string[] }[];
  voice_template_count: number;
  environment: Record<string, string | number | boolean>;
  [key: string]: unknown;
}

export interface SettingsResponse {
  settings: AppSettings;
  defaults: AppSettings;
  metadata: SettingsMetadata;
}

export interface ZoneMeta {
  zone_types: { value: ZoneType; label: string; description: string; color: string }[];
  weekdays: { value: number; label: string }[];
  defaults: { min_dwell_seconds: number; min_frames: number; cooldown_seconds: number };
}

export interface ReportOverview {
  generated_at: string;
  range: { start: string; end: string; days: number };
  totals: {
    incidents: number;
    events: number;
    critical: number;
    high: number;
    medium: number;
    normal: number;
    false_alarms: number;
    open: number;
    acknowledged: number;
    resolved: number;
    false_alarm_rate: number;
    avg_response_minutes: number;
    avg_resolution_minutes: number;
    verification_reduction: number;
  };
  by_level: LevelCount[];
  by_type: TypeCount[];
  by_status: { status: string; count: number }[];
  by_camera: { camera_name: string; count: number }[];
  by_zone: { zone_name: string; count: number }[];
  daily: { date: string; label: string; incidents: number; critical: number; high: number }[];
}

export interface RealtimeMessage<T = unknown> {
  type: string;
  data: T;
  ts?: string;
}

export interface Paged<T> {
  items: T[];
  total: number;
  limit?: number;
  offset?: number;
}

export interface RiskPreview {
  score: number;
  level: Level;
  level_label: string;
  explanation: string;
  breakdown: Record<string, number>;
  contributions: Record<string, number>;
  factors: Record<
    string,
    { label: string; weight: number; normalized: number; contribution: number }
  >;
}

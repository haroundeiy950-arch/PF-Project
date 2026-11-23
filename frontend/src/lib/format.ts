/** Formatting helpers shared across the control center UI. */

import type { IncidentStatus, Level, ZoneType } from "../types";

const pad = (value: number) => String(value).padStart(2, "0");

export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatTime(value: string | null | undefined, withSeconds = false): string {
  const date = parseDate(value);
  if (!date) return "—";
  return withSeconds
    ? `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
    : `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function formatDate(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function formatDateTime(value: string | null | undefined, seconds = false): string {
  const date = parseDate(value);
  if (!date) return "—";
  return `${formatDate(value)} ${formatTime(value, seconds)}`;
}

export function formatRelative(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}

export function formatUptime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

export function formatGb(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(1)} TB`;
  return `${Number(value).toFixed(1)} GB`;
}

export const LEVEL_LABELS: Record<Level, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  normal: "Normal",
};

export const LEVEL_DESCRIPTIONS: Record<Level, string> = {
  critical: "Flashing red frame, immediate siren and administrator notification.",
  high: "Audible warning, event recorded and a notification sent.",
  medium: "Warning sign, event recorded and followed up.",
  normal: "Continuous monitoring with no alarm.",
};

export const INCIDENT_STATUS_LABELS: Record<IncidentStatus, string> = {
  open: "Open",
  acknowledged: "Acknowledged",
  resolved: "Resolved",
  false_alarm: "False alarm",
};

export const ZONE_LABELS: Record<ZoneType, string> = {
  restricted: "Restricted",
  limited: "Limited",
  public: "Public",
};

export const EVENT_TYPE_LABELS: Record<string, string> = {
  restricted_intrusion: "Restricted intrusion",
  unknown_face: "Unknown face",
  abnormal_activity: "Abnormal activity",
  loitering: "Loitering",
  vehicle_intrusion: "Vehicle intrusion",
  door_open: "Door opened",
  motion: "Motion",
  person: "Person",
  vehicle: "Vehicle",
  animal: "Animal",
  unknown: "Unknown",
};

export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  return EVENT_TYPE_LABELS[value] ?? value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function todayInput(): string {
  const date = new Date();
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function daysAgoInput(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function toApiDate(value: string): string {
  if (!value) return "";
  return `${value} 00:00:00`;
}

export function toApiEnd(value: string): string {
  if (!value) return "";
  return `${value} 23:59:59`;
}

export function countdown(target: string | number | null | undefined): number {
  if (target === null || target === undefined) return 0;
  const stamp = typeof target === "number" ? target : new Date(target).getTime();
  if (Number.isNaN(stamp)) return 0;
  return Math.max(0, Math.floor((stamp - Date.now()) / 1000));
}

export function formatCountdown(seconds: number): string {
  const safe = Math.max(0, seconds);
  return `${pad(Math.floor(safe / 60))}:${pad(safe % 60)}`;
}

export function cx(...values: (string | false | null | undefined)[]): string {
  return values.filter(Boolean).join(" ");
}

export function percentage(value: number, total: number): number {
  if (!total) return 0;
  return Math.round((value / total) * 100);
}

export function initials(name: string | null | undefined): string {
  if (!name) return "??";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

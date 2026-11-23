/** Reusable presentation primitives used by every screen. */

import type { CSSProperties, ReactNode } from "react";
import { useEffect } from "react";
import type { IncidentStatus, Level } from "../types";
import { cx, INCIDENT_STATUS_LABELS, LEVEL_LABELS } from "../lib/format";
import { IconClose, IconRefresh, IconWarning } from "./Icons";

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
  accent,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  accent?: "cyan" | "red" | "amber" | "green" | "none";
}) {
  return (
    <section className={cx("panel", accent && `panel--${accent}`, className)}>
      {(title || actions) && (
        <header className="panel__head">
          <div>
            {title && <h2 className="panel__title">{title}</h2>}
            {subtitle && <p className="panel__subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="panel__actions">{actions}</div>}
        </header>
      )}
      <div className={cx("panel__body", bodyClassName)}>{children}</div>
    </section>
  );
}

export function LevelBadge({ level, pulse = false }: { level: Level; pulse?: boolean }) {
  return (
    <span className={cx("level-badge", `level-badge--${level}`, pulse && "level-badge--pulse")}>
      <span className="level-badge__dot" />
      {LEVEL_LABELS[level]}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const label = INCIDENT_STATUS_LABELS[status as IncidentStatus] ?? status.replace(/_/g, " ");
  return <span className={cx("status-badge", `status-badge--${status}`)}>{label}</span>;
}

export function ScoreRing({
  score,
  level,
  size = 132,
  label = "RISK SCORE",
}: {
  score: number;
  level: Level;
  size?: number;
  label?: string;
}) {
  const radius = (size - 14) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, score));
  return (
    <div className={cx("score-ring", `score-ring--${level}`)} style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={radius} className="score-ring__track" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          className="score-ring__value"
          strokeDasharray={circumference}
          strokeDashoffset={circumference - (clamped / 100) * circumference}
        />
      </svg>
      <div className="score-ring__content">
        <strong>{score}</strong>
        <span>/100</span>
        <small>{label}</small>
      </div>
    </div>
  );
}

export function Gauge({
  value,
  label,
  suffix = "%",
  tone,
}: {
  value: number;
  label: string;
  suffix?: string;
  tone?: "cyan" | "amber" | "red" | "green";
}) {
  const clamped = Math.max(0, Math.min(100, value));
  const color = tone ?? (clamped >= 90 ? "red" : clamped >= 75 ? "amber" : "cyan");
  return (
    <div className={cx("gauge", `gauge--${color}`)}>
      <div className="gauge__head">
        <span>{label}</span>
        <strong>
          {Math.round(value)}
          {suffix}
        </strong>
      </div>
      <div className="gauge__track">
        <div className="gauge__fill" style={{ width: `${clamped}%` }} />
      </div>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  message,
  action,
}: {
  icon?: ReactNode;
  title: string;
  message?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-state__icon">{icon}</div>}
      <h3>{title}</h3>
      {message && <p>{message}</p>}
      {action}
    </div>
  );
}

export function LoadingState({ label = "Loading secure data…" }: { label?: string }) {
  return (
    <div className="loading-state">
      <span className="spinner" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="error-state">
      <IconWarning size={22} />
      <div>
        <strong>Request failed</strong>
        <p>{message}</p>
      </div>
      {retry && (
        <button type="button" className="btn btn--ghost btn--sm" onClick={retry}>
          <IconRefresh size={14} /> Retry
        </button>
      )}
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
}) {
  return (
    <label className={cx("toggle-row", disabled && "is-disabled")}>
      <span>
        <strong>{label}</strong>
        {description && <small>{description}</small>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        className={cx("switch", checked && "switch--on")}
        onClick={() => !disabled && onChange(!checked)}
        disabled={disabled}
      >
        <span className="switch__thumb" />
      </button>
    </label>
  );
}

export function Modal({
  open,
  title,
  subtitle,
  onClose,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
}) {
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    document.body.classList.add("modal-open");
    return () => {
      document.removeEventListener("keydown", handler);
      document.body.classList.remove("modal-open");
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className={cx("modal", `modal--${size}`)} role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal__head">
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close dialog">
            <IconClose size={18} />
          </button>
        </header>
        <div className="modal__body">{children}</div>
        {footer && <footer className="modal__foot">{footer}</footer>}
      </div>
    </div>
  );
}

export function Pagination({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <div className="pagination">
      <span>
        Page {page} of {pages} · {total} records
      </span>
      <div>
        <button type="button" className="btn btn--ghost btn--sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
          Previous
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          disabled={offset + limit >= total}
          onClick={() => onChange(offset + limit)}
        >
          Next
        </button>
      </div>
    </div>
  );
}

export function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "cyan" | "red" | "amber" | "green";
}) {
  return (
    <div className={cx("metric", tone && `metric--${tone}`)}>
      <span className="metric__label">{label}</span>
      <strong className="metric__value">{value}</strong>
      {hint && <span className="metric__hint">{hint}</span>}
    </div>
  );
}

export function BarList({
  items,
  color = "cyan",
  valueSuffix = "",
}: {
  items: { label: string; value: number; hint?: string }[];
  color?: "cyan" | "red" | "amber";
  valueSuffix?: string;
}) {
  const max = Math.max(1, ...items.map((item) => item.value));
  return (
    <div className="bar-list">
      {items.map((item) => (
        <div className="bar-list__item" key={`${item.label}-${item.value}`}>
          <div className="bar-list__head">
            <span>{item.label}</span>
            <strong>
              {item.value}
              {valueSuffix}
            </strong>
          </div>
          <div className="bar-list__track">
            <span
              className={cx("bar-list__fill", `bar-list__fill--${color}`)}
              style={{ width: `${(item.value / max) * 100}%` }}
            />
          </div>
          {item.hint && <small>{item.hint}</small>}
        </div>
      ))}
    </div>
  );
}

export function TonePill({
  children,
  tone = "muted",
}: {
  children: ReactNode;
  tone?: "cyan" | "red" | "amber" | "green" | "muted";
}) {
  return <span className={cx("tone-pill", `tone-pill--${tone}`)}>{children}</span>;
}

export function RingStat({
  value,
  label,
  color,
  size = 54,
}: {
  value: number;
  label: string;
  color?: string;
  size?: number;
}) {
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const style = { "--ring-color": color } as CSSProperties;
  return (
    <div className="ring-stat" style={style}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={radius} className="ring-stat__track" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          className="ring-stat__value"
          strokeDasharray={circumference}
          strokeDashoffset={circumference - (Math.max(0, Math.min(100, value)) / 100) * circumference}
        />
      </svg>
      <strong>{Math.round(value)}</strong>
      <span>{label}</span>
    </div>
  );
}

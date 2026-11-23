export type StatusTone = "success" | "warn" | "danger" | "info" | "muted";

const TONE_CLASS: Record<StatusTone, string> = {
  success:
    "bg-[var(--status-success-bg)] text-[var(--status-success-fg)] border-[var(--status-success-border)]",
  warn: "bg-[var(--status-warn-bg)] text-[var(--status-warn-fg)] border-[var(--status-warn-border)]",
  danger:
    "bg-[var(--status-danger-bg)] text-[var(--status-danger-fg)] border-[var(--status-danger-border)]",
  info: "bg-[var(--status-info-bg)] text-[var(--status-info-fg)] border-[var(--status-info-border)]",
  muted: "bg-muted text-muted-foreground border-border",
};

export function toneClass(tone: StatusTone): string {
  return TONE_CLASS[tone];
}

export function toneFromLabel(label: string): StatusTone {
  const v = label.toLowerCase();
  // Exact lifecycle statuses first (applied ≠ resolved).
  if (v === "resolved" || v === "completed" || v === "accepted" || v === "implemented") {
    return "success";
  }
  if (v === "applied") {
    return "info";
  }
  if (v === "pending" || v === "rolled_back") {
    return "warn";
  }
  if (v === "ignored" || v === "rejected" || v === "deferred") {
    return "muted";
  }
  if (["pass", "success", "healthy", "ok", "low", "completed"].some((x) => v.includes(x))) {
    return "success";
  }
  if (["warn", "warning", "medium", "stale"].some((x) => v.includes(x))) {
    return "warn";
  }
  if (["block", "fail", "error", "high", "critical", "danger"].some((x) => v.includes(x))) {
    return "danger";
  }
  if (["running", "info", "progress"].some((x) => v.includes(x))) {
    return "info";
  }
  return "muted";
}

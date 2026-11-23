/**
 * Parse API timestamps. Naive ISO values from SQLite are UTC; browsers otherwise
 * treat them as local time (e.g. IST), which skews relative labels by hours.
 */
export function parseApiDate(iso: string): Date {
  const trimmed = iso.trim();
  if (/([zZ]|[+-]\d{2}:?\d{2})$/.test(trimmed)) {
    return new Date(trimmed);
  }
  if (/^\d{4}-\d{2}-\d{2}T/.test(trimmed)) {
    return new Date(`${trimmed}Z`);
  }
  return new Date(trimmed);
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = parseApiDate(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const diff = Date.now() - date.getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return date.toLocaleDateString();
}

export function shortSha(sha: string | null | undefined): string {
  if (!sha) return "—";
  return sha.slice(0, 7);
}

export function scoreLabel(score: number): string {
  if (score >= 80) return "Healthy";
  if (score >= 60) return "Fair";
  if (score >= 40) return "At risk";
  return "Critical";
}

/** Presentational risk from health fields — not a separate API field. */
export function riskFromHealth(overall: number, criticalCount: number): string {
  if (criticalCount > 0 || overall < 40) return "high";
  if (overall < 60) return "medium";
  return "low";
}

export function trendDirection(values: number[] | undefined): string {
  if (!values || values.length < 2) return "stable";
  const a = values[values.length - 2]!;
  const b = values[values.length - 1]!;
  if (b - a > 1) return "up";
  if (a - b > 1) return "down";
  return "stable";
}

export function formatHealthScore(score: number | null | undefined): string {
  if (score == null) return "—";
  return Math.round(score).toString();
}

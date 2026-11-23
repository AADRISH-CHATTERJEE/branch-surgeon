/**
 * Build Graph Workspace URL from Branch Surgeon context.
 * Repo/branch context stays in RepoProvider; optional node focus via query.
 */
export function graphWorkspaceHref(focusFile?: string | null): string {
  const base = "/repository/graph";
  const file = focusFile?.trim();
  if (!file) return base;
  return `${base}?node=${encodeURIComponent(file)}`;
}

/** Prefer critical blast files, then most-connected, for graph focus. */
export function blastFocusFile(blast?: {
  critical_files?: string[] | null;
  most_connected?: string[] | null;
} | null): string | null {
  const critical = blast?.critical_files?.find((f) => f?.trim());
  if (critical) return critical;
  const connected = blast?.most_connected?.find((f) => f?.trim());
  return connected ?? null;
}

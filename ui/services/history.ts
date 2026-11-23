import { apiRequest, type ApiClientOptions } from "@/services/client";
import { endpoints } from "@/services/endpoints";
import type { HistoryItem, HistoryMetrics } from "@/types/domain";

export type HistoryListParams = {
  analysis_type?: string;
  status?: string;
  branch?: string;
  search?: string;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
};

export function fetchHistory(
  options: ApiClientOptions = {},
  params: HistoryListParams = {},
) {
  const sp = new URLSearchParams();
  if (params.analysis_type) sp.set("analysis_type", params.analysis_type);
  if (params.status) sp.set("status", params.status);
  if (params.branch) sp.set("branch", params.branch);
  if (params.search) sp.set("search", params.search);
  if (params.since) sp.set("since", params.since);
  if (params.until) sp.set("until", params.until);
  if (params.limit) sp.set("limit", String(params.limit));
  if (params.offset) sp.set("offset", String(params.offset));
  const q = sp.toString();
  return apiRequest<HistoryItem[]>(
    `${endpoints.history}${q ? `?${q}` : ""}`,
    options,
  );
}

export function fetchHistoryMetrics(options: ApiClientOptions = {}) {
  return apiRequest<HistoryMetrics>(endpoints.historyMetrics, options);
}

export function fetchHistoryItem(id: string, options: ApiClientOptions = {}) {
  return apiRequest<HistoryItem>(endpoints.historyItem(id), options);
}

export function applyHistoryRetention(
  days: number | null,
  options: ApiClientOptions = {},
) {
  return apiRequest<{ deleted: number; retention_days: number | null }>(
    endpoints.historyRetention,
    {
      ...options,
      method: "POST",
      body: JSON.stringify({ days }),
    },
  );
}

export async function downloadHistoryExport(
  format: "json" | "markdown" | "csv",
  options: ApiClientOptions = {},
) {
  const base = (
    options.baseUrl ||
    process.env.NEXT_PUBLIC_REFACTORY_API_URL ||
    "http://127.0.0.1:8741"
  ).replace(/\/$/, "");
  const path = `${endpoints.historyExport}?format=${format}`;
  const headers: Record<string, string> = { Accept: "*/*" };
  if (options.repoRoot) headers["X-Repo-Root"] = options.repoRoot;
  const res = await fetch(`${base}${path}`, { headers, signal: options.signal });
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  const blob = await res.blob();
  const a = document.createElement("a");
  const objectUrl = URL.createObjectURL(blob);
  a.href = objectUrl;
  a.download = `analysis-history.${format === "markdown" ? "md" : format}`;
  a.click();
  URL.revokeObjectURL(objectUrl);
}

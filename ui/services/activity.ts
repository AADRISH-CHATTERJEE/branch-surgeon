import { apiRequest, type ApiClientOptions } from "@/services/client";
import { endpoints } from "@/services/endpoints";
import type { AnalysisRun } from "@/types/domain";

export function fetchActivity(
  options: ApiClientOptions = {},
  params: { limit?: number; command?: string; status?: string } = {},
) {
  const sp = new URLSearchParams();
  if (params.limit) sp.set("limit", String(params.limit));
  if (params.command) sp.set("command", params.command);
  if (params.status) sp.set("status", params.status);
  const q = sp.toString();
  return apiRequest<AnalysisRun[]>(`${endpoints.activity}${q ? `?${q}` : ""}`, options);
}

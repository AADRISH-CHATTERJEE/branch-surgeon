import { apiRequest, type ApiClientOptions } from "@/services/client";
import { endpoints } from "@/services/endpoints";

export function buildIndex(force = false, options: ApiClientOptions = {}) {
  return apiRequest<Record<string, unknown>>(endpoints.index, {
    ...options,
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

export function fetchIndexStatus(options: ApiClientOptions = {}) {
  return apiRequest<Record<string, unknown>>(endpoints.indexStatus, options);
}

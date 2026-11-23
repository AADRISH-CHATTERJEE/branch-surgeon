import { apiRequest, type ApiClientOptions } from "@/services/client";
import { endpoints } from "@/services/endpoints";
import type { HealthData } from "@/types/api";

export function fetchHealth(options: ApiClientOptions = {}) {
  return apiRequest<HealthData>(endpoints.health, options);
}

import { apiRequest, type ApiClientOptions } from "@/services/client";
import { endpoints } from "@/services/endpoints";
import type { RulesCheckResult, RulesListData } from "@/types/domain";

export function fetchRules(options: ApiClientOptions = {}) {
  return apiRequest<RulesListData>(endpoints.rules, options);
}

export function checkRules(
  body: {
    branch?: string | null;
    commit?: string | null;
    base?: string | null;
    changed_files?: string[] | null;
  } = {},
  options: ApiClientOptions = {},
) {
  return apiRequest<RulesCheckResult>(endpoints.rulesCheck, {
    ...options,
    method: "POST",
    body: JSON.stringify(body),
  });
}

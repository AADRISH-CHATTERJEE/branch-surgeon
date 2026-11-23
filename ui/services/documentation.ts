import { apiRequest, type ApiClientOptions } from "@/services/client";
import { endpoints } from "@/services/endpoints";
import type { CompanyDocumentation } from "@/types/domain";

export function fetchDocumentation(options: ApiClientOptions = {}) {
  return apiRequest<CompanyDocumentation>(endpoints.documentation, options);
}

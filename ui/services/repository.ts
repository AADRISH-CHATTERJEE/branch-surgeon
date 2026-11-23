import { apiRequest, type ApiClientOptions } from "@/services/client";
import { endpoints } from "@/services/endpoints";
import type { RepositoryData, RepositoryStatusData } from "@/types/api";
import type {
  HealthReport,
  RepoFile,
  RepoFileContent,
  RepoImport,
  RepoSymbol,
} from "@/types/domain";

export function fetchRepository(options: ApiClientOptions = {}) {
  return apiRequest<RepositoryData>(endpoints.repository, options);
}

export function fetchRepositoryStatus(options: ApiClientOptions = {}) {
  return apiRequest<RepositoryStatusData>(endpoints.repositoryStatus, options);
}

export function fetchRepositoryHealth(options: ApiClientOptions = {}) {
  return apiRequest<HealthReport>(endpoints.repositoryHealth, options);
}

export function fetchRepositoryFiles(
  options: ApiClientOptions = {},
  params: { language?: string; limit?: number } = {},
) {
  const sp = new URLSearchParams();
  if (params.language) sp.set("language", params.language);
  if (params.limit) sp.set("limit", String(params.limit));
  const q = sp.toString();
  return apiRequest<RepoFile[]>(
    `${endpoints.repositoryFiles}${q ? `?${q}` : ""}`,
    options,
  );
}

export function fetchRepositoryFileContent(
  options: ApiClientOptions = {},
  params: { path: string },
) {
  const sp = new URLSearchParams();
  sp.set("path", params.path);
  return apiRequest<RepoFileContent>(
    `${endpoints.repositoryFile}?${sp.toString()}`,
    options,
  );
}

export function fetchRepositorySymbols(
  options: ApiClientOptions = {},
  params: { file_id?: string; path?: string; limit?: number } = {},
) {
  const sp = new URLSearchParams();
  if (params.file_id) sp.set("file_id", params.file_id);
  if (params.path) sp.set("path", params.path);
  if (params.limit) sp.set("limit", String(params.limit));
  const q = sp.toString();
  return apiRequest<RepoSymbol[]>(
    `${endpoints.repositorySymbols}${q ? `?${q}` : ""}`,
    options,
  );
}

export function fetchRepositoryImports(
  options: ApiClientOptions = {},
  params: { file_id?: string; path?: string; limit?: number } = {},
) {
  const sp = new URLSearchParams();
  if (params.file_id) sp.set("file_id", params.file_id);
  if (params.path) sp.set("path", params.path);
  if (params.limit) sp.set("limit", String(params.limit));
  const q = sp.toString();
  return apiRequest<RepoImport[]>(
    `${endpoints.repositoryImports}${q ? `?${q}` : ""}`,
    options,
  );
}

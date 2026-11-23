/** Local REST API envelope — mirrors refactory.api.schemas.ApiResponse */

export type ApiStatus = "success" | "error";

export interface ApiResponse<T = unknown> {
  status: ApiStatus;
  message: string;
  data: T | null;
  errors: string[];
  meta: Record<string, unknown>;
}

export interface HealthData {
  service: string;
  version: string;
}

export interface RepositoryData {
  name: string;
  root_path: string;
  current_branch: string;
  default_branch: string | null;
  remote_url: string | null;
  head_sha: string | null;
  is_dirty?: boolean;
  is_detached?: boolean;
  working_tree?: "clean" | "dirty" | string;
  dirty_files?: string[];
  ahead?: number | null;
  behind?: number | null;
  root?: string;
  remote?: string | null;
  branch?: string;
  head?: string | null;
  owner?: string | null;
  full_name?: string | null;
}

export interface RepositoryStatusData {
  name?: string;
  root?: string;
  root_path?: string;
  branch?: string;
  current_branch?: string;
  default_branch?: string | null;
  head?: string | null;
  head_sha?: string | null;
  remote?: string | null;
  remote_url?: string | null;
  working_tree?: "clean" | "dirty" | string;
  is_dirty?: boolean;
  ahead?: number | null;
  behind?: number | null;
  ai_provider: string;
  ai_model: string | null;
  cache_enabled: boolean;
  backend_url: string | null;
  index_staleness: Record<string, unknown>;
  review_engine: string;
}

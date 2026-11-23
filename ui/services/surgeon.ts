/**
 * Branch Surgeon Local API — single orchestrated workspace snapshot.
 */

import { apiRequest, type ApiClientOptions } from "@/services/client";
import { endpoints } from "@/services/endpoints";

export type SurgeonAnalysisStatus =
  | "unavailable"
  | "composed"
  | "idle"
  | "running"
  | "ready"
  | "error";

export type SurgeonAvailability = {
  status: SurgeonAnalysisStatus;
  message: string;
  composedFrom: string[];
  missing: string[];
};

export type BranchSurgeonWorkspace = {
  branch: {
    name: string;
    base_branch: string;
    head_sha?: string | null;
    repository?: string;
    commits: number;
    changed_files: number;
    insertions: number;
    deletions: number;
  };
  health: {
    overall: number;
    architecture: number;
    security: number;
    testing: number;
    maintainability?: number;
  };
  surgery: {
    score: number;
    grade: string;
    formula?: string;
  };
  blast_radius: {
    node_count: number;
    edge_count: number;
    critical_files: string[];
    most_connected: string[];
  };
  recommendations: {
    total: number;
    critical: number;
    high: number;
    medium?: number;
    low?: number;
    pending?: number;
    resolved?: number;
    ignored?: number;
    by_type?: Record<string, number>;
    last_updated?: string | null;
    repository_id?: string;
    repository?: string;
    repo_root?: string;
    branch?: string;
    source?: string;
    version?: string;
  };
  reviews: {
    completed: number;
    pending: number;
    latest?: {
      id?: string;
      pr_number?: number | null;
      risk?: string;
      summary?: string;
      created_at?: string | null;
      suggestion_count?: number;
      /** Null/omitted means not recorded — never treat as 0%. */
      confidence?: number | null;
    } | null;
  };
  rules: {
    passed: number;
    failed: number;
    warning_count: number;
    outcome: string;
  };
  merge_conflict_risk: {
    level: string;
    score: number;
    reason: string;
  };
  confidence?: number | null;
  surgery_score?: number;
  timeline: Array<{
    id: string;
    kind: string;
    label: string;
    status: string;
    at?: string | null;
    detail?: string | null;
  }>;
};

export const SURGEON_API_REASON =
  "Branch Surgeon data comes from GET /branch-surgeon.";

export function getSurgeonAvailability(): SurgeonAvailability {
  return {
    status: "ready",
    message:
      "Branch Surgeon workspace loads from GET /branch-surgeon (orchestrated Local API snapshot).",
    composedFrom: ["GET /branch-surgeon"],
    missing: [
      "impacted tests",
      "advanced branch-scoped blast algorithms",
    ],
  };
}

export function fetchBranchSurgeon(options: ApiClientOptions = {}) {
  return apiRequest<BranchSurgeonWorkspace>(endpoints.branchSurgeon, options);
}

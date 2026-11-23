import {
  apiRequest,
  apiRequestWithMeta,
  type ApiClientOptions,
} from "@/services/client";
import { endpoints } from "@/services/endpoints";
import type {
  PatchApplyResult,
  PersistedRecommendation,
  RecommendationPatch,
  RecommendationRepositorySummary,
} from "@/types/domain";

export type RecommendationUpdateResult = {
  recommendation: PersistedRecommendation;
  summary: RecommendationRepositorySummary | null;
  oldStatus: string | null;
  newStatus: string | null;
};

export function fetchRecommendationStats(options: ApiClientOptions = {}) {
  return apiRequest<RecommendationRepositorySummary>(
    endpoints.recommendationStats,
    options,
  );
}

export async function updateRecommendation(
  recommendationId: string,
  body: {
    status?: string;
    priority?: string;
    resolution_notes?: string;
    verification_status?: string;
    updated_by?: string;
  },
  options: ApiClientOptions = {},
): Promise<RecommendationUpdateResult> {
  const envelope = await apiRequestWithMeta<PersistedRecommendation>(
    endpoints.recommendationItem(recommendationId),
    {
      ...options,
      method: "PATCH",
      body: JSON.stringify({ updated_by: "local", ...body }),
    },
  );
  const meta = envelope.meta ?? {};
  return {
    recommendation: envelope.data,
    summary:
      meta.summary && typeof meta.summary === "object"
        ? (meta.summary as RecommendationRepositorySummary)
        : null,
    oldStatus: typeof meta.old_status === "string" ? meta.old_status : null,
    newStatus: typeof meta.new_status === "string" ? meta.new_status : null,
  };
}

export function resolveRecommendation(
  recommendationId: string,
  options: ApiClientOptions = {},
) {
  return updateRecommendation(recommendationId, { status: "resolved" }, options);
}

export function ignoreRecommendation(
  recommendationId: string,
  options: ApiClientOptions = {},
) {
  return updateRecommendation(recommendationId, { status: "ignored" }, options);
}

export function deleteRecommendation(
  recommendationId: string,
  options: ApiClientOptions = {},
) {
  return apiRequest<{ id: string; deleted: boolean }>(
    endpoints.recommendationItem(recommendationId),
    { ...options, method: "DELETE" },
  );
}

export function fetchRecommendations(
  options: ApiClientOptions = {},
  params: { limit?: number; status?: string } = {},
) {
  const sp = new URLSearchParams();
  if (params.limit) sp.set("limit", String(params.limit));
  if (params.status) sp.set("status", params.status);
  const q = sp.toString();
  return apiRequest<PersistedRecommendation[]>(
    `${endpoints.recommendations}${q ? `?${q}` : ""}`,
    options,
  );
}

export function generateRecommendations(
  body: { top?: number; category?: string; priority?: string } = {},
  options: ApiClientOptions = {},
) {
  return apiRequest<Record<string, unknown>>(endpoints.recommend, {
    ...options,
    method: "POST",
    body: JSON.stringify({
      top: body.top ?? 15,
      category: body.category ?? null,
      priority: body.priority ?? null,
    }),
  });
}

export function generateRecommendationPatch(
  recommendationId: string,
  options: ApiClientOptions = {},
) {
  return apiRequest<RecommendationPatch>(
    endpoints.recommendationPatch(recommendationId),
    { ...options, method: "POST" },
  );
}

export function fetchRecommendationPatches(
  recommendationId: string,
  options: ApiClientOptions = {},
) {
  return apiRequest<RecommendationPatch[]>(
    endpoints.recommendationPatches(recommendationId),
    options,
  );
}

export function applyRecommendationPatch(
  patchId: string,
  options: ApiClientOptions = {},
  body: { dry_run?: boolean; applied_by?: string } = {},
) {
  return apiRequest<PatchApplyResult>(endpoints.applyPatch(patchId), {
    ...options,
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function applyRecommendation(
  recommendationId: string,
  options: ApiClientOptions = {},
  body: { patch_id?: string; dry_run?: boolean; applied_by?: string } = {},
) {
  return apiRequest<PatchApplyResult>(
    endpoints.applyRecommendation(recommendationId),
    {
      ...options,
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export function rollbackRecommendation(
  recommendationId: string,
  options: ApiClientOptions = {},
  body: { patch_id?: string; applied_by?: string } = {},
) {
  return apiRequest<PatchApplyResult>(
    endpoints.rollbackRecommendation(recommendationId),
    {
      ...options,
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

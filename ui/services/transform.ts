import { apiRequest, type ApiClientOptions } from "@/services/client";
import { endpoints } from "@/services/endpoints";
import type {
  TransformHistoryItem,
  TransformationPlanSummary,
  TransformPreview,
  TransformResult,
} from "@/types/domain";

export type TransformBody = {
  target_file?: string;
  transformation_type?: string;
  target_symbol?: string;
  parameters?: Record<string, unknown>;
  new_name?: string;
  method_name?: string;
  start_line?: number;
  end_line?: number;
  destination_file?: string;
  param_order?: string[];
  rename_params?: Record<string, string>;
  natural_language?: string;
  scope?: string;
  ai_assisted?: boolean;
};

function serializeBody(body: TransformBody) {
  return JSON.stringify({
    target_file: body.target_file ?? "",
    transformation_type: body.transformation_type ?? "rename_symbol",
    target_symbol: body.target_symbol ?? "",
    parameters: body.parameters ?? {},
    new_name: body.new_name,
    method_name: body.method_name,
    start_line: body.start_line,
    end_line: body.end_line,
    destination_file: body.destination_file,
    param_order: body.param_order,
    rename_params: body.rename_params,
    natural_language: body.natural_language,
    scope: body.scope,
    ai_assisted: body.ai_assisted,
  });
}

function clientOptions(options: ApiClientOptions = {}): ApiClientOptions & RequestInit {
  const { hydrated: _h, ...rest } = options as ApiClientOptions & { hydrated?: boolean };
  return rest;
}

export function planTransform(body: TransformBody, options: ApiClientOptions = {}) {
  return apiRequest<TransformationPlanSummary>(endpoints.transformPlan, {
    ...clientOptions(options),
    method: "POST",
    body: serializeBody(body),
  });
}

export function previewTransform(body: TransformBody, options: ApiClientOptions = {}) {
  console.debug("Transformation Preview Payload", body);
  return apiRequest<TransformPreview>(endpoints.transform, {
    ...clientOptions(options),
    method: "POST",
    body: serializeBody(body),
  });
}

export function applyTransform(body: TransformBody, options: ApiClientOptions = {}) {
  console.debug("Transformation Apply Payload", body);
  return apiRequest<TransformResult>(endpoints.transformApply, {
    ...clientOptions(options),
    method: "POST",
    body: serializeBody(body),
  });
}

export function rollbackTransform(options: ApiClientOptions = {}) {
  return apiRequest<TransformResult>(endpoints.transformRollback, {
    ...clientOptions(options),
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function rollbackTransformById(
  historyId: string,
  options: ApiClientOptions = {},
) {
  return apiRequest<TransformResult>(endpoints.transformRollbackById(historyId), {
    ...clientOptions(options),
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function fetchRecentTransforms(
  options: ApiClientOptions & { limit?: number } = {},
) {
  const limit = options.limit ?? 5;
  const { limit: _omit, ...rest } = options;
  return apiRequest<TransformHistoryItem[]>(
    `${endpoints.transformRecent}?limit=${limit}`,
    clientOptions(rest),
  );
}

import { apiRequest, type ApiClientOptions } from "@/services/client";
import { endpoints } from "@/services/endpoints";
import type { GraphFull, GraphNodeDetail } from "@/types/domain";

export function fetchGraphSummary(options: ApiClientOptions = {}) {
  return apiRequest<{ nodes: number | null; edges: number | null; statistics: unknown }>(
    endpoints.graph,
    options,
  );
}

export function fetchGraphFull(options: ApiClientOptions = {}) {
  return apiRequest<GraphFull>(endpoints.graphFull, options);
}

export function fetchGraphNode(id: string, options: ApiClientOptions = {}) {
  return apiRequest<GraphNodeDetail>(endpoints.graphNode(id), options);
}

export function buildGraph(force = false, options: ApiClientOptions = {}) {
  return apiRequest<Record<string, unknown>>(endpoints.graph, {
    ...options,
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

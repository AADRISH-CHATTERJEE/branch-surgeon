import type { GraphEdge, GraphNode } from "@/types/domain";

import { FILTER_GROUPS, type FilterGroupKey } from "./graph-styles";

export type GraphStats = {
  nodes: number;
  edges: number;
  files: number;
  classes: number;
  functions: number;
  modules: number;
  packages: number;
  dependencies: number;
  largestComponent: number;
};

export type DegreeEntry = { id: string; name: string; type: string; degree: number };

export function countByType(nodes: GraphNode[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const n of nodes) {
    const t = n.type || "unknown";
    counts[t] = (counts[t] ?? 0) + 1;
  }
  return counts;
}

/** Undirected adjacency for hop / component calculations. */
export function buildAdjacency(edges: GraphEdge[]): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>();
  const add = (a: string, b: string) => {
    if (!adj.has(a)) adj.set(a, new Set());
    if (!adj.has(b)) adj.set(b, new Set());
    adj.get(a)!.add(b);
    adj.get(b)!.add(a);
  };
  for (const e of edges) {
    if (e.source_node && e.target_node) add(e.source_node, e.target_node);
  }
  return adj;
}

export function largestConnectedComponentSize(
  nodeIds: string[],
  edges: GraphEdge[],
): number {
  if (!nodeIds.length) return 0;
  const adj = buildAdjacency(edges);
  const seen = new Set<string>();
  let best = 0;

  for (const start of nodeIds) {
    if (seen.has(start)) continue;
    const stack = [start];
    let size = 0;
    seen.add(start);
    while (stack.length) {
      const cur = stack.pop()!;
      size += 1;
      for (const next of adj.get(cur) ?? []) {
        if (!seen.has(next) && nodeIds.includes(next)) {
          seen.add(next);
          stack.push(next);
        }
      }
    }
    if (size > best) best = size;
  }
  return best;
}

export function computeClientStats(
  nodes: GraphNode[],
  edges: GraphEdge[],
): GraphStats {
  const byType = countByType(nodes);
  const files = byType.file ?? 0;
  const classes = byType.class ?? 0;
  const functions =
    (byType.function ?? 0) + (byType.method ?? 0) + (byType.nested_function ?? 0);
  const modules = byType.module ?? 0;
  const packages = byType.package ?? 0;

  const importRels = new Set(["FILE_IMPORTS_FILE", "MODULE_IMPORTS_MODULE"]);
  const dependencies = edges.filter((e) => importRels.has(e.relationship)).length;

  return {
    nodes: nodes.length,
    edges: edges.length,
    files,
    classes,
    functions,
    modules,
    packages,
    dependencies,
    largestComponent: largestConnectedComponentSize(
      nodes.map((n) => n.id),
      edges,
    ),
  };
}

export function nHopNeighborhood(
  rootId: string,
  edges: GraphEdge[],
  hops: number,
): Set<string> {
  const adj = buildAdjacency(edges);
  const result = new Set<string>([rootId]);
  let frontier = new Set<string>([rootId]);

  for (let h = 0; h < hops; h += 1) {
    const next = new Set<string>();
    for (const id of frontier) {
      for (const n of adj.get(id) ?? []) {
        if (!result.has(n)) {
          result.add(n);
          next.add(n);
        }
      }
    }
    frontier = next;
    if (!frontier.size) break;
  }
  return result;
}

export function connectedSet(rootId: string, edges: GraphEdge[]): Set<string> {
  const adj = buildAdjacency(edges);
  return new Set([rootId, ...(adj.get(rootId) ?? [])]);
}

export function filterNodesByGroups(
  nodes: GraphNode[],
  enabled: Set<FilterGroupKey>,
): GraphNode[] {
  const allowedTypes = new Set<string>();
  for (const g of FILTER_GROUPS) {
    if (enabled.has(g.key)) {
      for (const t of g.types) allowedTypes.add(t);
    }
  }
  return nodes.filter((n) => allowedTypes.has(n.type) || !n.type);
}

export function topDegreeNodes(
  nodes: GraphNode[],
  edges: GraphEdge[],
  options: { typeFilter?: string | string[]; limit?: number } = {},
): DegreeEntry[] {
  const { typeFilter, limit = 8 } = options;
  const types = typeFilter
    ? new Set(Array.isArray(typeFilter) ? typeFilter : [typeFilter])
    : null;
  const degree = new Map<string, number>();
  for (const e of edges) {
    degree.set(e.source_node, (degree.get(e.source_node) ?? 0) + 1);
    degree.set(e.target_node, (degree.get(e.target_node) ?? 0) + 1);
  }
  return nodes
    .filter((n) => !types || types.has(n.type))
    .map((n) => ({
      id: n.id,
      name: n.name,
      type: n.type,
      degree: degree.get(n.id) ?? 0,
    }))
    .filter((e) => e.degree > 0)
    .sort((a, b) => b.degree - a.degree || a.name.localeCompare(b.name))
    .slice(0, limit);
}

/** Most-imported: inbound import edges on file/module nodes. */
export function mostImported(
  nodes: GraphNode[],
  edges: GraphEdge[],
  limit = 8,
): DegreeEntry[] {
  const importRels = new Set(["FILE_IMPORTS_FILE", "MODULE_IMPORTS_MODULE"]);
  const inbound = new Map<string, number>();
  for (const e of edges) {
    if (!importRels.has(e.relationship)) continue;
    inbound.set(e.target_node, (inbound.get(e.target_node) ?? 0) + 1);
  }
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return [...inbound.entries()]
    .map(([id, degree]) => {
      const n = byId.get(id);
      return n
        ? { id, name: n.name, type: n.type, degree }
        : { id, name: id.slice(0, 8), type: "unknown", degree };
    })
    .filter((e) => e.type === "file" || e.type === "module")
    .sort((a, b) => b.degree - a.degree || a.name.localeCompare(b.name))
    .slice(0, limit);
}

export function searchNodes(nodes: GraphNode[], query: string): GraphNode[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return nodes
    .filter(
      (n) =>
        n.name.toLowerCase().includes(q) ||
        n.type.toLowerCase().includes(q) ||
        n.id.toLowerCase().includes(q),
    )
    .slice(0, 40);
}

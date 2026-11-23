"use client";

import * as React from "react";

import { SearchInput } from "@/components/search-input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { GraphEdge, GraphNode } from "@/types/domain";

import { buildAdjacency, nHopNeighborhood } from "@/features/graph/lib/graph-analytics";

type DependencyChainProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export function DependencyChainExplorer({ nodes, edges }: DependencyChainProps) {
  const [q, setQ] = React.useState("");
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  const fileNodes = React.useMemo(
    () => nodes.filter((n) => n.type === "file" || n.type === "module"),
    [nodes],
  );

  const matches = React.useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return fileNodes.slice(0, 12);
    return fileNodes
      .filter((n) => n.name.toLowerCase().includes(needle))
      .slice(0, 20);
  }, [fileNodes, q]);

  const selected = fileNodes.find((n) => n.id === selectedId) ?? null;

  const chain = React.useMemo(() => {
    if (!selectedId) return { hop1: [] as GraphNode[], hop2: [] as GraphNode[] };
    const hop1Ids = nHopNeighborhood(selectedId, edges, 1);
    hop1Ids.delete(selectedId);
    const hop2Ids = nHopNeighborhood(selectedId, edges, 2);
    for (const id of hop1Ids) hop2Ids.delete(id);
    hop2Ids.delete(selectedId);
    const byId = new Map(nodes.map((n) => [n.id, n]));
    return {
      hop1: [...hop1Ids].map((id) => byId.get(id)).filter(Boolean) as GraphNode[],
      hop2: [...hop2Ids].map((id) => byId.get(id)).filter(Boolean) as GraphNode[],
    };
  }, [selectedId, edges, nodes]);

  const adj = React.useMemo(() => buildAdjacency(edges), [edges]);
  const degree = selectedId ? adj.get(selectedId)?.size ?? 0 : 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Dependency Chain</CardTitle>
        <CardDescription>
          1–2 hop neighbors from GET /graph/full. Branch-diff chains need Surgeon API.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!nodes.length ? (
          <p className="text-sm text-muted-foreground">Build the repository graph first.</p>
        ) : (
          <>
            <SearchInput
              value={q}
              onChange={setQ}
              placeholder="Search file or module…"
            />
            <div className="flex flex-wrap gap-1.5">
              {matches.map((n) => (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => setSelectedId(n.id)}
                  className={`rounded-md border px-2 py-1 font-mono text-2xs ${
                    selectedId === n.id ? "border-primary bg-muted" : "hover:bg-muted/50"
                  }`}
                >
                  {n.name}
                </button>
              ))}
            </div>
            {selected ? (
              <div className="space-y-2 text-sm">
                <p>
                  <span className="font-mono text-xs font-semibold">{selected.name}</span>
                  <span className="ml-2 text-xs text-muted-foreground">
                    {selected.type} · degree {degree}
                  </span>
                </p>
                <HopList label="1-hop" nodes={chain.hop1} />
                <HopList label="2-hop" nodes={chain.hop2} />
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">Select a node to explore chains.</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function HopList({ label, nodes }: { label: string; nodes: GraphNode[] }) {
  return (
    <div>
      <h4 className="mb-1 text-2xs font-medium uppercase text-muted-foreground">
        {label} ({nodes.length})
      </h4>
      <ul className="max-h-28 space-y-0.5 overflow-auto">
        {nodes.slice(0, 40).map((n) => (
          <li key={n.id} className="font-mono text-2xs text-muted-foreground">
            {n.type}: {n.name}
          </li>
        ))}
        {!nodes.length ? <li className="text-xs text-muted-foreground">—</li> : null}
      </ul>
    </div>
  );
}

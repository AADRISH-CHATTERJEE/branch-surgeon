"use client";

import type { GraphEdge, GraphNode } from "@/types/domain";

import { RankedList } from "@/components/data-display/ranked-list";
import { Unavailable } from "@/components/feedback/unavailable";

import {
  mostImported,
  topDegreeNodes,
} from "../lib/graph-analytics";

type MetricsSidebarProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onSelectNode: (id: string) => void;
};

export function MetricsSidebar({ nodes, edges, onSelectNode }: MetricsSidebarProps) {
  const mostConnected = topDegreeNodes(nodes, edges, {
    typeFilter: "file",
    limit: 8,
  });
  const largestModules = topDegreeNodes(nodes, edges, {
    typeFilter: ["module", "package"],
    limit: 8,
  });
  const imported = mostImported(nodes, edges, 8);

  return (
    <div className="space-y-4 text-sm">
      <div>
        <h3 className="text-sm font-semibold">Metrics</h3>
        <p className="mt-0.5 text-2xs text-muted-foreground">
          Computed client-side from GET /graph/full degree counts. Engine hotspot APIs are not
          exposed on Local REST.
        </p>
      </div>

      <RankedList
        title="Most connected files"
        items={mostConnected.map((item) => ({
          id: item.id,
          label: item.name,
          value: item.degree,
        }))}
        empty="No file nodes with edges."
        onSelect={onSelectNode}
      />
      <RankedList
        title="Largest modules / packages"
        items={largestModules.map((item) => ({
          id: item.id,
          label: item.name,
          value: item.degree,
        }))}
        empty="No module/package connectivity."
        onSelect={onSelectNode}
      />
      <RankedList
        title="Most imported"
        items={imported.map((item) => ({
          id: item.id,
          label: item.name,
          value: item.degree,
        }))}
        empty="No import edges in persisted graph."
        onSelect={onSelectNode}
      />

      <Unavailable
        compact
        title="Potential hotspots"
        reason="RepositoryGraphService hotspot helpers are not exposed via Local API. Degree rankings above are the closest available signal."
      />
    </div>
  );
}

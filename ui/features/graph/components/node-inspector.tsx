"use client";

import { StatusBadge } from "@/components/data-display/status-badge";
import { ErrorState } from "@/components/feedback/error-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ApiError } from "@/services/errors";
import type { GraphEdge, GraphNode, GraphNodeDetail } from "@/types/domain";

import { nodeStyle } from "../lib/graph-styles";

type NodeInspectorProps = {
  selectedId: string | null;
  selectedNode: GraphNode | null;
  allNodes: GraphNode[];
  detail?: GraphNodeDetail;
  isLoading?: boolean;
  isError?: boolean;
  error?: unknown;
  onSelectNode?: (id: string) => void;
};

function resolveName(nodes: GraphNode[], id: string): string {
  return nodes.find((n) => n.id === id)?.name ?? id.slice(0, 8);
}

export function NodeInspector({
  selectedId,
  selectedNode,
  allNodes,
  detail,
  isLoading,
  isError,
  error,
  onSelectNode,
}: NodeInspectorProps) {
  if (!selectedId) {
    return (
      <p className="text-sm text-muted-foreground">
        Select a node to inspect connections from GET /graph/nodes/{"{id}"}.
      </p>
    );
  }

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading node…</p>;
  }

  if (isError) {
    return (
      <ErrorState
        title="Node not found"
        description={error instanceof ApiError ? error.message : undefined}
      />
    );
  }

  const node = detail ?? selectedNode;
  if (!node) return null;

  const style = nodeStyle(node.type);
  const outgoing = detail?.outgoing_edges ?? [];
  const incoming = detail?.incoming_edges ?? [];

  const imports = outgoing.filter((e) =>
    e.relationship.includes("IMPORTS"),
  );
  const importedBy = incoming.filter((e) =>
    e.relationship.includes("IMPORTS"),
  );

  const connectedFiles = collectConnectedFiles(allNodes, [...outgoing, ...incoming]);

  return (
    <ScrollArea className="h-full">
      <div className="space-y-4 pr-2 text-sm">
        <div>
          <p className="break-all font-mono text-xs font-semibold">{node.name}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <StatusBadge label={style.label} tone="info" />
            <StatusBadge label={node.type} tone="muted" />
          </div>
        </div>

        <section>
          <h4 className="mb-1 text-2xs font-medium uppercase text-muted-foreground">
            Path
          </h4>
          <p className="text-xs text-muted-foreground">
            Not persisted on GET /graph/full — engine has <code>file_path</code> but
            Local API node rows only expose name/type.
          </p>
        </section>

        <section>
          <h4 className="mb-1 text-2xs font-medium uppercase text-muted-foreground">
            Symbol count
          </h4>
          <p className="text-xs text-muted-foreground">Unavailable from current graph API.</p>
        </section>

        <EdgeList
          title={`Outgoing (${outgoing.length})`}
          edges={outgoing}
          allNodes={allNodes}
          direction="out"
          onSelectNode={onSelectNode}
        />
        <EdgeList
          title={`Incoming (${incoming.length})`}
          edges={incoming}
          allNodes={allNodes}
          direction="in"
          onSelectNode={onSelectNode}
        />

        <section>
          <h4 className="mb-1 text-2xs font-medium uppercase text-muted-foreground">
            Imports ({imports.length})
          </h4>
          <ul className="space-y-1">
            {imports.slice(0, 20).map((e) => (
              <li key={e.id}>
                <button
                  type="button"
                  className="font-mono text-2xs hover:underline"
                  onClick={() => onSelectNode?.(e.target_node)}
                >
                  {resolveName(allNodes, e.target_node)}
                </button>
              </li>
            ))}
            {!imports.length ? <li className="text-muted-foreground">—</li> : null}
          </ul>
        </section>

        <section>
          <h4 className="mb-1 text-2xs font-medium uppercase text-muted-foreground">
            Imported by ({importedBy.length})
          </h4>
          <ul className="space-y-1">
            {importedBy.slice(0, 20).map((e) => (
              <li key={e.id}>
                <button
                  type="button"
                  className="font-mono text-2xs hover:underline"
                  onClick={() => onSelectNode?.(e.source_node)}
                >
                  {resolveName(allNodes, e.source_node)}
                </button>
              </li>
            ))}
            {!importedBy.length ? <li className="text-muted-foreground">—</li> : null}
          </ul>
        </section>

        <section>
          <h4 className="mb-1 text-2xs font-medium uppercase text-muted-foreground">
            Connected files ({connectedFiles.length})
          </h4>
          <ul className="space-y-1">
            {connectedFiles.slice(0, 20).map((f) => (
              <li key={f.id}>
                <button
                  type="button"
                  className="font-mono text-2xs hover:underline"
                  onClick={() => onSelectNode?.(f.id)}
                >
                  {f.name}
                </button>
              </li>
            ))}
            {!connectedFiles.length ? (
              <li className="text-xs text-muted-foreground">No adjacent file nodes.</li>
            ) : null}
          </ul>
        </section>
      </div>
    </ScrollArea>
  );
}

function EdgeList({
  title,
  edges,
  allNodes,
  direction,
  onSelectNode,
}: {
  title: string;
  edges: GraphEdge[];
  allNodes: GraphNode[];
  direction: "in" | "out";
  onSelectNode?: (id: string) => void;
}) {
  return (
    <section>
      <h4 className="mb-1 text-2xs font-medium uppercase text-muted-foreground">
        {title}
      </h4>
      <ul className="space-y-1">
        {edges.slice(0, 30).map((e) => {
          const other = direction === "out" ? e.target_node : e.source_node;
          return (
            <li key={e.id} className="font-mono text-2xs">
              <span className="text-muted-foreground">{e.relationship}</span>{" "}
              <button
                type="button"
                className="hover:underline"
                onClick={() => onSelectNode?.(other)}
              >
                {direction === "out" ? "→" : "←"} {resolveName(allNodes, other)}
              </button>
            </li>
          );
        })}
        {!edges.length ? <li className="text-muted-foreground">—</li> : null}
      </ul>
    </section>
  );
}

function collectConnectedFiles(
  allNodes: GraphNode[],
  edges: GraphEdge[],
): GraphNode[] {
  const ids = new Set<string>();
  for (const e of edges) {
    ids.add(e.source_node);
    ids.add(e.target_node);
  }
  return allNodes.filter((n) => n.type === "file" && ids.has(n.id));
}

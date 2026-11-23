"use client";

import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { ErrorState } from "@/components/feedback/error-state";
import { ListSkeleton } from "@/components/feedback/loading-skeletons";
import { PageContainer } from "@/components/layout/page-container";
import { useAnimationsEnabled } from "@/components/motion/prefer-motion";
import { PageHeader } from "@/components/page-header";
import { SearchInput } from "@/components/search-input";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  useBuildGraph,
  useGraphFull,
  useGraphNode,
  useGraphSummary,
} from "@/queries/use-graph";
import { ApiError } from "@/services/errors";

import { GraphLegend } from "./components/graph-legend";
import { GraphStatsBar } from "./components/graph-stats-bar";
import {
  graphEdgeTypes,
  graphNodeTypes,
  type GraphNodeData,
} from "./components/graph-node";
import { MetricsSidebar } from "./components/metrics-sidebar";
import { NodeInspector } from "./components/node-inspector";
import {
  computeClientStats,
  connectedSet,
  filterNodesByGroups,
  nHopNeighborhood,
  searchNodes,
} from "./lib/graph-analytics";
import { layoutNodes, type LayoutMode } from "./lib/graph-layout";
import {
  EDGE_LEGEND,
  FILTER_GROUPS,
  edgeStyle,
  type FilterGroupKey,
} from "./lib/graph-styles";

type HopMode = "all" | "1" | "2";
type SideTab = "inspector" | "metrics";

const MAX_VISIBLE = 500;

function GraphWorkspace() {
  const searchParams = useSearchParams();
  const focusParam = searchParams.get("node") ?? searchParams.get("focus");
  const graph = useGraphFull();
  /** Summary can rebuild server-side — wait until full graph is available. */
  const summary = useGraphSummary(Boolean(graph.data));
  const build = useBuildGraph();
  const animationsOn = useAnimationsEnabled();
  const { fitView, setCenter, getNode } = useReactFlow();
  const motionMs = animationsOn ? 300 : 0;

  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [q, setQ] = React.useState("");
  const [layout, setLayout] = React.useState<LayoutMode>("hierarchical-tb");
  const [hopMode, setHopMode] = React.useState<HopMode>("all");
  const [sideTab, setSideTab] = React.useState<SideTab>("inspector");
  const [enabledGroups, setEnabledGroups] = React.useState<Set<FilterGroupKey>>(
    () => new Set(FILTER_GROUPS.map((g) => g.key)),
  );
  const [focusId, setFocusId] = React.useState<string | null>(null);

  const detail = useGraphNode(selectedId);

  const allNodes = React.useMemo(() => graph.data?.nodes ?? [], [graph.data?.nodes]);
  const allEdges = React.useMemo(() => graph.data?.edges ?? [], [graph.data?.edges]);

  const clientStats = React.useMemo(
    () => computeClientStats(allNodes, allEdges),
    [allNodes, allEdges],
  );

  // Merge summary statistics when available (from GET /graph)
  const displayStats = React.useMemo(() => {
    const s = summary.data?.statistics as Record<string, number> | null | undefined;
    if (!s) return clientStats;
    const fnCount =
      (s.functions ?? 0) + (s.methods ?? 0) + (s.nested_functions ?? 0);
    const depCount = (s.import_edges ?? 0) + (s.dependency_edges ?? 0);
    return {
      ...clientStats,
      files: s.files ?? clientStats.files,
      classes: s.classes ?? clientStats.classes,
      functions: fnCount || clientStats.functions,
      modules: s.modules ?? clientStats.modules,
      packages: s.packages ?? clientStats.packages,
      dependencies: depCount || clientStats.dependencies,
      nodes: s.total_nodes ?? clientStats.nodes,
      edges: s.total_edges ?? clientStats.edges,
    };
  }, [clientStats, summary.data]);

  const searchHits = React.useMemo(
    () => searchNodes(allNodes, q),
    [allNodes, q],
  );

  const visibleNodeIds = React.useMemo(() => {
    let nodes = filterNodesByGroups(allNodes, enabledGroups);

    if (hopMode !== "all" && selectedId) {
      const hops = hopMode === "1" ? 1 : 2;
      const neighborhood = nHopNeighborhood(selectedId, allEdges, hops);
      nodes = nodes.filter((n) => neighborhood.has(n.id));
    }

    if (q.trim() && !selectedId) {
      const hitIds = new Set(searchHits.map((n) => n.id));
      // When searching without selection, keep hits + their 1-hop for context
      if (hitIds.size && hitIds.size < 40) {
        const expanded = new Set<string>();
        for (const id of hitIds) {
          for (const n of nHopNeighborhood(id, allEdges, 1)) expanded.add(n);
        }
        nodes = nodes.filter((n) => expanded.has(n.id));
      } else {
        nodes = nodes.filter((n) => hitIds.has(n.id));
      }
    }

    const truncated = nodes.length > MAX_VISIBLE;
    if (truncated) nodes = nodes.slice(0, MAX_VISIBLE);
    return { nodes, truncated };
  }, [allNodes, allEdges, enabledGroups, hopMode, selectedId, q, searchHits]);

  const highlightIds = React.useMemo(() => {
    if (!selectedId) return new Set<string>();
    return connectedSet(selectedId, allEdges);
  }, [selectedId, allEdges]);

  const mapped = React.useMemo(() => {
    const show = visibleNodeIds.nodes;
    const ids = new Set(show.map((n) => n.id));
    const dimActive = Boolean(selectedId);

    const rfNodes: Node<GraphNodeData>[] = show.map((n) => ({
      id: n.id,
      type: "refactory",
      position: { x: 0, y: 0 },
      data: {
        label: n.name,
        type: n.type,
        selected: selectedId === n.id,
        highlighted: selectedId === n.id || focusId === n.id,
        dimmed: dimActive && !highlightIds.has(n.id),
      },
    }));

    const rfEdges: Edge[] = allEdges
      .filter((e) => ids.has(e.source_node) && ids.has(e.target_node))
      .slice(0, MAX_VISIBLE * 2)
      .map((e) => {
        const style = edgeStyle(e.relationship);
        const onPath =
          !selectedId ||
          (highlightIds.has(e.source_node) && highlightIds.has(e.target_node));
        return {
          id: e.id,
          source: e.source_node,
          target: e.target_node,
          label: style.label,
          animated:
            animationsOn &&
            Boolean(
              selectedId &&
                highlightIds.has(e.source_node) &&
                highlightIds.has(e.target_node),
            ),
          style: {
            stroke: style.stroke,
            strokeWidth: onPath && selectedId ? 2 : 1,
            opacity: selectedId && !onPath ? 0.12 : 0.85,
            strokeDasharray: style.dashed ? "4 3" : undefined,
          },
          labelStyle: { fontSize: 9, fill: "var(--muted-foreground)" },
        };
      });

    const laidOut = layoutNodes(rfNodes, rfEdges, layout);
    return {
      rfNodes: laidOut,
      rfEdges,
      truncated: visibleNodeIds.truncated,
    };
  }, [
    visibleNodeIds,
    allEdges,
    selectedId,
    focusId,
    highlightIds,
    layout,
    animationsOn,
  ]);

  const [nodes, setNodes, onNodesChange] = useNodesState(mapped.rfNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(mapped.rfEdges);

  React.useEffect(() => {
    setNodes(mapped.rfNodes);
    setEdges(mapped.rfEdges);
  }, [mapped, setNodes, setEdges]);

  /** Fit view only when structure filters/layout change — not on every selection restyle. */
  const structureKey = `${layout}|${hopMode}|${[...enabledGroups].sort().join(",")}|${mapped.rfNodes.length}`;
  React.useEffect(() => {
    const t = window.setTimeout(() => {
      void fitView({ padding: 0.15, duration: motionMs });
    }, 50);
    return () => window.clearTimeout(t);
  }, [structureKey, fitView, motionMs]);

  const centerOnNode = React.useCallback(
    (id: string) => {
      setSelectedId(id);
      setFocusId(id);
      setSideTab("inspector");
      requestAnimationFrame(() => {
        const node = getNode(id);
        if (node) {
          const x = node.position.x + 84;
          const y = node.position.y + 22;
          void setCenter(x, y, { zoom: 1.2, duration: animationsOn ? 400 : 0 });
        } else {
          void fitView({ padding: 0.2, duration: motionMs });
        }
      });
      window.setTimeout(() => setFocusId(null), animationsOn ? 1600 : 0);
    },
    [getNode, setCenter, fitView, animationsOn, motionMs],
  );

  const focusAppliedRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!focusParam || !allNodes.length) return;
    const needle = focusParam.replace(/\\/g, "/").toLowerCase();
    const match =
      allNodes.find((n) => n.id === focusParam) ??
      allNodes.find((n) => {
        const name = (n.name ?? "").replace(/\\/g, "/").toLowerCase();
        return name === needle || name.endsWith(`/${needle}`) || name.endsWith(needle);
      });
    if (!match || focusAppliedRef.current === match.id) return;
    focusAppliedRef.current = match.id;
    const id = match.id;
    const handle = window.requestAnimationFrame(() => centerOnNode(id));
    return () => window.cancelAnimationFrame(handle);
  }, [focusParam, allNodes, centerOnNode]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        void fitView({ padding: 0.15, duration: motionMs });
      }
      if (e.key === "Escape") {
        setSelectedId(null);
      }
      if (e.key === "/" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        document.getElementById("graph-search")?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fitView, motionMs]);

  const toggleGroup = (key: FilterGroupKey) => {
    setEnabledGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  if (graph.isLoading && !graph.data) {
    return (
      <PageContainer variant="wide" className="space-y-4">
        <PageHeader
          title="Repository Graph"
          description="Explore structure, imports, calls, and inheritance — Sourcegraph-style, local-first."
          actions={
            <Button size="sm" disabled={build.isPending} onClick={() => build.mutate(false)}>
              Build Graph
            </Button>
          }
        />
        <ListSkeleton rows={8} />
      </PageContainer>
    );
  }

  if (graph.isError) {
    return (
      <PageContainer variant="wide" className="space-y-6">
        <PageHeader
          title="Repository Graph"
          description="Interactive architecture explorer over GET /graph/full."
          actions={
            <Button size="sm" disabled={build.isPending} onClick={() => build.mutate(false)}>
              Build Graph
            </Button>
          }
        />
        <ErrorState
          title="Graph unavailable"
          description={graph.error instanceof ApiError ? graph.error.message : undefined}
          errors={graph.error instanceof ApiError ? graph.error.errors : undefined}
          onRetry={() => void graph.refetch()}
        />
      </PageContainer>
    );
  }

  if (!allNodes.length) {
    return (
      <PageContainer variant="wide" className="space-y-6">
        <PageHeader title="Repository Graph" description="No persisted nodes yet." />
        <EmptyState
          title="Empty graph"
          description="Build the graph so nodes and edges are persisted."
          actionLabel="Build Graph"
          onAction={() => build.mutate(false)}
        />
      </PageContainer>
    );
  }

  return (
    <PageContainer variant="wide" className="space-y-4">
      <PageHeader
        title="Repository Graph"
        description="Explore structure, imports, calls, and inheritance — Sourcegraph-style, local-first."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={build.isPending}
              onClick={() => build.mutate(true)}
            >
              Rebuild
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void fitView({ padding: 0.15 })}>
              Fit view
            </Button>
          </div>
        }
      />

      <GraphStatsBar stats={displayStats} fromSummary />

      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-end">
          <div className="w-full sm:max-w-xs">
            <Label htmlFor="graph-search" className="mb-1 text-xs">
              Search <Kbd className="ml-1">/</Kbd>
            </Label>
            <SearchInput
              id="graph-search"
              value={q}
              onChange={setQ}
              placeholder="File, class, function, module…"
            />
          </div>
          <div className="w-full sm:w-44">
            <Label className="mb-1 text-xs">Layout</Label>
            <Select value={layout} onValueChange={(v) => setLayout(v as LayoutMode)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="hierarchical-tb">Top → Bottom</SelectItem>
                <SelectItem value="hierarchical-lr">Left → Right</SelectItem>
                <SelectItem value="force">Force directed</SelectItem>
                <SelectItem value="grid">Grid</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="w-full sm:w-40">
            <Label className="mb-1 text-xs">Neighborhood</Label>
            <Select value={hopMode} onValueChange={(v) => setHopMode(v as HopMode)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Entire graph</SelectItem>
                <SelectItem value="1">1-hop neighbors</SelectItem>
                <SelectItem value="2">2-hop neighbors</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <p className="text-2xs text-muted-foreground">
          Shortcuts: <Kbd>F</Kbd> fit · <Kbd>Esc</Kbd> clear · <Kbd>/</Kbd> search
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {FILTER_GROUPS.map((g) => {
          const on = enabledGroups.has(g.key);
          return (
            <Button
              key={g.key}
              size="sm"
              variant={on ? "secondary" : "ghost"}
              onClick={() => toggleGroup(g.key)}
              className="h-7 text-xs"
            >
              {g.label}
            </Button>
          );
        })}
      </div>

      {q.trim() && searchHits.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {searchHits.slice(0, 12).map((hit) => (
            <Button
              key={hit.id}
              size="sm"
              variant="outline"
              className="h-7 font-mono text-2xs"
              onClick={() => centerOnNode(hit.id)}
            >
              {hit.type}: {hit.name}
            </Button>
          ))}
        </div>
      ) : null}

      {mapped.truncated ? (
        <p className="text-xs text-muted-foreground">
          Showing first {MAX_VISIBLE} nodes for performance. Use search, filters, or
          neighborhood mode to focus.
        </p>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="relative h-[min(72vh,680px)] overflow-hidden rounded-lg border">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={graphNodeTypes}
            edgeTypes={graphEdgeTypes}
            fitView
            minZoom={0.15}
            maxZoom={2}
            onNodeClick={(_, node) => {
              setSelectedId(node.id);
              setSideTab("inspector");
            }}
            onPaneClick={() => setSelectedId(null)}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={18} size={1} />
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
              nodeStrokeWidth={2}
              className="!bg-background"
            />
          </ReactFlow>
          <div className="pointer-events-none absolute bottom-3 left-3 max-w-[200px]">
            <div className="pointer-events-auto">
              <GraphLegend />
            </div>
          </div>
        </div>

        <div className="flex h-[min(72vh,680px)] flex-col rounded-lg border">
          <div className="flex border-b">
            <button
              type="button"
              className={`flex-1 px-3 py-2 text-xs font-medium ${
                sideTab === "inspector" ? "bg-muted" : "hover:bg-muted/40"
              }`}
              onClick={() => setSideTab("inspector")}
            >
              Inspector
            </button>
            <button
              type="button"
              className={`flex-1 px-3 py-2 text-xs font-medium ${
                sideTab === "metrics" ? "bg-muted" : "hover:bg-muted/40"
              }`}
              onClick={() => setSideTab("metrics")}
            >
              Metrics
            </button>
          </div>
          <div className="min-h-0 flex-1 p-3">
            {sideTab === "inspector" ? (
              <NodeInspector
                selectedId={selectedId}
                selectedNode={
                  allNodes.find((n) => n.id === selectedId) ?? null
                }
                allNodes={allNodes}
                detail={detail.data}
                isLoading={detail.isLoading}
                isError={detail.isError}
                error={detail.error}
                onSelectNode={centerOnNode}
              />
            ) : (
              <MetricsSidebar
                nodes={allNodes}
                edges={allEdges}
                onSelectNode={centerOnNode}
              />
            )}
          </div>
          <Separator />
          <div className="p-2 text-2xs text-muted-foreground">
            Edge styles: {EDGE_LEGEND.map((e) => e.label).join(" · ")}
          </div>
        </div>
      </div>
    </PageContainer>
  );
}

export function GraphView() {
  return (
    <ReactFlowProvider>
      <GraphWorkspace />
    </ReactFlowProvider>
  );
}

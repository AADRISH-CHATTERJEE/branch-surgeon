import dagre from "@dagrejs/dagre";
import type { Edge, Node } from "@xyflow/react";

export type LayoutMode = "hierarchical-tb" | "hierarchical-lr" | "force" | "grid";

const NODE_W = 168;
const NODE_H = 44;

export function layoutNodes(
  nodes: Node[],
  edges: Edge[],
  mode: LayoutMode,
): Node[] {
  if (!nodes.length) return nodes;

  if (mode === "hierarchical-tb" || mode === "hierarchical-lr") {
    return layoutDagre(nodes, edges, mode === "hierarchical-lr" ? "LR" : "TB");
  }
  if (mode === "force") {
    return layoutForce(nodes, edges);
  }
  return layoutGrid(nodes);
}

function layoutDagre(
  nodes: Node[],
  edges: Edge[],
  rankdir: "TB" | "LR",
): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir, nodesep: 36, ranksep: 64, marginx: 24, marginy: 24 });

  for (const n of nodes) {
    g.setNode(n.id, { width: NODE_W, height: NODE_H });
  }
  for (const e of edges) {
    if (g.hasNode(e.source) && g.hasNode(e.target)) {
      g.setEdge(e.source, e.target);
    }
  }

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    if (!pos) return n;
    return {
      ...n,
      position: {
        x: pos.x - NODE_W / 2,
        y: pos.y - NODE_H / 2,
      },
    };
  });
}

function layoutGrid(nodes: Node[]): Node[] {
  const cols = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
  return nodes.map((n, i) => ({
    ...n,
    position: {
      x: (i % cols) * (NODE_W + 40),
      y: Math.floor(i / cols) * (NODE_H + 36),
    },
  }));
}

/** Lightweight deterministic force-style layout (no simulation loop). */
function layoutForce(nodes: Node[], edges: Edge[]): Node[] {
  const n = nodes.length;
  if (n === 0) return nodes;

  const radius = Math.max(220, Math.sqrt(n) * 48);
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  const positions = nodes.map((_, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2;
    return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
  });

  // Pull connected nodes closer in a few relaxation passes
  for (let pass = 0; pass < 40; pass += 1) {
    for (const e of edges) {
      const si = index.get(e.source);
      const ti = index.get(e.target);
      if (si == null || ti == null) continue;
      const a = positions[si]!;
      const b = positions[ti]!;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.hypot(dx, dy) || 1;
      const target = 140;
      const f = ((dist - target) / dist) * 0.08;
      a.x += dx * f;
      a.y += dy * f;
      b.x -= dx * f;
      b.y -= dy * f;
    }
    // Mild repulsion
    for (let i = 0; i < n; i += 1) {
      for (let j = i + 1; j < n; j += 1) {
        const a = positions[i]!;
        const b = positions[j]!;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.hypot(dx, dy) || 1;
        if (dist > 220) continue;
        const f = ((220 - dist) / dist) * 0.02;
        a.x -= dx * f;
        a.y -= dy * f;
        b.x += dx * f;
        b.y += dy * f;
      }
    }
  }

  return nodes.map((node, i) => ({
    ...node,
    position: positions[i]!,
  }));
}

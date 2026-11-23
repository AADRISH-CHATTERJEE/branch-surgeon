"use client";

import dynamic from "next/dynamic";
import { Suspense } from "react";

import { ProgressiveFallback } from "@/components/feedback/progressive-fallback";

/**
 * Route entry that code-splits React Flow + dagre away from the shell and
 * Dashboard. The Graph page is the only consumer of this chunk.
 */
const GraphView = dynamic(
  () => import("./graph-view").then((m) => ({ default: m.GraphView })),
  {
    ssr: false,
    loading: () => (
      <ProgressiveFallback
        title="Repository Graph"
        description="Explore structure, imports, calls, and inheritance — Sourcegraph-style, local-first."
        wide
        metrics={false}
      />
    ),
  },
);

export function GraphRoute() {
  return (
    <Suspense
      fallback={
        <ProgressiveFallback
          title="Repository Graph"
          description="Explore structure, imports, calls, and inheritance — Sourcegraph-style, local-first."
          wide
          metrics={false}
        />
      }
    >
      <GraphView />
    </Suspense>
  );
}

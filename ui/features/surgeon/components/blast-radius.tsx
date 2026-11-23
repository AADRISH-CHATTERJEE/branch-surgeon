"use client";

import Link from "next/link";

import { RankedList } from "@/components/data-display/ranked-list";
import { StatusBadge } from "@/components/data-display/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { BranchSurgeonWorkspace } from "@/services/surgeon";

import { blastFocusFile, graphWorkspaceHref } from "../lib/graph-workspace-href";

type BlastRadiusProps = {
  blast?: BranchSurgeonWorkspace["blast_radius"] | null;
  loading?: boolean;
};

/** Blast surface from GET /branch-surgeon (graph-derived). */
export function BlastRadiusPanel({ blast, loading }: BlastRadiusProps) {
  const critical = blast?.critical_files ?? [];
  const connected = blast?.most_connected ?? [];
  const graphHref = graphWorkspaceHref(blastFocusFile(blast));

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">Blast Radius</CardTitle>
          <StatusBadge label="Graph-derived" tone="info" />
        </div>
        <CardDescription>
          Affected graph nodes and highly connected files from the Branch Surgeon workspace.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading blast radius…</p>
        ) : (
          <div className="space-y-3">
            <div className="grid gap-2 sm:grid-cols-3">
              <Stat label="Graph nodes" value={blast?.node_count ?? 0} />
              <Stat label="Graph edges" value={blast?.edge_count ?? 0} />
              <Stat label="Critical files" value={critical.length} />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <RankedList
                title="Critical files"
                items={critical.map((name, i) => ({
                  id: `${name}-${i}`,
                  label: name,
                  value: critical.length - i,
                  href: `/repository?file=${encodeURIComponent(name)}`,
                }))}
                empty="No critical files in graph snapshot."
              />
              <RankedList
                title="Most connected"
                items={connected.map((name, i) => ({
                  id: `c-${name}-${i}`,
                  label: name,
                  value: connected.length - i,
                  href: `/repository?file=${encodeURIComponent(name)}`,
                }))}
                empty="No connectivity data."
              />
            </div>
          </div>
        )}
        <Button asChild size="sm" className="w-full sm:w-auto">
          <Link href={graphHref}>Open Full Graph Workspace</Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border p-2">
      <p className="text-2xs uppercase text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold tabular-nums">{value}</p>
    </div>
  );
}

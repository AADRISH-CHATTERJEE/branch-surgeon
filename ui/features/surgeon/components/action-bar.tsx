"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { SURGEON_API_REASON } from "@/services/surgeon";

type ActionBarProps = {
  onRunReview: () => void;
  onGenerateRecs: () => void;
  onBuildGraph: () => void;
  reviewPending?: boolean;
  recsPending?: boolean;
  graphPending?: boolean;
  exportPayload: Record<string, unknown>;
  /** Graph Workspace href (preserves optional blast-radius focus). */
  graphWorkspaceHref?: string;
};

export function SurgeonActionBar({
  onRunReview,
  onGenerateRecs,
  onBuildGraph,
  reviewPending,
  recsPending,
  graphPending,
  exportPayload,
  graphWorkspaceHref = "/repository/graph",
}: ActionBarProps) {
  const router = useRouter();

  const exportReport = () => {
    const blob = new Blob([JSON.stringify(exportPayload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `refactory-surgeon-composed-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Exported composed workspace snapshot (not Surgeon engine report)");
  };

  return (
    <TooltipProvider>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={reviewPending} onClick={onRunReview}>
          Run Review
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={recsPending}
          onClick={onGenerateRecs}
        >
          Generate Recommendations
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={graphPending}
          onClick={onBuildGraph}
        >
          Run Graph
        </Button>
        <Button asChild size="sm" variant="outline">
          <Link href={graphWorkspaceHref}>Open Full Graph Workspace</Link>
        </Button>
        <Button size="sm" variant="outline" onClick={() => router.push("/transform")}>
          Preview Transform
        </Button>

        <Tooltip>
          <TooltipTrigger asChild>
            <span>
              <Button size="sm" variant="outline" disabled>
                Apply Safe Fixes
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">
            {SURGEON_API_REASON} No apply-safe-fixes endpoint. Use Transform after review.
          </TooltipContent>
        </Tooltip>

        <Button size="sm" variant="ghost" onClick={exportReport}>
          Export Report
        </Button>
      </div>
    </TooltipProvider>
  );
}

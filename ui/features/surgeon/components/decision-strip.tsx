"use client";

import * as React from "react";

import { MetricCard } from "@/components/data-display/metric-card";
import { RiskSummary } from "@/components/data-display/risk-summary";
import { StatusBadge } from "@/components/data-display/status-badge";
import { ErrorState } from "@/components/feedback/error-state";
import { Unavailable } from "@/components/feedback/unavailable";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatRelativeTime } from "@/lib/format";
import { ApiError } from "@/services/errors";
import { SURGEON_API_REASON } from "@/services/surgeon";
import type { PersistedReview } from "@/types/domain";

type HealthScores = {
  overall?: number;
  security?: number;
  architecture?: number;
  maintainability?: number;
  testing?: number;
};

type ReviewForMeter = Omit<PersistedReview, "confidence"> & {
  confidence?: number | null;
};

function resolveConfidence(review: ReviewForMeter | null | undefined): number | null {
  if (!review) return null;
  const c = review.confidence;
  if (typeof c !== "number" || Number.isNaN(c)) return null;
  return c;
}

export const SurgeonDecisionStrip = React.memo(function SurgeonDecisionStrip({
  healthError,
  healthScores,
  recCount,
  criticalCount,
  blockerCount,
  warningCount,
  ruleCount,
  rulesPending,
  onRunRules,
  latestReview,
  mergeConflictRisk,
}: {
  healthError: Error | null;
  healthScores: HealthScores | null;
  recCount: number | string;
  criticalCount: number;
  blockerCount: number | string;
  warningCount: number | string;
  ruleCount: number | null | undefined;
  rulesPending: boolean;
  onRunRules: () => void;
  latestReview: ReviewForMeter | null | undefined;
  mergeConflictRisk?: {
    level: string;
    score: number;
    reason: string;
  } | null;
}) {
  const confidence = resolveConfidence(latestReview);
  const confidencePct =
    confidence == null ? null : Math.min(100, Math.max(0, confidence * 100));
  const riskLevel = (mergeConflictRisk?.level || "low").toLowerCase();
  const riskTone =
    riskLevel === "high" ? "danger" : riskLevel === "medium" ? "warn" : "info";

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Impact Analysis</CardTitle>
          <CardDescription>From repository health + recommendations</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {healthError ? (
            <ErrorState
              title="Health unavailable"
              description={
                healthError instanceof ApiError ? healthError.message : undefined
              }
            />
          ) : (
            <RiskSummary
              scores={{
                overall: healthScores?.overall,
                security: healthScores?.security,
                architecture: healthScores?.architecture,
                maintainability: healthScores?.maintainability,
                testing: healthScores?.testing,
              }}
            />
          )}
          <div className="grid grid-cols-2 gap-2">
            <MetricCard
              label="Total Recommendations"
              value={recCount}
              hint="All persisted recommendations"
              compact
            />
            <MetricCard
              label="Critical Recommendations"
              value={criticalCount}
              hint="Pending critical recommendations only (open work)"
              variant="danger"
              compact
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Merge Risk</CardTitle>
          <CardDescription>From GET /branch-surgeon merge_conflict_risk</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {mergeConflictRisk ? (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge label={mergeConflictRisk.level} tone={riskTone} />
                <span className="text-sm tabular-nums text-muted-foreground">
                  score {mergeConflictRisk.score.toFixed(2)}
                </span>
              </div>
              <p className="text-sm text-muted-foreground">{mergeConflictRisk.reason}</p>
            </div>
          ) : (
            <Unavailable
              reason={`${SURGEON_API_REASON} Restart Local API to load merge_conflict_risk.`}
            />
          )}
          <div className="grid grid-cols-2 gap-2">
            <MetricCard
              label="Rule blockers"
              value={blockerCount}
              hint="From Branch Surgeon rules snapshot"
              variant={(typeof blockerCount === "number" ? blockerCount : 0) > 0 ? "danger" : "default"}
              compact
            />
            <MetricCard label="Rule warnings" value={warningCount} compact />
          </div>
          <Button size="sm" variant="outline" disabled={rulesPending} onClick={onRunRules}>
            Run Rule Check
          </Button>
          {ruleCount != null ? (
            <p className="text-xs text-muted-foreground">{ruleCount} company rules loaded</p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Confidence Meter</CardTitle>
          <CardDescription>Persisted review confidence when recorded</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {!latestReview ? (
            <Unavailable
              title="No review confidence"
              reason="Run a review (POST /review) or wait until reviews are persisted."
            />
          ) : confidencePct == null ? (
            <>
              <div className="flex items-end justify-between gap-2">
                <p className="text-lg font-medium text-muted-foreground">Not recorded</p>
                <StatusBadge label={latestReview.risk || "unknown"} />
              </div>
              <p className="text-xs text-muted-foreground">
                Confidence unavailable for this review ·{" "}
                {formatRelativeTime(latestReview.created_at)}
              </p>
            </>
          ) : (
            <>
              <div className="flex items-end justify-between gap-2">
                <p className="text-3xl font-semibold tabular-nums">
                  {confidencePct.toFixed(0)}%
                </p>
                <StatusBadge label={latestReview.risk || "unknown"} />
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${confidencePct}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                From latest persisted review · {formatRelativeTime(latestReview.created_at)}
              </p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
});

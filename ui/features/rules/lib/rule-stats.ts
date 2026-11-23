import type { RuleItem, RulesCheckResult } from "@/types/domain";

import type { DistributionItem } from "@/components/data-display/distribution-chart";

export function countByField(
  rules: RuleItem[],
  field: "category" | "severity",
): DistributionItem[] {
  const map = new Map<string, number>();
  for (const r of rules) {
    const key = (r[field] || "unknown").toLowerCase();
    map.set(key, (map.get(key) ?? 0) + 1);
  }
  return [...map.entries()]
    .map(([key, value]) => ({ key, label: key, value }))
    .sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
}

export function blockingDistribution(rules: RuleItem[]): DistributionItem[] {
  let blocking = 0;
  let advisory = 0;
  for (const r of rules) {
    if (r.blocking) blocking += 1;
    else advisory += 1;
  }
  return [
    {
      key: "blocking",
      label: "Blocking",
      value: blocking,
      color: "var(--chart-series-5)",
    },
    {
      key: "advisory",
      label: "Advisory",
      value: advisory,
      color: "var(--chart-series-1)",
    },
  ];
}

export function categoryBucketCounts(rules: RuleItem[]) {
  const buckets = {
    architecture: 0,
    security: 0,
    testing: 0,
    company: 0,
    other: 0,
  };
  for (const r of rules) {
    const c = (r.category || "").toLowerCase();
    if (
      c.includes("architecture") ||
      c.includes("module") ||
      c.includes("forbidden_path") ||
      c.includes("forbidden_import") ||
      c.includes("layer")
    ) {
      buckets.architecture += 1;
    } else if (
      c.includes("security") ||
      c.includes("secret") ||
      c.includes("license")
    ) {
      buckets.security += 1;
    } else if (c.includes("test") || c.includes("coverage")) {
      buckets.testing += 1;
    } else if (
      c.includes("branch") ||
      c.includes("commit") ||
      c.includes("pr_") ||
      c.includes("merge") ||
      c.includes("reviewer")
    ) {
      buckets.company += 1;
    } else {
      buckets.other += 1;
    }
  }
  return buckets;
}

export function outcomeTone(outcome?: string | null) {
  const o = (outcome || "").toUpperCase();
  if (o === "PASS") return "success" as const;
  if (o === "WARN" || o === "WARNING") return "warn" as const;
  if (o === "BLOCK" || o === "ERROR") return "danger" as const;
  return "muted" as const;
}

export function checkStatusDistribution(
  result: RulesCheckResult | null,
): DistributionItem[] {
  if (!result) return [];
  const pass =
    result.outcome?.toUpperCase() === "PASS" && !result.violations.length ? 1 : 0;
  return [
    {
      key: "pass",
      label: "PASS signal",
      value: pass || (result.outcome?.toUpperCase() === "PASS" ? 1 : 0),
      color: "var(--chart-series-2)",
    },
    {
      key: "warn",
      label: "Warnings",
      value: result.warning_count,
      color: "var(--chart-series-3)",
    },
    {
      key: "block",
      label: "Blockers",
      value: result.blocker_count,
      color: "var(--chart-series-5)",
    },
  ];
}

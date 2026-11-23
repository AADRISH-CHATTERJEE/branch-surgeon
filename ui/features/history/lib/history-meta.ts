import type { HistoryItem } from "@/types/domain";

export const ANALYSIS_TYPE_OPTIONS = [
  { value: "review", label: "Review" },
  { value: "recommendation", label: "Recommendation" },
  { value: "repository_health", label: "Repository Health" },
  { value: "repository_graph", label: "Repository Graph" },
  { value: "branch_surgeon", label: "Branch Surgeon" },
  { value: "rules_evaluation", label: "Rules Evaluation" },
  { value: "patch_generation", label: "Patch Generation" },
  { value: "patch_apply", label: "Patch Apply" },
  { value: "transform", label: "Transform" },
  { value: "index", label: "Index" },
  { value: "organization_admin", label: "Organization Admin" },
  { value: "organization_rule", label: "Organization Rule" },
] as const;

export function analysisTypeLabel(type: string): string {
  return (
    ANALYSIS_TYPE_OPTIONS.find((o) => o.value === type)?.label ||
    type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

export function deepLinkFor(item: HistoryItem): { href: string; label: string } | null {
  if (item.deep_link?.href) return item.deep_link;
  switch (item.analysis_type) {
    case "review":
      return { href: "/reviews", label: "Open Review" };
    case "recommendation":
    case "patch_generation":
    case "patch_apply":
      return { href: "/recommendations", label: "Open Recommendations" };
    case "branch_surgeon":
      return { href: "/surgeon", label: "Open Surgeon" };
    case "repository_graph":
      return { href: "/repository/graph", label: "Open Graph" };
    case "repository_health":
      return { href: "/repository/health", label: "Open Health" };
    case "rules_evaluation":
      return { href: "/rules", label: "Open Rules" };
    case "transform":
      return { href: "/transform", label: "Open Transform" };
    case "index":
      return { href: "/repository", label: "Open Repository" };
    case "organization_admin": {
      const org = item.organization_id || item.metadata?.organization_id;
      return {
        href: org ? `/organization?org=${org}` : "/organization",
        label: "Open Organization",
      };
    }
    case "organization_rule":
      return { href: "/rules", label: "Open Rules" };
    default:
      return null;
  }
}

export function statusTone(
  status: string,
): "success" | "warn" | "danger" | "info" | "muted" {
  const s = status.toLowerCase();
  if (["completed", "applied", "pass", "success", "ok"].includes(s)) return "success";
  if (["warn", "warning"].includes(s)) return "warn";
  if (["failed", "error", "block"].includes(s)) return "danger";
  return "muted";
}

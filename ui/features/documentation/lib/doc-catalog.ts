import type { CompanyDocumentation } from "@/types/domain";

/** API-backed document keys from GET /documentation */
export type ApiDocKey = keyof CompanyDocumentation;

/**
 * Virtual catalog for the Documentation Center.
 * Only four blobs are persisted by the Local API; remaining entries degrade honestly.
 */
export type DocEntry = {
  id: string;
  title: string;
  category: string;
  description: string;
  /** When set, content comes from GET /documentation[apiKey] */
  apiKey?: ApiDocKey;
  /** Soft gap — shown via Unavailable when selected */
  unavailableReason?: string;
  relatedDocIds: string[];
  relatedRoutes: { label: string; href: string }[];
};

export const DOC_CATALOG: DocEntry[] = [
  {
    id: "architecture",
    title: "Architecture",
    category: "Engineering",
    description: "System design and architecture guidelines",
    apiKey: "architecture",
    relatedDocIds: ["coding_guidelines", "security_guidelines", "testing_guidelines"],
    relatedRoutes: [
      { label: "Repository Graph", href: "/repository/graph" },
      { label: "Rules Center", href: "/rules" },
    ],
  },
  {
    id: "coding_guidelines",
    title: "Coding Standards",
    category: "Engineering",
    description: "Coding conventions and style",
    apiKey: "coding_guidelines",
    relatedDocIds: ["architecture", "testing_guidelines", "security_guidelines"],
    relatedRoutes: [
      { label: "Rules Center", href: "/rules" },
      { label: "Transform", href: "/transform" },
    ],
  },
  {
    id: "security_guidelines",
    title: "Security",
    category: "Engineering",
    description: "Security guidelines and practices",
    apiKey: "security_guidelines",
    relatedDocIds: ["architecture", "coding_guidelines", "company_policies"],
    relatedRoutes: [{ label: "Rules Center", href: "/rules" }],
  },
  {
    id: "testing_guidelines",
    title: "Testing",
    category: "Engineering",
    description: "Testing standards and coverage expectations",
    apiKey: "testing_guidelines",
    relatedDocIds: ["coding_guidelines", "architecture"],
    relatedRoutes: [
      { label: "Recommendations", href: "/recommendations" },
      { label: "Branch Surgeon", href: "/surgeon" },
    ],
  },
  {
    id: "company_policies",
    title: "Company Policies",
    category: "Policies",
    description: "Organization-wide engineering policies",
    unavailableReason:
      "Managed as Organization Rules (SQLite) in Rules Center — not Markdown on GET /documentation. Link rules to docs via documentation_url.",
    relatedDocIds: ["security_guidelines", "branching", "commits"],
    relatedRoutes: [
      { label: "Rules Center", href: "/rules" },
      { label: "Settings · Company Policies", href: "/settings?section=company" },
    ],
  },
  {
    id: "branching",
    title: "Branching",
    category: "Workflow",
    description: "Branch naming and merge policies",
    unavailableReason:
      "No dedicated branching Markdown on GET /documentation. Branch policy may appear under Rules → Company Standards.",
    relatedDocIds: ["commits", "development_workflow", "company_policies"],
    relatedRoutes: [
      { label: "Rules Center", href: "/rules" },
      { label: "Branch Surgeon", href: "/surgeon" },
    ],
  },
  {
    id: "commits",
    title: "Commits",
    category: "Workflow",
    description: "Commit message and history conventions",
    unavailableReason:
      "No dedicated commits Markdown on GET /documentation. Commit policy may appear under Rules → Company Standards.",
    relatedDocIds: ["branching", "development_workflow"],
    relatedRoutes: [{ label: "Rules Center", href: "/rules" }],
  },
  {
    id: "development_workflow",
    title: "Development Workflow",
    category: "Workflow",
    description: "Day-to-day engineering workflow",
    unavailableReason:
      "No dedicated workflow Markdown on GET /documentation. Use Architecture + Coding Standards when present.",
    relatedDocIds: ["architecture", "coding_guidelines", "branching"],
    relatedRoutes: [
      { label: "Activity", href: "/activity" },
      { label: "Branch Surgeon", href: "/surgeon" },
    ],
  },
];

export const DOC_CATEGORIES = ["Engineering", "Policies", "Workflow"] as const;

export function getDocEntry(id: string | null | undefined): DocEntry | undefined {
  if (!id) return undefined;
  return DOC_CATALOG.find((d) => d.id === id);
}

export function resolveDocContent(
  entry: DocEntry,
  data: CompanyDocumentation | undefined,
): string {
  if (!entry.apiKey || !data) return "";
  const direct = data[entry.apiKey];
  if (typeof direct === "string" && direct.trim()) return direct;
  // Defensive: tolerate accidental camelCase from proxies / older payloads.
  const camel = entry.apiKey.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());
  const alt = (data as Record<string, unknown>)[camel];
  return typeof alt === "string" ? alt : typeof direct === "string" ? direct : "";
}

export function firstAvailableDocId(data: CompanyDocumentation | undefined): string {
  for (const entry of DOC_CATALOG) {
    if (!entry.apiKey) continue;
    if (data?.[entry.apiKey]?.trim()) return entry.id;
  }
  return DOC_CATALOG[0]?.id ?? "architecture";
}

export function countLoadedDocs(data: CompanyDocumentation | undefined): number {
  if (!data) return 0;
  return (["architecture", "coding_guidelines", "security_guidelines", "testing_guidelines"] as const)
    .filter((k) => Boolean(data[k]?.trim())).length;
}

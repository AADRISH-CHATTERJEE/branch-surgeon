import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BookOpen,
  Building2,
  FolderGit2,
  History,
  ListChecks,
  Scale as ScaleIcon,
  Scissors,
  Settings,
  Sparkles,
  Wand2,
} from "lucide-react";

export type NavItem = {
  title: string;
  href: string;
  icon: LucideIcon;
  flagship?: boolean;
  children?: { title: string; href: string }[];
};

export const primaryNav: NavItem[] = [
  { title: "Branch Surgeon", href: "/surgeon", icon: Scissors, flagship: true },
  {
    title: "Organization",
    href: "/organization",
    icon: Building2,
    children: [
      { title: "Overview", href: "/organization" },
      { title: "Teams", href: "/organization/teams" },
      { title: "Members", href: "/organization/members" },
      { title: "Settings", href: "/organization/settings" },
    ],
  },
  {
    title: "Repository",
    href: "/repository",
    icon: FolderGit2,
    children: [
      { title: "Overview", href: "/repository" },
      { title: "Health", href: "/repository/health" },
      { title: "Graph", href: "/repository/graph" },
    ],
  },
  { title: "Reviews", href: "/reviews", icon: ListChecks },
  { title: "Recommendations", href: "/recommendations", icon: Sparkles },
  { title: "Transformations", href: "/transform", icon: Wand2 },
  { title: "Rules", href: "/rules", icon: ScaleIcon },
  { title: "History", href: "/history", icon: History },
  { title: "Activity", href: "/activity", icon: Activity },
  { title: "Documentation", href: "/documentation", icon: BookOpen },
];

export const secondaryNav: NavItem[] = [
  { title: "Settings", href: "/settings", icon: Settings },
];

/** Graph advanced workspace — reserved; not in Phase 10 nav. */
export const FUTURE_GRAPH_WORKSPACE = "/graph";

export function breadcrumbsForPath(pathname: string): { label: string; href?: string }[] {
  if (pathname === "/" || pathname === "/surgeon") {
    return [{ label: "Branch Surgeon" }];
  }

  const segments = pathname.split("/").filter(Boolean);
  const crumbs: { label: string; href?: string }[] = [];
  let acc = "";

  for (let i = 0; i < segments.length; i++) {
    acc += `/${segments[i]}`;
    const isLast = i === segments.length - 1;
    const label = formatSegment(segments[i]);
    crumbs.push(isLast ? { label } : { label, href: acc });
  }

  return crumbs;
}

function formatSegment(segment: string): string {
  const map: Record<string, string> = {
    surgeon: "Branch Surgeon",
    organization: "Organization",
    teams: "Teams",
    members: "Members",
    repository: "Repository",
    files: "Files",
    symbols: "Symbols",
    imports: "Imports",
    health: "Health",
    graph: "Graph",
    reviews: "Reviews",
    recommendations: "Recommendations",
    transform: "Transformations",
    rules: "Rules",
    activity: "Activity",
    history: "History",
    documentation: "Documentation",
    settings: "Settings",
  };
  return map[segment] ?? decodeURIComponent(segment);
}

export type SettingsSectionId =
  | "workspace"
  | "health"
  | "ai"
  | "company"
  | "appearance"
  | "notifications"
  | "developer"
  | "about"
  | "import-export"
  | "data";

export type SettingsNavItem = {
  id: SettingsSectionId;
  label: string;
  keywords: string[];
};

export const SETTINGS_NAV: SettingsNavItem[] = [
  {
    id: "workspace",
    label: "Workspace",
    keywords: ["api", "repository", "connection", "index", "reindex"],
  },
  {
    id: "health",
    label: "UI Health",
    keywords: [
      "version",
      "uptime",
      "provider",
      "model",
      "reachability",
      "frontend",
      "backend",
    ],
  },
  {
    id: "ai",
    label: "AI",
    keywords: ["provider", "model", "temperature", "tokens", "streaming", "prompt"],
  },
  {
    id: "company",
    label: "Company Policies",
    keywords: [
      "rules",
      "documentation",
      "architecture",
      "security",
      "testing",
      "policies",
      "organization",
      "company",
    ],
  },
  {
    id: "appearance",
    label: "Appearance",
    keywords: ["theme", "accent", "compact", "sidebar", "landing", "animations"],
  },
  {
    id: "notifications",
    label: "Notifications",
    keywords: ["toast", "desktop", "success", "warning", "error"],
  },
  {
    id: "developer",
    label: "Developer",
    keywords: ["debug", "cache", "inspector", "experimental", "diagnostics"],
  },
  {
    id: "about",
    label: "About",
    keywords: ["version", "build", "license", "github", "environment"],
  },
  {
    id: "data",
    label: "Data & History",
    keywords: ["history", "retention", "storage", "analyses", "purge"],
  },
  {
    id: "import-export",
    label: "Import / Export",
    keywords: ["backup", "reset", "preferences", "import", "export"],
  },
];

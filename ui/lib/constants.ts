export const APP_NAME = "Refactory";

export const STORAGE_KEYS = {
  apiBaseUrl: "refactory.apiBaseUrl",
  repoRoot: "refactory.repoRoot",
  organizationId: "refactory.organizationId",
  teamId: "refactory.teamId",
  sidebarCollapsed: "refactory.sidebarCollapsed",
  recommendationsView: "refactory.recommendationsView",
  reviewsView: "refactory.reviewsView",
  docsFavorites: "refactory.docsFavorites",
  docsRecent: "refactory.docsRecent",
  docsLastOpened: "refactory.docsLastOpened",
  docsNavCollapsed: "refactory.docsNavCollapsed",
  preferences: "refactory.preferences",
  recentRepos: "refactory.recentRepos",
} as const;

export const DEFAULT_API_URL = "http://127.0.0.1:8741";

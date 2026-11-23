/** Local API path constants. */

export const endpoints = {
  health: "/health",
  repository: "/repository",
  repositoryStatus: "/repository/status",
  repositoryHealth: "/repository/health",
  repositoryFiles: "/repository/files",
  repositoryFile: "/repository/file",
  repositorySymbols: "/repository/symbols",
  repositoryImports: "/repository/imports",
  branchSurgeon: "/branch-surgeon",
  graph: "/graph",
  graphFull: "/graph/full",
  graphNode: (id: string) => `/graph/nodes/${encodeURIComponent(id)}`,
  reviews: "/reviews",
  review: (id: string) => `/review/${encodeURIComponent(id)}`,
  createReview: "/review",
  reviewSuggestionStatus: (reviewId: string, suggestionId: string) =>
    `/reviews/${encodeURIComponent(reviewId)}/suggestions/${encodeURIComponent(suggestionId)}`,
  recommendations: "/recommendations",
  recommendationStats: "/recommendations/stats",
  recommend: "/recommend",
  recommendationItem: (id: string) =>
    `/recommendations/${encodeURIComponent(id)}`,
  resolveRecommendation: (id: string) =>
    `/recommendations/${encodeURIComponent(id)}/resolve`,
  ignoreRecommendation: (id: string) =>
    `/recommendations/${encodeURIComponent(id)}/ignore`,
  recommendationPatch: (id: string) =>
    `/recommendations/${encodeURIComponent(id)}/patch`,
  recommendationPatches: (id: string) =>
    `/recommendations/${encodeURIComponent(id)}/patches`,
  applyPatch: (patchId: string) =>
    `/patches/${encodeURIComponent(patchId)}/apply`,
  applyRecommendation: (id: string) =>
    `/recommendations/${encodeURIComponent(id)}/apply`,
  rollbackRecommendation: (id: string) =>
    `/recommendations/${encodeURIComponent(id)}/rollback`,
  transform: "/transform",
  transformPlan: "/transform/plan",
  transformApply: "/transform/apply",
  transformRollback: "/transform/rollback",
  transformRecent: "/transform/recent",
  transformItem: (id: string) => `/transform/${encodeURIComponent(id)}`,
  transformRollbackById: (id: string) =>
    `/transform/${encodeURIComponent(id)}/rollback`,

  rules: "/rules",
  rulesCheck: "/rules/check",
  organizationRules: "/organization-rules",
  organizationRule: (id: string) =>
    `/organization-rules/${encodeURIComponent(id)}`,
  organizationRuleDuplicate: (id: string) =>
    `/organization-rules/${encodeURIComponent(id)}/duplicate`,
  organizationRuleEnable: (id: string) =>
    `/organization-rules/${encodeURIComponent(id)}/enable`,
  organizationRuleDisable: (id: string) =>
    `/organization-rules/${encodeURIComponent(id)}/disable`,
  organizationRulesPreview: "/organization-rules/preview",
  organizationRulesExport: "/organization-rules/export",
  organizationRulesImport: "/organization-rules/import",
  organizationRulesAudit: "/organization-rules/audit",
  organizations: "/organizations",
  organizationRoles: "/organizations/roles",
  organization: (id: string) => `/organizations/${encodeURIComponent(id)}`,
  organizationDashboard: (id: string) =>
    `/organizations/${encodeURIComponent(id)}/dashboard`,
  organizationTeams: (id: string) =>
    `/organizations/${encodeURIComponent(id)}/teams`,
  organizationTeam: (orgId: string, teamId: string) =>
    `/organizations/${encodeURIComponent(orgId)}/teams/${encodeURIComponent(teamId)}`,
  organizationTeamMembers: (orgId: string, teamId: string) =>
    `/organizations/${encodeURIComponent(orgId)}/teams/${encodeURIComponent(teamId)}/members`,
  organizationTeamMember: (orgId: string, teamId: string, memberId: string) =>
    `/organizations/${encodeURIComponent(orgId)}/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(memberId)}`,
  organizationTeamRepositories: (orgId: string, teamId: string) =>
    `/organizations/${encodeURIComponent(orgId)}/teams/${encodeURIComponent(teamId)}/repositories`,
  organizationTeamRepository: (
    orgId: string,
    teamId: string,
    repositoryId: string,
  ) =>
    `/organizations/${encodeURIComponent(orgId)}/teams/${encodeURIComponent(teamId)}/repositories/${encodeURIComponent(repositoryId)}`,
  organizationMembers: (id: string) =>
    `/organizations/${encodeURIComponent(id)}/members`,
  organizationMember: (orgId: string, memberId: string) =>
    `/organizations/${encodeURIComponent(orgId)}/members/${encodeURIComponent(memberId)}`,
  organizationRepositories: (id: string) =>
    `/organizations/${encodeURIComponent(id)}/repositories`,
  organizationRepository: (orgId: string, repoId: string) =>
    `/organizations/${encodeURIComponent(orgId)}/repositories/${encodeURIComponent(repoId)}`,
  organizationMe: (id: string) =>
    `/organizations/${encodeURIComponent(id)}/me`,
  activity: "/activity",
  history: "/history",
  historyMetrics: "/history/metrics",
  historyExport: "/history/export",
  historyRetention: "/history/retention",
  historyItem: (id: string) => `/history/${encodeURIComponent(id)}`,
  documentation: "/documentation",
  index: "/index",
  indexStatus: "/index/status",
} as const;

/** Domain shapes returned by the Local API (presentation layer). */

export type HealthScores = {
  architecture: number;
  maintainability: number;
  security: number;
  performance: number;
  testing: number;
  documentation: number;
  technical_debt: number;
  overall: number;
};

export type HealthReport = {
  scores: HealthScores;
  trends: Record<string, number[]>;
  recommendations_count: number;
  critical_count: number;
};

export type PersistedRecommendation = {
  id: string;
  repository_id: string;
  type: string;
  priority: string;
  status: string;
  title: string;
  description: string;
  reasoning?: string;
  affected_files?: string[];
  impact?: string[];
  effort?: string;
  confidence?: number | null;
  resolution_notes?: string;
  verification_status?: string;
  patch_history?: unknown[];
  created_at: string | null;
  updated_at?: string | null;
  resolved_at?: string | null;
  ignored_at?: string | null;
  updated_by?: string | null;
};

/** GET /recommendations/stats — RecommendationStatsService summary. */
export type RecommendationRepositorySummary = {
  total: number;
  pending: number;
  applied?: number;
  resolved: number;
  ignored: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
  by_type?: Record<string, number>;
  by_status?: Record<string, number>;
  by_priority?: Record<string, number>;
  last_updated?: string | null;
  repository_id?: string;
  repository?: string;
  repo_root?: string;
  branch?: string;
  source?: string;
  version?: string;
};

export type RecommendationFilePatch = {
  file_path: string;
  original: string;
  modified: string;
};

/** POST /recommendations/{id}/patch response data */
export type RecommendationPatch = {
  id: string;
  recommendation_id: string;
  explanation: string;
  confidence: number;
  changed_files: string[];
  unified_diff: string;
  patches: RecommendationFilePatch[];
  prompt_version?: string;
  model?: string;
  provider?: string;
  created_at?: string | null;
  apply_available?: boolean;
  status?: string;
  applied_at?: string | null;
  applied_by?: string | null;
  git_commit?: string | null;
  failure_reason?: string | null;
  rollback_metadata?: Record<string, unknown> | null;
};

/** POST /recommendations/{id}/apply (or /patches/{id}/apply) response data */
export type PatchApplyResult = {
  status: "applied" | "conflict" | "failed" | "dry_run" | "rolled_back";
  applied: boolean;
  patch_id: string;
  recommendation_id: string;
  changed_files: string[];
  validation: {
    ok: boolean;
    checked_files: string[];
    errors: string[];
    rolled_back: boolean;
  };
  repository_updated: boolean;
  index_updated: boolean;
  graph_updated: boolean;
  message: string;
  details?: Record<string, unknown>;
  failure_reason?: string | null;
  failure_code?: string | null;
  git_commit?: string | null;
  applied_at?: string | null;
  applied_by?: string | null;
  recommendation_status?: string | null;
  recommendation?: PersistedRecommendation | null;
  dry_run?: boolean;
};

export type PersistedReview = {
  id: string;
  repository_id: string;
  pr_number: number | null;
  provider: string;
  model: string;
  risk: string;
  confidence: number;
  summary: string;
  created_at: string | null;
  /** Persisted suggestion stats (list + detail). Prefer over suggestions?.length. */
  suggestion_count?: number;
  file_count?: number;
  critical_count?: number;
  warning_count?: number;
  suggestions?: ReviewSuggestion[];
};

export type ReviewSuggestionStatus = "pending" | "resolved" | "ignored";

export type ReviewSuggestion = {
  id: string;
  review_id: string;
  file: string;
  line: number | null;
  severity: string;
  category: string;
  title: string;
  explanation: string;
  suggested_fix: string;
  confidence: number;
  estimated_impact: string;
  status?: ReviewSuggestionStatus | string;
  created_at?: string | null;
  updated_at?: string | null;
  resolved_at?: string | null;
  ignored_at?: string | null;
  updated_by?: string | null;
  recommendation_id?: string | null;
};

export type RepoFile = {
  id: string;
  repository_id?: string;
  path: string;
  language: string | null;
  sha256?: string | null;
  size?: number | null;
  last_indexed?: string | null;
};

/** GET /repository/file — working-tree text preview. */
export type RepoFileContent = {
  path: string;
  language: string;
  size: number | null;
  sha?: string | null;
  sha256?: string | null;
  content: string;
  truncated?: boolean;
  id?: string | null;
};

export type RepoSymbol = {
  id: string;
  file_id: string;
  name: string;
  type: string;
  line: number | null;
};

export type RepoImport = {
  id: string;
  file_id: string;
  module: string;
  symbol: string | null;
};

export type GraphNode = {
  id: string;
  repository_id?: string;
  name: string;
  type: string;
};

export type GraphEdge = {
  id: string;
  source_node: string;
  target_node: string;
  relationship: string;
};

export type GraphFull = {
  repository_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  node_count: number;
  edge_count: number;
};

export type GraphNodeDetail = GraphNode & {
  outgoing_edges: GraphEdge[];
  incoming_edges: GraphEdge[];
};

export type AnalysisRun = {
  id: string;
  repository_id: string;
  command: string;
  status: string;
  git_commit: string | null;
  branch?: string | null;
  duration_ms?: number | null;
  result_type?: string | null;
  result_data?: unknown;
  error_message?: string | null;
  created_at: string | null;
  metadata?: Record<string, unknown> | null;
};

/** GET /history item — analysis results memory (Phase 11.3) */
export type HistoryItem = {
  id: string;
  timestamp: string | null;
  analysis_type: string;
  repository_id: string;
  repository?: string;
  repository_name?: string;
  branch?: string | null;
  commit?: string | null;
  status: string;
  duration_ms?: number;
  summary?: string;
  created_by?: string;
  metadata?: Record<string, unknown> | null;
  result_data?: Record<string, unknown> | null;
  analysis_run_id?: string | null;
  organization_id?: string | null;
  created_by_user?: string | null;
  deep_link?: { href: string; label: string } | null;
};

export type HistoryMetrics = {
  total_analyses: number;
  today: number;
  this_week: number;
  average_duration_ms: number;
  failures: number;
  success_rate: number;
};

export type CompanyDocumentation = {
  architecture: string;
  coding_guidelines: string;
  security_guidelines: string;
  testing_guidelines: string;
};

export type RuleCondition = {
  field: string;
  operator: string;
  value?: string | number | string[] | null;
  pattern?: string;
};

export type RuleItem = {
  id?: string;
  name: string;
  category: string;
  severity: string;
  blocking: boolean;
  message: string;
  description?: string;
  enabled?: boolean;
  source?: "builtin" | "organization" | string;
  rule_type?: string;
  documentation_url?: string;
  conditions?: RuleCondition[];
  condition_logic?: "and" | "or" | string;
};

export type OrganizationRule = RuleItem & {
  id: string;
  source: "organization";
  created_at?: string | null;
  updated_at?: string | null;
};

export type RulesListData = {
  standards: Record<string, unknown>;
  rules: RuleItem[];
  builtin_rules?: RuleItem[];
  organization_rules?: OrganizationRule[];
  rule_count?: number;
  organization_rule_count?: number;
  rules_error?: string;
};

export type RuleViolation = {
  rule: string;
  message: string;
  severity: string;
  blocking: boolean;
  file_path: string;
  detail: string;
  source?: "builtin" | "organization" | string;
  documentation_url?: string;
};

export type RulesCheckResult = {
  outcome: string;
  violations: RuleViolation[];
  blocker_count: number;
  warning_count: number;
  summary: string;
  context?: Record<string, unknown>;
};

export type PlanOperation = {
  op: string;
  description?: string;
  target?: string;
  files?: string[];
};

export type TransformationPlanSummary = {
  id?: string;
  goal?: string;
  description?: string;
  operations?: PlanOperation[];
  dependencies?: string[];
  estimated_risk?: string;
  estimated_confidence?: number;
  affected_files?: string[];
  affected_symbols?: string[];
  steps?: Array<{ file_path?: string; description?: string; action?: string }>;
};

export type TransformPreview = {
  plan_id?: string;
  patch_id?: string;
  description?: string;
  goal?: string;
  operations?: PlanOperation[];
  files_modified?: string[];
  additions?: number;
  deletions?: number;
  modified_symbols?: string[];
  risk?: string;
  affected_modules?: string[];
  confidence?: number;
  estimated_review_time?: string;
  diff_preview?: string;
  rollback_available?: boolean;
  validation?: Record<string, unknown>;
  plan?: TransformationPlanSummary | null;
};

export type TransformResult = {
  id?: string;
  plan_id?: string;
  patch_id?: string;
  status?: string;
  files_modified?: string[];
  duration_ms?: number;
  rollback_available?: boolean;
  validation?: Record<string, unknown>;
};

export type TransformHistoryItem = {
  id: string;
  plan_id?: string;
  patch_id?: string;
  status?: string;
  transformation_type?: string;
  description?: string;
  target_file?: string;
  target_symbol?: string;
  files_modified?: string[];
  created_at?: string | null;
  duration_ms?: number;
  rolled_back?: boolean;
  rolled_back_at?: string | null;
  canRollback?: boolean;
  can_rollback?: boolean;
};

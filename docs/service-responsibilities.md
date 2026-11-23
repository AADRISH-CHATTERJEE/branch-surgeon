# Service Responsibilities

| Service | Responsibility | Does not |
|---------|----------------|----------|
| **GitService** | Detect repo, branch, remotes, local diffs | Call GitHub API |
| **GitHubService** | Fetch PR metadata when implemented | Index or embed code |
| **ParserService** | Tree-sitter parse → typed AST models | Persist index |
| **IndexerService** | Hash-aware repository index under `.refactory/` | Embeddings / AI |
| **RepositoryGraphService** | Build/query knowledge graph from index | I/O beyond caller data |
| **EmbeddingService** | Incremental vectors → `embeddings.json` | Semantic search |
| **RetrievalService** | Search / related files over persisted vectors | Regenerate embeddings |
| **PromptBuilder** | Assemble versioned review prompts | Call LLMs |
| **AIGateway** | Provider calls, retries, fallback, cost, optional cache | Prompt assembly |
| **ResponseParser** | Raw AI text → typed review models | Call AI |
| **ReviewEngine** | Orchestrate the review pipeline | Construct dependencies |
| **BackendClient** | Auth + download control-plane config | Upload source |
| **ConfigService** (backend) | Versioned prompts/workflows/settings catalog | Run reviews |

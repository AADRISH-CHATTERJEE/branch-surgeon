"use client";

import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { VirtualizedList } from "@/components/data-display/virtualized-list";
import { FilePreview } from "@/components/file-preview";
import { FilterBar } from "@/components/filter-bar";
import { SearchInput } from "@/components/search-input";
import { StatusBadge } from "@/components/data-display/status-badge";
import { EmptyState } from "@/components/feedback/empty-state";
import { ErrorState } from "@/components/feedback/error-state";
import { ListSkeleton, MetricSkeleton } from "@/components/feedback/loading-skeletons";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useRepository,
  useRepositoryFileContent,
  useRepositoryFiles,
  useRepositoryImports,
  useRepositoryStatus,
  useRepositorySymbols,
} from "@/queries/use-repository";
import { ApiError } from "@/services/errors";
import { shortSha } from "@/lib/format";
import type { RepoFile } from "@/types/domain";

export function RepositoryExplorer() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const fileParam = searchParams.get("file");
  const repo = useRepository();
  const status = useRepositoryStatus();
  const files = useRepositoryFiles({ limit: 5000 });
  const [q, setQ] = React.useState("");
  const [lang, setLang] = React.useState<string | null>(null);
  /** Local selection when URL has no ?file= yet (first paint / no deep link). */
  const [localSelectedId, setLocalSelectedId] = React.useState<string | null>(null);

  const deepLinkedId = React.useMemo(() => {
    if (!fileParam || !files.data?.length) return null;
    const needle = fileParam.replace(/\\/g, "/").toLowerCase();
    const match = files.data.find((f) => {
      const path = f.path.replace(/\\/g, "/").toLowerCase();
      return path === needle || path.endsWith(`/${needle}`) || path.endsWith(needle);
    });
    return match?.id ?? null;
  }, [fileParam, files.data]);

  const languages = React.useMemo(() => {
    const set = new Set<string>();
    for (const f of files.data ?? []) {
      if (f.language) set.add(f.language);
    }
    return [...set].sort().map((v) => ({ value: v, label: v }));
  }, [files.data]);

  const filtered = React.useMemo(() => {
    return (files.data ?? []).filter((f) => {
      if (lang && f.language !== lang) return false;
      if (q && !f.path.toLowerCase().includes(q.toLowerCase())) return false;
      return true;
    });
  }, [files.data, lang, q]);

  // URL is source of truth when ?file= is present; otherwise local / first file.
  const selectedId =
    (fileParam ? deepLinkedId : null) ??
    localSelectedId ??
    filtered[0]?.id ??
    null;

  const selected = filtered.find((f) => f.id === selectedId) ?? null;
  const activeId = selected?.id ?? null;
  const selectedIndex = React.useMemo(
    () => (activeId ? filtered.findIndex((f) => f.id === activeId) : -1),
    [filtered, activeId],
  );

  const selectFile = React.useCallback(
    (file: RepoFile) => {
      setLocalSelectedId(file.id);
      const params = new URLSearchParams(searchParams.toString());
      params.set("file", file.path);
      router.replace(`/repository?${params.toString()}`, { scroll: false });
    },
    [router, searchParams],
  );

  const symbols = useRepositorySymbols({
    file_id: activeId ?? undefined,
    enabled: Boolean(activeId),
  });
  const imports = useRepositoryImports({
    file_id: activeId ?? undefined,
    enabled: Boolean(activeId),
  });
  const fileContent = useRepositoryFileContent({
    path: selected?.path ?? null,
    enabled: Boolean(selected?.path),
  });

  const contentErrorMessage = React.useMemo(() => {
    if (!fileContent.isError) return null;
    const err = fileContent.error;
    if (!(err instanceof ApiError)) return "Unable to load file.";
    if (err.status === 404) return "File not found.";
    if (err.status === 415) return "Binary file cannot be previewed.";
    if (err.status === 413) return "File too large.";
    return err.message || "Unable to load file.";
  }, [fileContent.isError, fileContent.error]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!filtered.length) return;
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      e.preventDefault();
      const cur = selectedIndex < 0 ? 0 : selectedIndex;
      const next =
        e.key === "ArrowDown"
          ? Math.min(filtered.length - 1, cur + 1)
          : Math.max(0, cur - 1);
      selectFile(filtered[next]!);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [filtered, selectedIndex, selectFile]);

  return (
    <PageContainer className="space-y-6">
      <PageHeader
        title="Repository"
        description="Indexed files, symbols, and imports from the Local API."
      />

      <div className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 text-sm">
        {repo.isLoading && !repo.data ? (
          Array.from({ length: 6 }).map((_, i) => <MetricSkeleton key={i} />)
        ) : repo.isError ? (
          <div className="sm:col-span-2 lg:col-span-3 xl:col-span-6">
            <ErrorState
              title="Invalid repository root"
              description={
                repo.error instanceof ApiError
                  ? repo.error.message
                  : "Unable to load repository metadata for the configured root."
              }
              errors={repo.error instanceof ApiError ? repo.error.errors : undefined}
              onRetry={() => void repo.refetch()}
            />
          </div>
        ) : (
          <>
            <Meta label="Repository" value={repo.data?.name} />
            <Meta label="Root" value={repo.data?.root ?? repo.data?.root_path} mono />
            <Meta label="Branch" value={repo.data?.branch ?? repo.data?.current_branch} />
            <Meta label="HEAD" value={shortSha(repo.data?.head ?? repo.data?.head_sha)} mono />
            <Meta
              label="Status"
              value={
                repo.data?.working_tree ??
                (repo.data?.is_dirty ? "dirty" : "clean")
              }
            />
            <Meta label="Remote" value={repo.data?.remote ?? repo.data?.remote_url ?? "—"} mono />
          </>
        )}
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <SearchInput
            className="sm:max-w-xs"
            value={q}
            onChange={setQ}
            placeholder="Search files…"
          />
          <FilterBar options={languages} value={lang} onChange={setLang} allLabel="All languages" />
        </div>
        <p className="text-xs text-muted-foreground">
          Indexed files: {files.data?.length ?? 0}
          {filtered.length !== (files.data?.length ?? 0)
            ? ` · showing ${filtered.length}`
            : ""}
        </p>
      </div>

      {files.isLoading && !files.data ? (
        <ListSkeleton rows={8} />
      ) : files.isError ? (
        <ErrorState
          title="Could not load files"
          description={files.error instanceof ApiError ? files.error.message : undefined}
          errors={files.error instanceof ApiError ? files.error.errors : undefined}
          onRetry={() => void files.refetch()}
        />
      ) : !filtered.length ? (
        <EmptyState
          title="No indexed files"
          description="Run Index on Branch Surgeon (or POST /index), then return here. GET /repository/files should list paths for the selected repository."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <div className="space-y-2">
            <h2 className="text-sm font-medium">Indexed file list</h2>
            <VirtualizedList
              items={filtered}
              getItemKey={(f) => f.id}
              scrollToIndex={selectedIndex >= 0 ? selectedIndex : null}
              renderItem={(f) => (
                <button
                  type="button"
                  onClick={() => selectFile(f)}
                  className={`flex h-full min-h-9 w-full items-center justify-between gap-2 px-3 text-left text-sm hover:bg-muted/50 ${
                    activeId === f.id ? "bg-muted" : ""
                  }`}
                >
                  <span className="truncate font-mono text-xs">{f.path}</span>
                  {f.language ? <StatusBadge label={f.language} tone="muted" /> : null}
                </button>
              )}
            />
          </div>

          <div className="space-y-3">
            <FilePreview
              file={
                selected
                  ? {
                      id: selected.id,
                      path: selected.path,
                      language:
                        fileContent.data?.language ?? selected.language,
                      size: fileContent.data?.size ?? selected.size,
                      sha256:
                        fileContent.data?.sha256 ??
                        fileContent.data?.sha ??
                        selected.sha256,
                    }
                  : null
              }
              content={fileContent.data?.content}
              language={fileContent.data?.language ?? selected?.language}
              isLoading={
                fileContent.isPending ||
                (fileContent.isFetching && fileContent.data == null)
              }
              errorMessage={contentErrorMessage}
            />
            <Tabs defaultValue="symbols">
              <TabsList>
                <TabsTrigger value="symbols">Symbols</TabsTrigger>
                <TabsTrigger value="imports">Imports</TabsTrigger>
              </TabsList>
              <TabsContent value="symbols" className="rounded-lg border p-2">
                {symbols.isLoading ? (
                  <ListSkeleton rows={4} />
                ) : !(symbols.data ?? []).length ? (
                  <p className="p-3 text-sm text-muted-foreground">No symbols for this file.</p>
                ) : (
                  <ul className="max-h-56 space-y-1 overflow-auto text-sm">
                    {(symbols.data ?? []).map((s) => (
                      <li key={s.id} className="flex justify-between gap-2 px-2 py-1 font-mono text-xs">
                        <span>{s.name}</span>
                        <span className="text-muted-foreground">
                          {s.type}
                          {s.line != null ? `:${s.line}` : ""}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </TabsContent>
              <TabsContent value="imports" className="rounded-lg border p-2">
                {imports.isLoading ? (
                  <ListSkeleton rows={4} />
                ) : !(imports.data ?? []).length ? (
                  <p className="p-3 text-sm text-muted-foreground">No imports for this file.</p>
                ) : (
                  <ul className="max-h-56 space-y-1 overflow-auto text-sm">
                    {(imports.data ?? []).map((i) => (
                      <li key={i.id} className="px-2 py-1 font-mono text-xs">
                        {i.module}
                        {i.symbol ? ` · ${i.symbol}` : ""}
                      </li>
                    ))}
                  </ul>
                )}
              </TabsContent>
            </Tabs>
          </div>
        </div>
      )}
    </PageContainer>
  );
}

function Meta({
  label,
  value,
  mono,
}: {
  label: string;
  value?: string | null;
  mono?: boolean;
}) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={mono ? "font-mono text-xs" : "font-medium"}>{value || "—"}</p>
    </div>
  );
}

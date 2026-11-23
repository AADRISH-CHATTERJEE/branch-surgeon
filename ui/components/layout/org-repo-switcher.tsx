"use client";

import { Building2, Check, ChevronsUpDown, FolderGit2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useOrgContext } from "@/providers/org-context";
import { useRepoContext } from "@/providers/repo-context";
import { useRepository } from "@/queries/use-repository";
import { cn } from "@/lib/utils";

function normalizePath(path: string | null | undefined) {
  return (path || "").replace(/\\/g, "/").toLowerCase();
}

export function OrgRepoSwitcher() {
  const { organization, organizations, setOrganizationId, repositories, selectRepository } =
    useOrgContext();
  const { repoRoot } = useRepoContext();
  const repo = useRepository();
  const activeRoot = normalizePath(repoRoot);
  const matchedRepo = repositories.find(
    (r) => normalizePath(r.repository_root_path) === activeRoot,
  );
  const repoLabel =
    repo.data?.name ??
    matchedRepo?.repository_name ??
    (repoRoot ? repoRoot.split(/[/\\]/).pop() : "Repository");
  const branchLabel = repo.data?.branch ?? repo.data?.current_branch;
  const statusLabel =
    repo.data?.working_tree ?? (repo.data?.is_dirty ? "dirty" : repo.data ? "clean" : null);

  return (
    <div className="hidden items-center gap-1 md:flex">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className="max-w-[10rem] gap-1.5"
            aria-label="Switch organization"
          >
            <Building2 className="size-3.5 shrink-0" />
            <span className="truncate">{organization?.name ?? "Organization"}</span>
            <ChevronsUpDown className="size-3.5 shrink-0 opacity-60" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-64">
          <DropdownMenuLabel>Organization</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {organizations.map((org) => (
            <DropdownMenuItem
              key={org.id}
              onClick={() => setOrganizationId(org.id)}
              className="gap-2"
            >
              <Check
                className={cn(
                  "size-3.5",
                  org.id === organization?.id ? "opacity-100" : "opacity-0",
                )}
              />
              <span className="truncate">{org.name}</span>
            </DropdownMenuItem>
          ))}
          {!organizations.length ? (
            <DropdownMenuItem disabled>No organizations yet</DropdownMenuItem>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className="max-w-[16rem] gap-1.5"
            aria-label="Switch repository"
          >
            <FolderGit2 className="size-3.5 shrink-0" />
            <span className="min-w-0 truncate">
              <span className="font-medium">{repoLabel}</span>
              {branchLabel ? (
                <span className="text-muted-foreground"> · {branchLabel}</span>
              ) : null}
              {statusLabel ? (
                <span className="text-muted-foreground"> · {statusLabel}</span>
              ) : null}
            </span>
            <ChevronsUpDown className="size-3.5 shrink-0 opacity-60" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-80">
          <DropdownMenuLabel>Repositories</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {repositories.map((repo) => {
            const active = normalizePath(repo.repository_root_path) === activeRoot;
            return (
              <DropdownMenuItem
                key={repo.id}
                onClick={() => selectRepository(repo.repository_root_path)}
                className="flex-col items-start gap-0.5"
              >
                <span className="flex w-full items-center gap-2">
                  <Check className={cn("size-3.5", active ? "opacity-100" : "opacity-0")} />
                  <span className="truncate font-medium">{repo.repository_name}</span>
                </span>
                <span className="w-full truncate pl-5 font-mono text-2xs text-muted-foreground">
                  {repo.repository_root_path}
                </span>
              </DropdownMenuItem>
            );
          })}
          {!repositories.length ? (
            <DropdownMenuItem disabled>
              Link a repository under Organization → Repositories
            </DropdownMenuItem>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

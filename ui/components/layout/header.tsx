"use client";

import { Search, UserRound } from "lucide-react";

import { AppBreadcrumbs } from "@/components/layout/app-breadcrumbs";
import { MobileNav } from "@/components/layout/mobile-nav";
import { OrgRepoSwitcher } from "@/components/layout/org-repo-switcher";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Kbd, KbdGroup } from "@/components/ui/kbd";
import { useCommandPalette } from "@/features/command-palette/command-palette";
import { useRepoContext } from "@/providers/repo-context";

export function Header() {
  const { open } = useCommandPalette();
  const { repoRoot, apiBaseUrl } = useRepoContext();

  return (
    <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center gap-2 border-b bg-background px-3 sm:gap-3 sm:px-4">
      <MobileNav />

      <OrgRepoSwitcher />

      <div className="min-w-0 flex-1">
        <AppBreadcrumbs />
      </div>

      <button
        type="button"
        onClick={open}
        aria-label="Open command palette"
        className="hidden items-center gap-2 rounded-md border bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:flex"
      >
        <span>Search or jump to…</span>
        <KbdGroup>
          <Kbd>⌘</Kbd>
          <Kbd>K</Kbd>
        </KbdGroup>
      </button>

      <Button
        variant="outline"
        size="icon-sm"
        className="sm:hidden"
        aria-label="Open command palette"
        onClick={open}
      >
        <Search className="size-4" />
      </Button>

      <ThemeToggle />

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label="Workspace menu">
            <UserRound className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          <DropdownMenuLabel>Local workspace</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem disabled className="flex-col items-start gap-0.5 opacity-100">
            <span className="text-xs text-muted-foreground">API</span>
            <span className="truncate font-mono text-xs">{apiBaseUrl}</span>
          </DropdownMenuItem>
          <DropdownMenuItem disabled className="flex-col items-start gap-0.5 opacity-100">
            <span className="text-xs text-muted-foreground">Repo root</span>
            <span className="truncate font-mono text-xs">{repoRoot || "(process default)"}</span>
          </DropdownMenuItem>
          <DropdownMenuItem disabled className="flex-col items-start gap-0.5 opacity-100">
            <span className="text-xs text-muted-foreground">Tip</span>
            <span className="text-xs text-muted-foreground">
              Link any local Git clone under Organization → Repositories. No GitHub OAuth.
            </span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}

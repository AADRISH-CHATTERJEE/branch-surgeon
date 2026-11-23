"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronLeft, ChevronRight, Network } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { StatusBadge } from "@/components/data-display/status-badge";
import { APP_NAME } from "@/lib/constants";
import { primaryNav, secondaryNav } from "@/lib/navigation";
import { cn } from "@/lib/utils";
import { useNavPrefetch } from "@/hooks/use-nav-prefetch";
import { useApiHealth } from "@/queries/use-health";
import { useRepoContext } from "@/providers/repo-context";

export function Sidebar() {
  const pathname = usePathname();
  const { sidebarCollapsed, setSidebarCollapsed } = useRepoContext();
  const health = useApiHealth();
  const prefetch = useNavPrefetch();

  return (
    <aside
      aria-label="Primary navigation"
      className={cn(
        "flex h-full flex-col border-r bg-sidebar text-sidebar-foreground transition-[width] motion-reduce:transition-none",
        sidebarCollapsed ? "w-14" : "w-60",
      )}
    >
      <div className="flex h-12 items-center gap-2 border-b px-3">
        <Network className="size-4 shrink-0" />
        {!sidebarCollapsed ? (
          <span className="truncate text-sm font-semibold tracking-tight">{APP_NAME}</span>
        ) : null}
        <Button
          variant="ghost"
          size="icon-sm"
          className="ml-auto"
          aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
        >
          {sidebarCollapsed ? <ChevronRight className="size-4" /> : <ChevronLeft className="size-4" />}
        </Button>
      </div>

      <ScrollArea className="flex-1 px-2 py-3">
        <nav className="space-y-1">
          {primaryNav.map((item) => {
            const active =
              pathname === item.href ||
              (item.href !== "/surgeon" && pathname.startsWith(`${item.href}/`)) ||
              (item.href === "/repository" && pathname.startsWith("/repository"));
            const Icon = item.icon;
            return (
              <div key={item.href}>
                <Link
                  href={item.href}
                  title={item.title}
                  aria-current={active ? "page" : undefined}
                  onMouseEnter={() => prefetch(item.href)}
                  onFocus={() => prefetch(item.href)}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active
                      ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                      : "text-sidebar-foreground/80 hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground",
                    item.flagship && !active && "text-foreground",
                  )}
                >
                  <Icon className="size-4 shrink-0" />
                  {!sidebarCollapsed ? (
                    <>
                      <span className="truncate">{item.title}</span>
                      {item.flagship ? (
                        <span className="ml-auto text-2xs tracking-wide text-muted-foreground uppercase">
                          Flagship
                        </span>
                      ) : null}
                    </>
                  ) : null}
                </Link>
                {!sidebarCollapsed && item.children && active ? (
                  <div className="mt-0.5 mb-1 ml-6 space-y-0.5 border-l pl-2">
                    {item.children.map((child) => {
                      const childActive = pathname === child.href;
                      return (
                        <Link
                          key={child.href}
                          href={child.href}
                          aria-current={childActive ? "page" : undefined}
                          onMouseEnter={() => prefetch(child.href)}
                          onFocus={() => prefetch(child.href)}
                          className={cn(
                            "block rounded-md px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                            childActive
                              ? "bg-sidebar-accent font-medium"
                              : "text-muted-foreground hover:text-foreground",
                          )}
                        >
                          {child.title}
                        </Link>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            );
          })}
        </nav>
      </ScrollArea>

      <div className="space-y-2 border-t p-2">
        {secondaryNav.map((item) => {
          const Icon = item.icon;
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              title={item.title}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                active ? "bg-sidebar-accent font-medium" : "text-muted-foreground hover:bg-muted",
              )}
            >
              <Icon className="size-4 shrink-0" />
              {!sidebarCollapsed ? <span>{item.title}</span> : null}
            </Link>
          );
        })}
        {!sidebarCollapsed ? (
          <>
            <Separator />
            <div className="flex items-center justify-between px-1 py-1 text-xs">
              <span className="text-muted-foreground">API</span>
              <StatusBadge
                label={health.isSuccess ? "local" : health.isLoading ? "…" : "offline"}
                tone={health.isSuccess ? "success" : health.isLoading ? "muted" : "danger"}
              />
            </div>
          </>
        ) : null}
      </div>
    </aside>
  );
}

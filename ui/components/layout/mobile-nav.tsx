"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, Network } from "lucide-react";

import { StatusBadge } from "@/components/data-display/status-badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { ScrollArea } from "@/components/ui/scroll-area";
import { APP_NAME } from "@/lib/constants";
import { primaryNav, secondaryNav } from "@/lib/navigation";
import { cn } from "@/lib/utils";
import { useNavPrefetch } from "@/hooks/use-nav-prefetch";
import { useApiHealth } from "@/queries/use-health";

export function MobileNav() {
  const [open, setOpen] = React.useState(false);
  const pathname = usePathname();
  const health = useApiHealth();
  const prefetch = useNavPrefetch();

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          className="md:hidden"
          aria-label="Open navigation"
          aria-expanded={open}
          aria-controls="mobile-nav-panel"
        >
          <Menu className="size-4" />
        </Button>
      </SheetTrigger>
      <SheetContent
        id="mobile-nav-panel"
        side="left"
        className="w-[min(100%,20rem)] p-0"
        showCloseButton
      >
        <SheetHeader className="border-b px-4 py-3 text-left">
          <SheetTitle className="flex items-center gap-2 text-sm">
            <Network className="size-4" aria-hidden />
            {APP_NAME}
          </SheetTitle>
          <SheetDescription className="sr-only">Primary navigation</SheetDescription>
        </SheetHeader>
        <ScrollArea className="h-[calc(100svh-5.5rem)] px-2 py-3">
          <nav className="space-y-1" aria-label="Mobile primary">
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
                    aria-current={active ? "page" : undefined}
                    onMouseEnter={() => prefetch(item.href)}
                    onFocus={() => prefetch(item.href)}
                    onClick={() => setOpen(false)}
                    className={cn(
                      "flex items-center gap-2 rounded-md px-2 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      active
                        ? "bg-accent font-medium text-accent-foreground"
                        : "text-foreground/80 hover:bg-muted",
                    )}
                  >
                    <Icon className="size-4 shrink-0" aria-hidden />
                    <span>{item.title}</span>
                  </Link>
                  {item.children && active ? (
                    <div className="mt-0.5 mb-1 ml-6 space-y-0.5 border-l pl-2">
                      {item.children.map((child) => {
                        const childActive = pathname === child.href;
                        return (
                          <Link
                            key={child.href}
                            href={child.href}
                            aria-current={childActive ? "page" : undefined}
                            onClick={() => setOpen(false)}
                            className={cn(
                              "block rounded-md px-2 py-1.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                              childActive
                                ? "bg-accent font-medium"
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
          <div className="mt-4 space-y-1 border-t pt-3">
            {secondaryNav.map((item) => {
              const Icon = item.icon;
              const active = pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  onClick={() => setOpen(false)}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-2 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active ? "bg-accent font-medium" : "text-muted-foreground hover:bg-muted",
                  )}
                >
                  <Icon className="size-4 shrink-0" aria-hidden />
                  <span>{item.title}</span>
                </Link>
              );
            })}
            <div className="flex items-center justify-between px-2 py-2 text-xs">
              <span className="text-muted-foreground">API</span>
              <StatusBadge
                label={health.isSuccess ? "local" : health.isLoading ? "…" : "offline"}
                tone={health.isSuccess ? "success" : health.isLoading ? "muted" : "danger"}
              />
            </div>
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}

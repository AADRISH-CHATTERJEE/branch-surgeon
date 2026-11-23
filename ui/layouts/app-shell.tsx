"use client";

import type { ReactNode } from "react";
import { useEffect } from "react";
import { usePathname } from "next/navigation";

import { ConnectionBanner } from "@/components/layout/connection-banner";
import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";
import { SkipLink } from "@/components/layout/skip-link";
import { ErrorBoundary } from "@/components/feedback/error-boundary";
import { RouteAnnouncer } from "@/components/feedback/route-announcer";
import { CommandPaletteProvider } from "@/features/command-palette/command-palette";
import { BackNavProvider } from "@/providers/back-nav-provider";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  // Keep document pinned to the top so chrome (sidebar brand + header) never scrolls away.
  useEffect(() => {
    window.scrollTo(0, 0);
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
  }, [pathname]);

  return (
    <CommandPaletteProvider>
      <BackNavProvider chromeProvidesBack>
        <SkipLink />
        <RouteAnnouncer />
        <div className="flex h-dvh max-h-dvh overflow-hidden bg-background">
          <div className="hidden h-full min-h-0 md:flex">
            <Sidebar />
          </div>
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <ConnectionBanner />
            <Header />
            <main
              id="main-content"
              tabIndex={-1}
              className="min-h-0 flex-1 overflow-auto outline-none"
              onFocus={(event) => {
                // Focusing #main-content must not scroll the document and clip the header.
                if (event.target === event.currentTarget) {
                  window.scrollTo(0, 0);
                }
              }}
            >
              <ErrorBoundary>{children}</ErrorBoundary>
            </main>
          </div>
        </div>
      </BackNavProvider>
    </CommandPaletteProvider>
  );
}

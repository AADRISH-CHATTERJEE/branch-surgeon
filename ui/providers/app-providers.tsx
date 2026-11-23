"use client";

import * as React from "react";

import { AppToaster } from "@/components/feedback/app-toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { OrgProvider } from "@/providers/org-context";
import { PreferencesProvider } from "@/providers/preferences-provider";
import { QueryProvider } from "@/providers/query-provider";
import { RepoProvider } from "@/providers/repo-context";
import { ThemeProvider } from "@/providers/theme-provider";

export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <QueryProvider>
        <RepoProvider>
          <OrgProvider>
            <PreferencesProvider>
              <TooltipProvider delayDuration={200}>
                {children}
                <AppToaster />
              </TooltipProvider>
            </PreferencesProvider>
          </OrgProvider>
        </RepoProvider>
      </QueryProvider>
    </ThemeProvider>
  );
}

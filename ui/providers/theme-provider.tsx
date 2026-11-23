"use client";

import * as React from "react";
import { ThemeProvider as NextThemesProvider } from "next-themes";

/**
 * next-themes injects an inline <script> for FOUC prevention. React 19 / Next 16
 * logs "Encountered a script tag while rendering" when that script uses
 * type="text/javascript". Use application/json so React won't treat it as executable.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      scriptProps={{ type: "application/json" }}
    >
      {children}
    </NextThemesProvider>
  );
}

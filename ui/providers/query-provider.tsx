"use client";

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 30 * 60_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          const status =
            error && typeof error === "object" && "status" in error
              ? Number((error as { status: number }).status)
              : undefined;
          if (status !== undefined && status >= 400 && status < 500) return false;
          return failureCount < 1;
        },
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(makeClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

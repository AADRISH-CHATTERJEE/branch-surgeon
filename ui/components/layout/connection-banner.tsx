"use client";

import Link from "next/link";

import { useApiHealth } from "@/queries/use-health";
import { useRepoContext } from "@/providers/repo-context";
import { ApiError } from "@/services/errors";

export function ConnectionBanner() {
  const { apiBaseUrl } = useRepoContext();
  const health = useApiHealth();

  if (health.isLoading || health.isSuccess) return null;

  const err = health.error;
  const message =
    err instanceof ApiError
      ? err.message
      : "Local API is unreachable";

  return (
    <div className="border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-sm">
      <span className="font-medium text-destructive">API offline</span>
      <span className="text-muted-foreground">
        {" "}
        — {message}. Expected at <code className="font-mono text-xs">{apiBaseUrl}</code>.{" "}
        <Link href="/settings" className="underline underline-offset-2">
          Settings
        </Link>
      </span>
    </div>
  );
}

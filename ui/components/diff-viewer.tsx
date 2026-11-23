"use client";

import dynamic from "next/dynamic";

import { cn } from "@/lib/utils";

const Editor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex h-64 items-center justify-center rounded-lg border text-sm text-muted-foreground">
      Loading editor…
    </div>
  ),
});

type DiffViewerProps = {
  /** Patch / preview text from the Local API — never fabricated. */
  value: string;
  language?: string;
  className?: string;
  height?: string;
};

export function DiffViewer({
  value,
  language = "diff",
  className,
  height = "360px",
}: DiffViewerProps) {
  if (!value.trim()) {
    return (
      <div
        className={cn(
          "flex h-48 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground",
          className,
        )}
      >
        No patch content returned by the API.
      </div>
    );
  }

  return (
    <div className={cn("overflow-hidden rounded-lg border", className)}>
      <Editor
        height={height}
        language={language}
        value={value}
        theme="vs-dark"
        options={{
          readOnly: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          fontSize: 12,
          wordWrap: "on",
        }}
      />
    </div>
  );
}

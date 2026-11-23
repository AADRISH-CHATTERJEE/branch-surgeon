"use client";

import dynamic from "next/dynamic";
import { FileCode2 } from "lucide-react";

import { EmptyState } from "@/components/feedback/empty-state";
import { StatusBadge } from "@/components/data-display/status-badge";
import { cn } from "@/lib/utils";

const Editor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
      Loading file…
    </div>
  ),
});

export type FilePreviewMeta = {
  path: string;
  language?: string | null;
  size?: number | null;
  sha256?: string | null;
  id?: string;
};

type FilePreviewProps = {
  file: FilePreviewMeta | null;
  content?: string | null;
  language?: string | null;
  isLoading?: boolean;
  errorMessage?: string | null;
  className?: string;
};

/**
 * Preview pane: metadata always; Monaco read-only source when content is available.
 */
export function FilePreview({
  file,
  content,
  language,
  isLoading = false,
  errorMessage = null,
  className,
}: FilePreviewProps) {
  if (!file) {
    return (
      <EmptyState
        className={className}
        icon={FileCode2}
        title="No file selected"
        description="Select a file to inspect metadata and source."
      />
    );
  }

  const editorLanguage = language || file.language || "plaintext";

  return (
    <div className={cn("flex h-full min-h-[320px] flex-col rounded-lg border", className)}>
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
        <p className="truncate font-mono text-xs">{file.path}</p>
        {editorLanguage ? <StatusBadge label={editorLanguage} tone="info" /> : null}
      </div>
      <dl className="grid grid-cols-2 gap-2 border-b px-3 py-3 text-xs">
        <div>
          <dt className="text-muted-foreground">Size</dt>
          <dd className="font-medium tabular-nums">
            {file.size != null ? `${file.size} bytes` : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">File id</dt>
          <dd className="truncate font-mono">{file.id ?? "—"}</dd>
        </div>
        <div className="col-span-2">
          <dt className="text-muted-foreground">SHA-256</dt>
          <dd className="truncate font-mono">{file.sha256 ?? "—"}</dd>
        </div>
      </dl>
      <div className="min-h-0 flex-1 overflow-hidden">
        {isLoading ? (
          <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
            Loading file…
          </div>
        ) : errorMessage ? (
          <div className="flex h-64 items-center justify-center px-4 text-center">
            <p className="max-w-sm text-sm text-muted-foreground">{errorMessage}</p>
          </div>
        ) : content != null ? (
          <Editor
            height="420px"
            language={editorLanguage}
            value={content}
            theme="vs-dark"
            options={{
              readOnly: true,
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              fontSize: 13,
              lineNumbers: "on",
              wordWrap: "off",
              automaticLayout: true,
              renderWhitespace: "selection",
              tabSize: 4,
            }}
          />
        ) : (
          <div className="flex h-64 items-center justify-center px-4 text-center">
            <p className="max-w-xs text-sm text-muted-foreground">
              No file content to display.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

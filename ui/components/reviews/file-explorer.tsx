"use client";

import { EmptyState } from "@/components/feedback/empty-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { FileCode } from "lucide-react";

type FileItem = {
  path: string;
  suggestionCount?: number;
};

type FileExplorerProps = {
  files: FileItem[];
  selectedFile?: string | null;
  onSelectFile: (file: string) => void;
  className?: string;
};

export function FileExplorer({
  files,
  selectedFile,
  onSelectFile,
  className,
}: FileExplorerProps) {
  return (
    <div className={cn("flex flex-col overflow-hidden rounded-lg border", className)}>
      <div className="border-b bg-muted/40 px-3 py-2">
        <h3 className="text-sm font-semibold">Changed Files ({files.length})</h3>
      </div>
      {!files.length ? (
        <EmptyState
          className="m-2 flex-1 border-0 py-10"
          title="No changed files"
          description="No changed files were analyzed."
        />
      ) : (
        <ScrollArea className="flex-1">
          <ul className="divide-y">
            {files.map((file) => (
              <li key={file.path}>
                <button
                  type="button"
                  onClick={() => onSelectFile(file.path)}
                  className={cn(
                    "flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-muted/50",
                    selectedFile === file.path && "bg-muted",
                  )}
                >
                  <FileCode className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate font-mono text-xs">
                    {file.path}
                  </span>
                  {file.suggestionCount != null && file.suggestionCount > 0 && (
                    <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                      {file.suggestionCount}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </ScrollArea>
      )}
    </div>
  );
}

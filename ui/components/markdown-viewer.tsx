"use client";

import * as React from "react";
import { Check, Copy, ExternalLink } from "lucide-react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";

import { ListSkeleton } from "@/components/feedback/loading-skeletons";
import { Button } from "@/components/ui/button";
import { slugifyHeading } from "@/lib/markdown";
import { cn } from "@/lib/utils";

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- rehype plugin shape; avoid hard dep on `unified` types
type RehypePlugin = any;

export type MarkdownViewerProps = {
  content: string;
  className?: string;
  /** Soft highlight of search matches in rendered text nodes */
  searchQuery?: string;
  /** Called when heading elements mount (for scroll-spy consumers) */
  onReady?: () => void;
  /**
   * When false, skip AST parse/render (hidden panels / unselected docs).
   * Defaults to true.
   */
  active?: boolean;
};

const FENCE_RE = /```/;

function highlightText(text: string, query?: string): React.ReactNode {
  if (!query?.trim()) return text;
  const q = query.trim();
  const lower = text.toLowerCase();
  const ql = q.toLowerCase();
  const nodes: React.ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < text.length) {
    const at = lower.indexOf(ql, i);
    if (at === -1) {
      nodes.push(text.slice(i));
      break;
    }
    if (at > i) nodes.push(text.slice(i, at));
    nodes.push(
      <mark key={key++} className="rounded-sm bg-primary/20 px-0.5 text-foreground">
        {text.slice(at, at + q.length)}
      </mark>,
    );
    i = at + q.length;
  }
  return nodes;
}

function walkChildren(children: React.ReactNode, query?: string): React.ReactNode {
  return React.Children.map(children, (child) => {
    if (typeof child === "string") return highlightText(child, query);
    if (React.isValidElement<{ children?: React.ReactNode }>(child) && child.props.children) {
      return React.cloneElement(child, {
        ...child.props,
        children: walkChildren(child.props.children, query),
      });
    }
    return child;
  });
}

function CodeBlock({
  className,
  children,
}: {
  className?: string;
  children?: React.ReactNode;
}) {
  const [copied, setCopied] = React.useState(false);
  const preRef = React.useRef<HTMLPreElement>(null);
  const lang = /language-([\w-]+)/.exec(className ?? "")?.[1];

  const onCopy = async () => {
    const text = preRef.current?.innerText ?? "";
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* ignore */
    }
  };

  if (lang === "mermaid") {
    const raw = String(children ?? "").replace(/\n$/, "");
    return (
      <div
        className="not-prose my-4 rounded-md border border-dashed bg-muted/30 px-3 py-3 text-sm text-muted-foreground"
        role="note"
        aria-label="Mermaid diagram unavailable"
      >
        <p className="mb-2 font-medium text-foreground">Mermaid diagram</p>
        <p className="mb-2 text-xs">
          Rendering is not enabled in this build. Showing source as a graceful fallback.
        </p>
        <pre className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs text-foreground">
          {raw}
        </pre>
      </div>
    );
  }

  return (
    <div className="not-prose group relative my-4 overflow-hidden rounded-md border bg-muted/40">
      <div className="flex items-center justify-between border-b bg-muted/60 px-3 py-1.5">
        <span className="text-2xs font-medium tracking-wide text-muted-foreground uppercase">
          {lang || "code"}
        </span>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 gap-1 px-2 text-xs"
          onClick={() => void onCopy()}
          aria-label="Copy code"
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <pre
        ref={preRef}
        className={cn("overflow-x-auto p-3 text-xs leading-relaxed", className)}
      >
        <code className={className}>{children}</code>
      </pre>
    </div>
  );
}

function CalloutBlockquote({ children }: { children?: React.ReactNode }) {
  const text = React.Children.toArray(children)
    .map((c) => (typeof c === "string" ? c : ""))
    .join("");
  const match = text.match(/^\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*/i);
  if (!match) {
    return (
      <blockquote className="border-l-2 border-border pl-4 text-muted-foreground italic">
        {children}
      </blockquote>
    );
  }
  const kind = match[1].toUpperCase();
  const tones: Record<string, string> = {
    NOTE: "border-primary/40 bg-primary/5",
    TIP: "border-chart-2/50 bg-muted/40",
    IMPORTANT: "border-primary bg-primary/10",
    WARNING: "border-destructive/50 bg-destructive/5",
    CAUTION: "border-destructive bg-destructive/10",
  };
  return (
    <aside
      className={cn("my-4 rounded-md border px-3 py-2 text-sm not-italic", tones[kind] ?? tones.NOTE)}
      aria-label={`${kind} callout`}
    >
      <p className="mb-1 text-2xs font-semibold tracking-wide uppercase">{kind}</p>
      <div>{children}</div>
    </aside>
  );
}

/** Lazy-load highlight.js only when fenced code blocks are present. */
function useLazyHighlight(needsHighlight: boolean) {
  const [plugin, setPlugin] = React.useState<RehypePlugin | null>(null);
  const [loadedForFence, setLoadedForFence] = React.useState(false);

  React.useEffect(() => {
    if (!needsHighlight) return;
    let cancelled = false;
    void Promise.all([
      import("rehype-highlight"),
      import("highlight.js/styles/github-dark.css"),
    ]).then(([mod]) => {
      if (cancelled) return;
      setPlugin(() => mod.default);
      setLoadedForFence(true);
    });
    return () => {
      cancelled = true;
    };
  }, [needsHighlight]);

  const ready = !needsHighlight || loadedForFence;
  return { plugin: needsHighlight ? plugin : null, ready };
}

function MarkdownBody({
  content,
  className,
  searchQuery,
  onReady,
}: Omit<MarkdownViewerProps, "active">) {
  const deferred = React.useDeferredValue(content);
  const deferredQuery = React.useDeferredValue(searchQuery);
  const needsHighlight = FENCE_RE.test(deferred);
  const { plugin: highlightPlugin, ready: highlightReady } = useLazyHighlight(needsHighlight);

  const components: Components = React.useMemo(
    () => ({
      h1: ({ children, ...props }) => (
        <h1
          {...props}
          id={props.id || slugifyHeading(String(children))}
          className="scroll-mt-24 text-2xl font-semibold tracking-tight"
        >
          {walkChildren(children, deferredQuery)}
        </h1>
      ),
      h2: ({ children, ...props }) => (
        <h2
          {...props}
          id={props.id || slugifyHeading(String(children))}
          className="mt-8 scroll-mt-24 border-b pb-1 text-xl font-semibold tracking-tight"
        >
          {walkChildren(children, deferredQuery)}
        </h2>
      ),
      h3: ({ children, ...props }) => (
        <h3
          {...props}
          id={props.id || slugifyHeading(String(children))}
          className="mt-6 scroll-mt-24 text-lg font-semibold"
        >
          {walkChildren(children, deferredQuery)}
        </h3>
      ),
      h4: ({ children, ...props }) => (
        <h4
          {...props}
          id={props.id || slugifyHeading(String(children))}
          className="mt-4 scroll-mt-24 text-base font-semibold"
        >
          {walkChildren(children, deferredQuery)}
        </h4>
      ),
      h5: ({ children, ...props }) => (
        <h5
          {...props}
          id={props.id || slugifyHeading(String(children))}
          className="mt-3 scroll-mt-24 text-sm font-semibold"
        >
          {walkChildren(children, deferredQuery)}
        </h5>
      ),
      h6: ({ children, ...props }) => (
        <h6
          {...props}
          id={props.id || slugifyHeading(String(children))}
          className="mt-3 scroll-mt-24 text-sm font-medium text-muted-foreground"
        >
          {walkChildren(children, deferredQuery)}
        </h6>
      ),
      p: ({ children }) => (
        <p className="my-3 leading-relaxed text-foreground/90">
          {walkChildren(children, deferredQuery)}
        </p>
      ),
      a: ({ href, children }) => {
        const external = Boolean(href?.startsWith("http"));
        const isHash = Boolean(href?.startsWith("#"));
        return (
          <a
            href={href}
            className="font-medium text-primary underline-offset-4 hover:underline"
            {...(external
              ? { target: "_blank", rel: "noopener noreferrer" }
              : {})}
            onClick={
              isHash
                ? (e) => {
                    const id = href!.slice(1);
                    const el = document.getElementById(id);
                    if (el) {
                      e.preventDefault();
                      el.scrollIntoView({ behavior: "smooth", block: "start" });
                      history.replaceState(null, "", `#${id}`);
                    }
                  }
                : undefined
            }
          >
            {walkChildren(children, deferredQuery)}
            {external ? (
              <ExternalLink className="ml-1 inline size-3 align-[-2px] opacity-70" aria-hidden />
            ) : null}
          </a>
        );
      },
      ul: ({ children }) => (
        <ul className="my-3 list-disc space-y-1 pl-5">{children}</ul>
      ),
      ol: ({ children }) => (
        <ol className="my-3 list-decimal space-y-1 pl-5">{children}</ol>
      ),
      li: ({ children, className }) => (
        <li className={cn(className)}>{walkChildren(children, deferredQuery)}</li>
      ),
      table: ({ children }) => (
        <div className="my-4 overflow-x-auto rounded-md border">
          <table className="w-full border-collapse text-sm">{children}</table>
        </div>
      ),
      thead: ({ children }) => <thead className="bg-muted/50">{children}</thead>,
      th: ({ children }) => (
        <th className="border-b px-3 py-2 text-left font-medium">
          {walkChildren(children, deferredQuery)}
        </th>
      ),
      td: ({ children }) => (
        <td className="border-b px-3 py-2 align-top">{walkChildren(children, deferredQuery)}</td>
      ),
      blockquote: ({ children }) => <CalloutBlockquote>{children}</CalloutBlockquote>,
      hr: () => <hr className="my-8 border-border" />,
      img: ({ src, alt }) => (
        // eslint-disable-next-line @next/next/no-img-element -- company markdown may use relative/external images
        <img
          src={src}
          alt={alt || ""}
          className="my-4 max-h-[28rem] rounded-md border"
          loading="lazy"
        />
      ),
      pre: ({ children }) => {
        const child = React.Children.toArray(children)[0];
        if (React.isValidElement<{ className?: string; children?: React.ReactNode }>(child)) {
          return (
            <CodeBlock className={child.props.className}>{child.props.children}</CodeBlock>
          );
        }
        return <CodeBlock>{children}</CodeBlock>;
      },
      code: ({ className, children }) => {
        const isBlock = Boolean(className?.includes("language-"));
        if (isBlock) {
          return <code className={className}>{children}</code>;
        }
        return (
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">
            {children}
          </code>
        );
      },
      input: (props) => (
        <input
          {...props}
          disabled
          className="mr-2 align-middle accent-primary"
          aria-label={props.checked ? "Completed task" : "Incomplete task"}
        />
      ),
    }),
    [deferredQuery],
  );

  const rehypePlugins = React.useMemo(() => {
    const plugins: RehypePlugin[] = [rehypeSlug];
    if (highlightPlugin) plugins.push(highlightPlugin);
    return plugins;
  }, [highlightPlugin]);

  React.useEffect(() => {
    if (!highlightReady) return;
    onReady?.();
  }, [deferred, highlightReady, onReady]);

  if (!deferred.trim()) {
    return (
      <p className="text-sm text-muted-foreground">No content in this document.</p>
    );
  }

  if (needsHighlight && !highlightReady) {
    return <ListSkeleton rows={6} />;
  }

  return (
    <div
      className={cn("markdown-viewer max-w-none text-sm", className)}
      data-search={deferredQuery || undefined}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={rehypePlugins}
        components={components}
      >
        {deferred}
      </ReactMarkdown>
    </div>
  );
}

/**
 * Renders markdown only when `active`. Syntax highlighting (highlight.js) is
 * loaded on demand when fenced code blocks exist — Dashboard never pays for it.
 */
export function MarkdownViewer({
  content,
  className,
  searchQuery,
  onReady,
  active = true,
}: MarkdownViewerProps) {
  if (!active) return null;

  return (
    <MarkdownBody
      content={content}
      className={className}
      searchQuery={searchQuery}
      onReady={onReady}
    />
  );
}

"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  Activity,
  BookOpen,
  FileText,
  FolderGit2,
  Heading,
  History,
  ListChecks,
  Network,
  Scale,
  Scissors,
  Settings,
  Sparkles,
  Wand2,
} from "lucide-react";

import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { DOC_CATALOG, resolveDocContent } from "@/features/documentation/lib/doc-catalog";
import { extractHeadings } from "@/features/documentation/lib/markdown-utils";
import { primaryNav, secondaryNav } from "@/lib/navigation";
import { useDocumentation } from "@/queries/use-documentation";

type CommandPaletteContextValue = {
  open: () => void;
  close: () => void;
};

const CommandPaletteContext = React.createContext<CommandPaletteContextValue | null>(null);

export function useCommandPalette() {
  const ctx = React.useContext(CommandPaletteContext);
  if (!ctx) {
    throw new Error("useCommandPalette must be used within CommandPaletteProvider");
  }
  return ctx;
}

export function CommandPaletteProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false);
  const router = useRouter();
  /** Only fetch docs when the palette is open (then reuse RQ cache). */
  const docs = useDocumentation(open);

  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const value = React.useMemo(
    () => ({
      open: () => setOpen(true),
      close: () => setOpen(false),
    }),
    [],
  );

  const go = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  const docItems = React.useMemo(() => {
    const data = docs.data;
    return DOC_CATALOG.filter((d) => d.apiKey).flatMap((entry) => {
      const content = resolveDocContent(entry, data);
      const base = [
        {
          key: `doc-${entry.id}`,
          value: `documentation ${entry.title}`,
          label: entry.title,
          href: `/documentation?doc=${entry.id}`,
          icon: "doc" as const,
        },
      ];
      if (!content.trim()) return base;
      const headings = extractHeadings(content).slice(0, 12).map((h) => ({
        key: `doc-${entry.id}-${h.id}`,
        value: `documentation ${entry.title} ${h.text}`,
        label: `${entry.title} → ${h.text}`,
        href: `/documentation?doc=${entry.id}#${h.id}`,
        icon: "heading" as const,
      }));
      return [...base, ...headings];
    });
  }, [docs.data]);

  return (
    <CommandPaletteContext.Provider value={value}>
      {children}
      <CommandDialog
        open={open}
        onOpenChange={setOpen}
        title="Command palette"
        description="Jump to a page or action"
      >
        <Command>
          <CommandInput placeholder="Type a command or search…" />
          <CommandList>
            <CommandEmpty>No results found.</CommandEmpty>
            <CommandGroup heading="Actions">
              <CommandItem value="run review" onSelect={() => go("/reviews")}>
                <ListChecks className="size-4" />
                Run Review
              </CommandItem>
              <CommandItem
                value="generate recommendations"
                onSelect={() => go("/recommendations")}
              >
                <Sparkles className="size-4" />
                Generate Recommendations
              </CommandItem>
              <CommandItem value="open graph" onSelect={() => go("/repository/graph")}>
                <Network className="size-4" />
                Open Graph
              </CommandItem>
              <CommandItem value="open surgeon" onSelect={() => go("/surgeon")}>
                <Scissors className="size-4" />
                Open Surgeon
              </CommandItem>
              <CommandItem value="open history" onSelect={() => go("/history")}>
                <History className="size-4" />
                Open History
              </CommandItem>
              <CommandItem value="open rules" onSelect={() => go("/rules")}>
                <Scale className="size-4" />
                Open Rules
              </CommandItem>
              <CommandItem
                value="open transformations transform"
                onSelect={() => go("/transform")}
              >
                <Wand2 className="size-4" />
                Open Transformations
              </CommandItem>
              <CommandItem value="open activity" onSelect={() => go("/activity")}>
                <Activity className="size-4" />
                Open Activity
              </CommandItem>
              <CommandItem value="open reviews" onSelect={() => go("/reviews")}>
                <ListChecks className="size-4" />
                Open Reviews
              </CommandItem>
              <CommandItem
                value="open recommendations"
                onSelect={() => go("/recommendations")}
              >
                <Sparkles className="size-4" />
                Open Recommendations
              </CommandItem>
              <CommandItem value="open documentation" onSelect={() => go("/documentation")}>
                <BookOpen className="size-4" />
                Open Documentation
              </CommandItem>
              <CommandItem value="open repository" onSelect={() => go("/repository")}>
                <FolderGit2 className="size-4" />
                Open Repository
              </CommandItem>
              <CommandItem
                value="open settings workspace ai ui health"
                onSelect={() => go("/settings")}
              >
                <Settings className="size-4" />
                Open Settings
              </CommandItem>
            </CommandGroup>
            <CommandSeparator />
            <CommandGroup heading="Navigate">
              {primaryNav.map((item) => (
                <React.Fragment key={item.href}>
                  <CommandItem
                    value={item.title}
                    onSelect={() => go(item.href)}
                  >
                    <item.icon className="size-4" />
                    {item.title}
                  </CommandItem>
                  {item.children?.map((child) => (
                    <CommandItem
                      key={child.href}
                      value={`${item.title} ${child.title}`}
                      onSelect={() => go(child.href)}
                    >
                      <item.icon className="size-4 opacity-60" />
                      {item.title} → {child.title}
                    </CommandItem>
                  ))}
                </React.Fragment>
              ))}
              {secondaryNav.map((item) => (
                <CommandItem key={item.href} value={item.title} onSelect={() => go(item.href)}>
                  <item.icon className="size-4" />
                  {item.title}
                </CommandItem>
              ))}
              <CommandItem
                value="settings workspace"
                onSelect={() => go("/settings")}
              >
                <Settings className="size-4" />
                Settings → Workspace
              </CommandItem>
              <CommandItem value="settings ai" onSelect={() => go("/settings")}>
                <Settings className="size-4" />
                Settings → AI
              </CommandItem>
              <CommandItem
                value="settings ui health"
                onSelect={() => go("/settings")}
              >
                <Settings className="size-4" />
                Settings → UI Health
              </CommandItem>
              <CommandItem
                value="organization teams"
                onSelect={() => go("/organization/teams")}
              >
                Organization → Teams
              </CommandItem>
              <CommandItem
                value="organization members"
                onSelect={() => go("/organization/members")}
              >
                Organization → Members
              </CommandItem>
              <CommandItem
                value="organization organizations"
                onSelect={() => go("/organization")}
              >
                Organizations
              </CommandItem>
            </CommandGroup>
            <CommandSeparator />
            <CommandGroup heading="Documentation">
              <CommandItem value="documentation center" onSelect={() => go("/documentation")}>
                <BookOpen className="size-4" />
                Documentation Center
              </CommandItem>
              {docItems.map((item) => (
                <CommandItem key={item.key} value={item.value} onSelect={() => go(item.href)}>
                  {item.icon === "heading" ? (
                    <Heading className="size-4" />
                  ) : (
                    <FileText className="size-4" />
                  )}
                  {item.label}
                </CommandItem>
              ))}
            </CommandGroup>
            <CommandSeparator />
            <CommandGroup heading="Repository">
              <CommandItem value="repository health" onSelect={() => go("/repository/health")}>
                Health
              </CommandItem>
              <CommandItem value="repository graph" onSelect={() => go("/repository/graph")}>
                Repository graph
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </CommandDialog>
    </CommandPaletteContext.Provider>
  );
}

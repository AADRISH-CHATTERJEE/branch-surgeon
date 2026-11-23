/** Visual styles for persisted graph node `type` and edge `relationship`. */

export const NODE_TYPE_STYLES: Record<
  string,
  { label: string; color: string; bg: string; border: string; group: string }
> = {
  file: {
    label: "File",
    color: "var(--chart-series-1)",
    bg: "color-mix(in oklch, var(--chart-series-1) 14%, transparent)",
    border: "var(--chart-series-1)",
    group: "files",
  },
  package: {
    label: "Folder",
    color: "var(--chart-series-3)",
    bg: "color-mix(in oklch, var(--chart-series-3) 14%, transparent)",
    border: "var(--chart-series-3)",
    group: "folders",
  },
  module: {
    label: "Module",
    color: "var(--chart-series-2)",
    bg: "color-mix(in oklch, var(--chart-series-2) 14%, transparent)",
    border: "var(--chart-series-2)",
    group: "modules",
  },
  class: {
    label: "Class",
    color: "var(--chart-series-4)",
    bg: "color-mix(in oklch, var(--chart-series-4) 14%, transparent)",
    border: "var(--chart-series-4)",
    group: "classes",
  },
  function: {
    label: "Function",
    color: "var(--chart-series-2)",
    bg: "color-mix(in oklch, var(--chart-series-2) 16%, transparent)",
    border: "var(--chart-series-2)",
    group: "functions",
  },
  method: {
    label: "Method",
    color: "var(--chart-series-6)",
    bg: "color-mix(in oklch, var(--chart-series-6) 14%, transparent)",
    border: "var(--chart-series-6)",
    group: "functions",
  },
  nested_function: {
    label: "Nested fn",
    color: "var(--chart-series-6)",
    bg: "color-mix(in oklch, var(--chart-series-6) 14%, transparent)",
    border: "var(--chart-series-6)",
    group: "functions",
  },
};

export const EDGE_STYLES: Record<
  string,
  { label: string; stroke: string; dashed?: boolean; category: string }
> = {
  FILE_IMPORTS_FILE: {
    label: "imports",
    stroke: "var(--chart-series-1)",
    category: "imports",
  },
  MODULE_IMPORTS_MODULE: {
    label: "imports",
    stroke: "var(--chart-series-1)",
    category: "imports",
  },
  CALLS: { label: "calls", stroke: "var(--chart-series-2)", category: "calls" },
  INHERITS_FROM: {
    label: "inherits",
    stroke: "var(--chart-series-4)",
    category: "inherits",
  },
  FILE_CONTAINS_MODULE: {
    label: "contains",
    stroke: "var(--chart-series-3)",
    dashed: true,
    category: "contains",
  },
  MODULE_CONTAINS_CLASS: {
    label: "contains",
    stroke: "var(--chart-series-3)",
    dashed: true,
    category: "contains",
  },
  MODULE_CONTAINS_FUNCTION: {
    label: "contains",
    stroke: "var(--chart-series-3)",
    dashed: true,
    category: "contains",
  },
  CLASS_CONTAINS_METHOD: {
    label: "contains",
    stroke: "var(--chart-series-3)",
    dashed: true,
    category: "contains",
  },
  MODULE_CHILD_OF: {
    label: "contains",
    stroke: "var(--chart-series-3)",
    dashed: true,
    category: "contains",
  },
  REFERENCES_SYMBOL: {
    label: "references",
    stroke: "var(--chart-series-7)",
    category: "references",
  },
  FUNCTION_DEFINED_IN_FILE: {
    label: "references",
    stroke: "var(--muted-foreground)",
    dashed: true,
    category: "references",
  },
  CLASS_DEFINED_IN_FILE: {
    label: "references",
    stroke: "var(--muted-foreground)",
    dashed: true,
    category: "references",
  },
  FUNCTION_DEFINED_IN_MODULE: {
    label: "references",
    stroke: "var(--muted-foreground)",
    dashed: true,
    category: "references",
  },
  CLASS_DEFINED_IN_MODULE: {
    label: "references",
    stroke: "var(--muted-foreground)",
    dashed: true,
    category: "references",
  },
  SYMBOL_DEFINED_IN_FILE: {
    label: "references",
    stroke: "var(--muted-foreground)",
    dashed: true,
    category: "references",
  },
  SYMBOL_DEFINED_IN_MODULE: {
    label: "references",
    stroke: "var(--muted-foreground)",
    dashed: true,
    category: "references",
  },
  PARENT_FUNCTION: {
    label: "contains",
    stroke: "var(--chart-series-3)",
    dashed: true,
    category: "contains",
  },
  NESTED_FUNCTION: {
    label: "contains",
    stroke: "var(--chart-series-3)",
    dashed: true,
    category: "contains",
  },
};

export const EDGE_LEGEND: {
  key: string;
  label: string;
  stroke: string;
  dashed?: boolean;
}[] = [
  { key: "imports", label: "imports", stroke: "var(--chart-series-1)" },
  { key: "calls", label: "calls", stroke: "var(--chart-series-2)" },
  { key: "inherits", label: "inherits", stroke: "var(--chart-series-4)" },
  {
    key: "contains",
    label: "contains",
    stroke: "var(--chart-series-3)",
    dashed: true,
  },
  { key: "references", label: "references", stroke: "var(--chart-series-7)" },
];

export const FILTER_GROUPS = [
  { key: "files", label: "Files", types: ["file"] },
  { key: "folders", label: "Folders", types: ["package"] },
  { key: "modules", label: "Modules", types: ["module"] },
  { key: "classes", label: "Classes", types: ["class"] },
  {
    key: "functions",
    label: "Functions",
    types: ["function", "method", "nested_function"],
  },
] as const;

export type FilterGroupKey = (typeof FILTER_GROUPS)[number]["key"];

export function nodeStyle(type: string) {
  return (
    NODE_TYPE_STYLES[type] ?? {
      label: type || "Unknown",
      color: "var(--muted-foreground)",
      bg: "var(--muted)",
      border: "var(--border)",
      group: "other",
    }
  );
}

export function edgeStyle(relationship: string) {
  return (
    EDGE_STYLES[relationship] ?? {
      label: relationship.toLowerCase().replace(/_/g, " "),
      stroke: "var(--muted-foreground)",
      category: "other",
    }
  );
}

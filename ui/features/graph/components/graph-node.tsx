"use client";

import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { Box, FileCode, Folder, FunctionSquare, Hexagon, Layers } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

import { nodeStyle } from "../lib/graph-styles";

export type GraphNodeData = {
  label: string;
  type: string;
  highlighted?: boolean;
  dimmed?: boolean;
  selected?: boolean;
};

export type RefactoryGraphNode = Node<GraphNodeData, "refactory">;

function TypeIcon({ type }: { type: string }) {
  const className = "size-3.5 shrink-0";
  switch (type) {
    case "file":
      return <FileCode className={className} />;
    case "package":
      return <Folder className={className} />;
    case "module":
      return <Layers className={className} />;
    case "class":
      return <Box className={className} />;
    case "function":
    case "method":
    case "nested_function":
      return <FunctionSquare className={className} />;
    default:
      return <Hexagon className={className} />;
  }
}

function RefactoryGraphNodeComponentInner({ data }: NodeProps<RefactoryGraphNode>) {
  const style = nodeStyle(data.type);
  return (
    <div
      className={cn(
        "rounded-md border px-2.5 py-1.5 text-xs shadow-sm",
        data.dimmed && "opacity-20",
        data.highlighted && "ring-2 ring-offset-1 ring-offset-background",
        data.selected && "shadow-md",
      )}
      style={{
        background: style.bg,
        borderColor: data.selected || data.highlighted ? style.color : style.border,
        color: style.color,
        minWidth: 120,
        maxWidth: 168,
        ["--tw-ring-color" as string]: style.color,
      }}
    >
      <Handle type="target" position={Position.Top} className="!size-1.5 !bg-muted-foreground" />
      <div className="flex items-center gap-1.5">
        <TypeIcon type={data.type} />
        <span className="truncate font-medium text-foreground">{data.label}</span>
      </div>
      <p className="mt-0.5 truncate text-2xs opacity-70">{style.label}</p>
      <Handle type="source" position={Position.Bottom} className="!size-1.5 !bg-muted-foreground" />
    </div>
  );
}

export const RefactoryGraphNodeComponent = React.memo(RefactoryGraphNodeComponentInner);

/** Stable nodeTypes map — never recreate per render. */
export const graphNodeTypes = {
  refactory: RefactoryGraphNodeComponent,
};

/** Stable empty edgeTypes — React Flow compares by reference. */
export const graphEdgeTypes = {};

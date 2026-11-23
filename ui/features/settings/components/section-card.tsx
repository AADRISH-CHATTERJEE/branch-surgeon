"use client";

import type { ReactNode } from "react";

import { Unavailable } from "@/components/feedback/unavailable";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function SectionCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export function ReadOnlyValue({
  value,
  mono,
  emptyLabel = "Not Available",
  emptyReason = "Not returned by Local API.",
}: {
  value: string | number | null | undefined;
  mono?: boolean;
  /** Shown when the API does not expose this field (intentional empty). */
  emptyLabel?: string;
  emptyReason?: string;
}) {
  if (value == null || value === "") {
    return <Unavailable compact title={emptyLabel} reason={emptyReason} />;
  }
  return (
    <p className={cn("text-sm", mono && "font-mono text-xs")}>{String(value)}</p>
  );
}

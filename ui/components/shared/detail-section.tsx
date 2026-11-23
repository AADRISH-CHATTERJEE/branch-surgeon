import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type DetailSectionProps = {
  title: string;
  children: ReactNode;
  className?: string;
};

export function DetailSection({ title, children, className }: DetailSectionProps) {
  return (
    <section className={cn("space-y-1", className)}>
      <h4 className="text-2xs font-medium tracking-wide text-muted-foreground uppercase">
        {title}
      </h4>
      <div className="text-sm text-muted-foreground">{children}</div>
    </section>
  );
}

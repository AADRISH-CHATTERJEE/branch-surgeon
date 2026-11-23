"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";

import { DOC_CATALOG, type DocEntry } from "../lib/doc-catalog";

type DocRelatedProps = {
  entry: DocEntry;
  onSelectDoc: (id: string) => void;
};

export function DocRelated({ entry, onSelectDoc }: DocRelatedProps) {
  const relatedDocs = entry.relatedDocIds
    .map((id) => DOC_CATALOG.find((d) => d.id === id))
    .filter((d): d is DocEntry => Boolean(d));

  if (!relatedDocs.length && !entry.relatedRoutes.length) return null;

  return (
    <section className="mt-10 border-t pt-6" aria-labelledby="related-docs-heading">
      <h2 id="related-docs-heading" className="mb-3 text-sm font-semibold">
        Related Documents
      </h2>
      <ul className="flex flex-wrap gap-2">
        {relatedDocs.map((d) => (
          <li key={d.id}>
            <Button type="button" size="sm" variant="outline" onClick={() => onSelectDoc(d.id)}>
              {d.title}
            </Button>
          </li>
        ))}
        {entry.relatedRoutes.map((r) => (
          <li key={r.href}>
            <Button size="sm" variant="secondary" asChild>
              <Link href={r.href}>{r.label}</Link>
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}

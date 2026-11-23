import { slugifyHeading } from "@/lib/markdown";

export type TocHeading = {
  id: string;
  text: string;
  level: number;
};

const HEADING_RE = /^(#{1,6})\s+(.+?)\s*$/;

export { slugifyHeading };

export function extractHeadings(markdown: string): TocHeading[] {
  if (!markdown.trim()) return [];
  const seen = new Map<string, number>();
  const headings: TocHeading[] = [];

  for (const line of markdown.split("\n")) {
    // Skip fenced code blocks roughly
    if (line.trim().startsWith("```")) continue;
    const m = line.match(HEADING_RE);
    if (!m) continue;
    const level = m[1].length;
    const text = m[2].replace(/#+\s*$/, "").trim();
    if (!text) continue;
    let id = slugifyHeading(text) || "section";
    const n = seen.get(id) ?? 0;
    seen.set(id, n + 1);
    if (n > 0) id = `${id}-${n}`;
    headings.push({ id, text, level });
  }
  return headings;
}

export function wordCount(markdown: string): number {
  const plain = markdown
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`[^`]+`/g, " ")
    .replace(/!\[[^\]]*\]\([^)]+\)/g, " ")
    .replace(/\[[^\]]*\]\([^)]+\)/g, " ")
    .replace(/[#>*_\-|]/g, " ")
    .trim();
  if (!plain) return 0;
  return plain.split(/\s+/).filter(Boolean).length;
}

/** ~200 wpm reading estimate */
export function readingTimeMinutes(words: number): number {
  return Math.max(1, Math.ceil(words / 200));
}

export type DocSearchHit = {
  docId: string;
  title: string;
  kind: "document" | "heading";
  headingId?: string;
  headingText?: string;
  snippet?: string;
};

export function searchDocumentation(
  docs: { id: string; title: string; content: string }[],
  query: string,
  limit = 40,
): DocSearchHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const hits: DocSearchHit[] = [];

  for (const doc of docs) {
    if (doc.title.toLowerCase().includes(q)) {
      hits.push({ docId: doc.id, title: doc.title, kind: "document" });
    }
    for (const h of extractHeadings(doc.content)) {
      if (h.text.toLowerCase().includes(q)) {
        hits.push({
          docId: doc.id,
          title: doc.title,
          kind: "heading",
          headingId: h.id,
          headingText: h.text,
        });
      }
    }
    if (doc.content.toLowerCase().includes(q)) {
      const idx = doc.content.toLowerCase().indexOf(q);
      const start = Math.max(0, idx - 40);
      const snippet = doc.content.slice(start, start + 100).replace(/\s+/g, " ");
      if (!hits.some((h) => h.docId === doc.id && h.kind === "document")) {
        hits.push({
          docId: doc.id,
          title: doc.title,
          kind: "document",
          snippet: (start > 0 ? "…" : "") + snippet + "…",
        });
      }
    }
    if (hits.length >= limit) break;
  }
  return hits.slice(0, limit);
}

/** Highlight query matches inside plain text for search UI */
export function splitHighlight(text: string, query: string): { text: string; match: boolean }[] {
  const q = query.trim();
  if (!q) return [{ text, match: false }];
  const lower = text.toLowerCase();
  const ql = q.toLowerCase();
  const parts: { text: string; match: boolean }[] = [];
  let i = 0;
  while (i < text.length) {
    const at = lower.indexOf(ql, i);
    if (at === -1) {
      parts.push({ text: text.slice(i), match: false });
      break;
    }
    if (at > i) parts.push({ text: text.slice(i, at), match: false });
    parts.push({ text: text.slice(at, at + q.length), match: true });
    i = at + q.length;
  }
  return parts;
}

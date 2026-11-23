/** Shared markdown helpers (safe for components outside features/). */

export function slugifyHeading(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/<[^>]+>/g, "")
    .replace(/[`*_~[\]]/g, "")
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

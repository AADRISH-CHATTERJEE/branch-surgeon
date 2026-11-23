import { STORAGE_KEYS } from "@/lib/constants";

function readJsonArray(key: string): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function writeJsonArray(key: string, value: string[]) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* ignore */
  }
}

export function getFavoriteDocIds(): string[] {
  return readJsonArray(STORAGE_KEYS.docsFavorites);
}

export function toggleFavoriteDocId(id: string): string[] {
  const cur = getFavoriteDocIds();
  const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
  writeJsonArray(STORAGE_KEYS.docsFavorites, next);
  return next;
}

export function getRecentDocIds(): string[] {
  return readJsonArray(STORAGE_KEYS.docsRecent);
}

export function pushRecentDocId(id: string, limit = 8): string[] {
  const next = [id, ...getRecentDocIds().filter((x) => x !== id)].slice(0, limit);
  writeJsonArray(STORAGE_KEYS.docsRecent, next);
  return next;
}

export function getCollapsedCategories(): string[] {
  return readJsonArray(STORAGE_KEYS.docsNavCollapsed);
}

export function setCollapsedCategories(ids: string[]) {
  writeJsonArray(STORAGE_KEYS.docsNavCollapsed, ids);
}

export function getLastOpenedDocId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const id = localStorage.getItem(STORAGE_KEYS.docsLastOpened);
    return id && id.trim() ? id : null;
  } catch {
    return null;
  }
}

export function setLastOpenedDocId(id: string): void {
  try {
    localStorage.setItem(STORAGE_KEYS.docsLastOpened, id);
  } catch {
    /* ignore */
  }
}

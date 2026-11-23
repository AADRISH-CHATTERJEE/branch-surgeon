/** Canonical list fetch sizes — callers slice via React Query `select` for smaller views. */

export const REVIEWS_FETCH_LIMIT = 100;
export const RECOMMENDATIONS_FETCH_LIMIT = 200;
export const ACTIVITY_FETCH_LIMIT = 200;

/** Virtualize tables / lists above this row count. */
export const VIRTUALIZE_ROW_THRESHOLD = 40;
export const VIRTUAL_ROW_HEIGHT = 40;

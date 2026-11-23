import type { ApiResponse } from "@/types/api";
import { ApiError } from "@/services/errors";

const DEFAULT_API_URL = "http://127.0.0.1:8741";

export type ApiClientOptions = {
  baseUrl?: string;
  repoRoot?: string | null;
  orgId?: string | null;
  teamId?: string | null;
  signal?: AbortSignal;
  /** UI hydration flag — never forwarded to fetch. */
  hydrated?: boolean;
};

function resolveBaseUrl(override?: string): string {
  if (override) return override.replace(/\/$/, "");
  if (typeof process !== "undefined" && process.env.NEXT_PUBLIC_REFACTORY_API_URL) {
    return process.env.NEXT_PUBLIC_REFACTORY_API_URL.replace(/\/$/, "");
  }
  return DEFAULT_API_URL;
}

/** Like {@link apiRequest} but also returns response `meta` (for optimistic UI sync). */
export async function apiRequestWithMeta<T>(
  path: string,
  init: RequestInit & ApiClientOptions = {},
): Promise<{ data: T; meta: Record<string, unknown>; message?: string }> {
  const {
    baseUrl,
    repoRoot,
    orgId,
    teamId,
    signal,
    headers,
    hydrated: _hydrated,
    ...rest
  } = init;
  const url = `${resolveBaseUrl(baseUrl)}${path.startsWith("/") ? path : `/${path}`}`;

  const mergedHeaders = new Headers(headers);
  if (!mergedHeaders.has("Accept")) {
    mergedHeaders.set("Accept", "application/json");
  }
  if (rest.body && !mergedHeaders.has("Content-Type")) {
    mergedHeaders.set("Content-Type", "application/json");
  }
  if (repoRoot) {
    mergedHeaders.set("X-Repo-Root", repoRoot);
  }
  if (orgId) {
    mergedHeaders.set("X-Org-Id", orgId);
  }
  if (teamId) {
    mergedHeaders.set("X-Team-Id", teamId);
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...rest,
      headers: mergedHeaders,
      signal,
    });
  } catch (cause) {
    throw new ApiError("Unable to reach the Local API", {
      status: 0,
      errors: ["Network error — is the API running on the configured host?"],
      cause,
    });
  }

  const rawText = await response.text();
  let payload: unknown = null;
  if (rawText.trim()) {
    try {
      payload = JSON.parse(rawText);
    } catch (cause) {
      throw new ApiError("Invalid JSON from Local API", {
        status: response.status,
        errors: [`HTTP ${response.status}: non-JSON body`],
        body: { raw: rawText.slice(0, 2000) },
        cause,
      });
    }
  }

  const envelope = (payload ?? {}) as ApiResponse<T> & {
    detail?: unknown;
  };
  const detailMessage = formatFastApiDetail(envelope?.detail);
  const bodyRecord =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {
          status: "error",
          message: `Request failed (${response.status})`,
          errors: [`HTTP ${response.status}: empty response body`],
          meta: {},
        };

  if (!response.ok || envelope?.status === "error") {
    const errorsFromBody = Array.isArray(envelope?.errors)
      ? envelope.errors.filter((e): e is string => typeof e === "string" && e.trim().length > 0)
      : [];
    const message =
      (typeof envelope?.message === "string" && envelope.message.trim()) ||
      detailMessage ||
      errorsFromBody[0] ||
      `Request failed (${response.status})`;
    const errors =
      errorsFromBody.length > 0
        ? errorsFromBody
        : detailMessage
          ? [detailMessage]
          : [message];
    throw new ApiError(message, {
      status: response.status,
      errors,
      meta:
        envelope?.meta && typeof envelope.meta === "object"
          ? (envelope.meta as Record<string, unknown>)
          : {},
      body: {
        status: (bodyRecord.status as string) || "error",
        message,
        errors,
        data: bodyRecord.data ?? null,
        meta: bodyRecord.meta ?? {},
        ...(detailMessage && !errorsFromBody.length ? { detail: envelope.detail } : {}),
      },
    });
  }

  return {
    data: envelope.data as T,
    meta:
      envelope.meta && typeof envelope.meta === "object"
        ? (envelope.meta as Record<string, unknown>)
        : {},
    message: typeof envelope.message === "string" ? envelope.message : undefined,
  };
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit & ApiClientOptions = {},
): Promise<T> {
  const result = await apiRequestWithMeta<T>(path, init);
  return result.data;
}

/** Normalize FastAPI `{ detail }` / validation-error payloads into a string. */
function formatFastApiDetail(detail: unknown): string | null {
  if (detail == null) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const loc = Array.isArray((item as { loc?: unknown }).loc)
            ? (item as { loc: unknown[] }).loc.join(".")
            : "";
          const msg = String((item as { msg: unknown }).msg);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return null;
      })
      .filter(Boolean);
    return parts.length ? parts.join("; ") : null;
  }
  if (typeof detail === "object") return JSON.stringify(detail);
  return String(detail);
}

export function getDefaultApiUrl(): string {
  return resolveBaseUrl();
}

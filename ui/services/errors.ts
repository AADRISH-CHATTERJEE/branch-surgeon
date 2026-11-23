/** Typed errors from the Local API client. */

export class ApiError extends Error {
  readonly status: number;
  readonly errors: string[];
  readonly meta: Record<string, unknown>;
  /** Full parsed response body when available. */
  readonly body: Record<string, unknown>;

  constructor(
    message: string,
    options: {
      status?: number;
      errors?: string[];
      meta?: Record<string, unknown>;
      body?: Record<string, unknown>;
      cause?: unknown;
    } = {},
  ) {
    super(message, { cause: options.cause });
    this.name = "ApiError";
    this.status = options.status ?? 0;
    this.errors = options.errors ?? [];
    this.meta = options.meta ?? {};
    this.body = options.body ?? {
      status: "error",
      message: message,
      errors: this.errors,
      meta: this.meta,
    };
  }

  get isNetwork(): boolean {
    return this.status === 0;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  get isClient(): boolean {
    return this.status >= 400 && this.status < 500;
  }

  /** Prefer first errors[] entry, then message — never a bare generic label. */
  get displayMessage(): string {
    const first = this.errors.find((e) => typeof e === "string" && e.trim());
    if (first) return first.trim();
    const msg = (this.message || "").trim();
    return msg || "Request failed";
  }
}

/** Resolve a user-facing API error string from unknown catch values. */
export function formatApiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.displayMessage;
  if (err instanceof Error && err.message.trim()) return err.message.trim();
  return fallback;
}

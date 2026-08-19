/** Normalizes every backend failure into one frontend-safe shape.
 *
 * The backend already returns clean, typed errors (see Sprint 9I's
 * error-response audit: 401/403/404/422/500 all come back as
 * `{"detail": "..."}` or FastAPI's validation-error array — never a
 * stack trace, a SQL error, or a credential). This module's only job
 * is to turn that into one consistent shape the UI can render without
 * every call site re-parsing `response.json()` itself.
 */

export interface ApiError {
  status: number;
  message: string;
  code?: string;
  details?: string[];
}

/** FastAPI's 422 shape: `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`. */
interface ValidationErrorBody {
  detail: Array<{ loc?: unknown[]; msg?: string; type?: string }>;
}

/** The common shape for every other error: `{"detail": "..."}`. */
interface SimpleErrorBody {
  detail: string;
}

function isValidationErrorBody(value: unknown): value is ValidationErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as { detail?: unknown }).detail)
  );
}

function isSimpleErrorBody(value: unknown): value is SimpleErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { detail?: unknown }).detail === "string"
  );
}

/** Build an `ApiError` from a failed `Response`. Never throws — a
 * response body that doesn't parse as JSON, or doesn't match either
 * known shape, still produces a safe, generic message rather than
 * leaking whatever the body actually contained. */
export async function parseApiError(response: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (isValidationErrorBody(body)) {
    const details = body.detail
      .map((item) => item.msg)
      .filter((msg): msg is string => Boolean(msg));
    return {
      status: response.status,
      message: details[0] ?? "The request could not be validated.",
      code: "validation_error",
      details,
    };
  }

  if (isSimpleErrorBody(body)) {
    return { status: response.status, message: body.detail };
  }

  return {
    status: response.status,
    message: genericMessageFor(response.status),
  };
}

function genericMessageFor(status: number): string {
  switch (status) {
    case 401:
      return "Your session has expired. Please log in again.";
    case 403:
      return "You do not have access to this resource.";
    case 404:
      return "The requested resource was not found.";
    case 429:
      return "Too many requests. Please try again shortly.";
    default:
      return status >= 500
        ? "The server encountered a problem. Please try again."
        : "The request could not be completed.";
  }
}

export function isApiError(value: unknown): value is ApiError {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ApiError).status === "number" &&
    typeof (value as ApiError).message === "string"
  );
}

/** A human-readable message for anything a service function might
 * throw — an `ApiError`, a network-level `TypeError` from `fetch`, or
 * something unexpected. Always safe to render directly. */
export function messageFor(error: unknown): string {
  if (isApiError(error)) return error.message;
  if (error instanceof TypeError) {
    return "Could not reach the server. Check your connection.";
  }
  return "An unexpected error occurred.";
}

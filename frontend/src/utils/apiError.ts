/**
 * Turn an axios error into something a person can act on.
 *
 * The pattern this replaces is `err.response?.data?.detail || 'Failed to ...'`,
 * which is right for the common case and silently useless for the three that
 * matter most:
 *
 *   A 500 has no `detail`, so it falls through to the generic message. That is
 *   how "Failed to save provider" came to be shown for a missing database
 *   column, sending everyone looking at the form instead of the server.
 *
 *   A 422 has `detail` as an ARRAY of objects, which renders as
 *   "[object Object]".
 *
 *   A request that never completed has no `response` at all, and reads
 *   identically to a request the server rejected.
 *
 * The status code is always included. Even when nothing else can be said, "HTTP
 * 500" and "HTTP 400" send you to completely different places.
 */

interface ValidationItem {
  loc?: (string | number)[];
  msg?: string;
}

export function describeApiError(error: any, fallback: string): string {
  // No response: DNS, TLS, a dropped connection, or the request was blocked.
  if (!error?.response) {
    const reason = error?.message ? `: ${error.message}` : '';
    return `${fallback}. The server could not be reached${reason}.`;
  }

  const status = error.response.status;
  const detail = error.response.data?.detail;

  // FastAPI validation failures arrive as [{loc: [...], msg: "..."}].
  if (Array.isArray(detail)) {
    const parts = (detail as ValidationItem[]).map((item) => {
      const field = Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : null;
      const message = item?.msg ?? 'invalid value';
      return field ? `${field}: ${message}` : message;
    });
    return `${fallback} (HTTP ${status}): ${parts.join('; ')}`;
  }

  if (typeof detail === 'string' && detail.trim()) {
    return `${detail} (HTTP ${status})`;
  }

  // A 5xx is the server's fault. Saying so stops people editing the form in
  // the hope that something different will happen.
  if (status >= 500) {
    return `${fallback}: the server returned HTTP ${status}. This is a server-side `
      + `fault rather than a problem with what you entered. The application logs `
      + `will have the underlying error.`;
  }

  return `${fallback} (HTTP ${status}).`;
}

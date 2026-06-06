/**
 * Shareable-URL encoding for simulation parameters.
 *
 * Encodes only the fields that differ from DEFAULT_PARAMS into a compact
 * base64url string, keeping shared links short. Decoding merges the diff back
 * onto DEFAULT_PARAMS so links stay forward-compatible when new fields are
 * added (missing keys fall back to their defaults).
 */
import { DEFAULT_PARAMS, type FormParams } from "./types";

/** Query-string key carrying the encoded parameter diff. */
export const SHARE_PARAM_KEY = "s";

/** Deep equality for the plain-JSON values that make up FormParams. */
function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null) return false;
  if (typeof a !== "object") return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((v, i) => deepEqual(v, b[i]));
  }
  const ao = a as Record<string, unknown>;
  const bo = b as Record<string, unknown>;
  const keys = new Set([...Object.keys(ao), ...Object.keys(bo)]);
  for (const k of keys) {
    if (!deepEqual(ao[k], bo[k])) return false;
  }
  return true;
}

/** base64url encode a UTF-8 string (URL-safe, no padding). */
function toBase64Url(s: string): string {
  const b64 = btoa(unescape(encodeURIComponent(s)));
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Inverse of toBase64Url. */
function fromBase64Url(s: string): string {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/");
  return decodeURIComponent(escape(atob(b64)));
}

/** Encode the non-default fields of `params` into a compact base64url token. */
export function encodeParams(params: FormParams): string {
  const diff: Record<string, unknown> = {};
  const def = DEFAULT_PARAMS as unknown as Record<string, unknown>;
  const cur = params as unknown as Record<string, unknown>;
  for (const key of Object.keys(cur)) {
    if (!deepEqual(cur[key], def[key])) diff[key] = cur[key];
  }
  return toBase64Url(JSON.stringify(diff));
}

/**
 * Decode a token produced by `encodeParams` back into a full FormParams,
 * merging the diff onto DEFAULT_PARAMS. Returns null on malformed input.
 */
export function decodeParams(token: string): FormParams | null {
  try {
    const parsed = JSON.parse(fromBase64Url(token));
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return null;
    }
    return { ...DEFAULT_PARAMS, ...(parsed as Partial<FormParams>) };
  } catch {
    return null;
  }
}

/** Build a full shareable URL for the given params on the current page. */
export function buildShareUrl(params: FormParams): string {
  const token = encodeParams(params);
  const { origin, pathname } = window.location;
  return `${origin}${pathname}?${SHARE_PARAM_KEY}=${token}`;
}

/**
 * Read and consume a shared token from the current URL, if present.
 * Returns the decoded params, or null if absent/invalid. On success the token
 * is stripped from the address bar so a later edit + refresh isn't overridden.
 */
export function consumeSharedParams(): FormParams | null {
  if (typeof window === "undefined") return null;
  const url = new URL(window.location.href);
  const token = url.searchParams.get(SHARE_PARAM_KEY);
  if (!token) return null;
  const decoded = decodeParams(token);
  url.searchParams.delete(SHARE_PARAM_KEY);
  window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  return decoded;
}

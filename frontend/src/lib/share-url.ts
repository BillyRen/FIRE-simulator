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

/** localStorage key holding the shared FormParams object. */
const PARAMS_STORAGE_KEY = "fire:params";

/**
 * Per-page localStorage keys that independently persist the headline
 * portfolio / withdrawal controls (each page syncs these into ParamsContext,
 * so they are the source of truth for those two fields and must be seeded too).
 */
const PAGE_PORTFOLIO_KEYS = [
  "fire:main:portfolio",
  "fire:sensitivity:portfolio",
  "fire:guardrail:portfolio",
  "fire:allocation:portfolio",
];
const PAGE_WITHDRAWAL_KEYS = [
  "fire:main:withdrawal",
  "fire:sensitivity:withdrawal",
  "fire:guardrail:withdrawal",
  "fire:allocation:withdrawal",
];

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

type TypeTag = "array" | "object" | "number" | "string" | "boolean" | "other";

function typeTag(v: unknown): TypeTag {
  if (Array.isArray(v)) return "array";
  if (v === null) return "other";
  const t = typeof v;
  if (t === "object") return "object";
  if (t === "number") return "number";
  if (t === "string") return "string";
  if (t === "boolean") return "boolean";
  return "other";
}

/** Merge only the finite-number subkeys of `src` onto a copy of `base`. */
function mergeNumericObject(
  base: Record<string, unknown>,
  src: Record<string, unknown>,
): Record<string, unknown> {
  const out = { ...base };
  for (const k of Object.keys(base)) {
    const v = src[k];
    if (typeof v === "number" && Number.isFinite(v)) out[k] = v;
  }
  return out;
}

/**
 * Validate an untrusted parsed diff against the DEFAULT_PARAMS schema, keeping
 * only type-compatible fields. Nested objects (allocation, expense ratios,
 * glide-path allocation) are merged subkey-by-subkey so they always retain a
 * full numeric shape; cash_flows is kept only as an array of plain objects.
 * Unknown keys and mismatched types are dropped — a crafted token can never
 * smuggle a value of the wrong shape into the UI.
 */
function sanitizeParamsDiff(parsed: Record<string, unknown>): Partial<FormParams> {
  const def = DEFAULT_PARAMS as unknown as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(def)) {
    if (!(key in parsed)) continue;
    const dTag = typeTag(def[key]);
    const pVal = parsed[key];
    if (typeTag(pVal) !== dTag) continue;
    if (dTag === "object") {
      out[key] = mergeNumericObject(
        def[key] as Record<string, unknown>,
        pVal as Record<string, unknown>,
      );
    } else if (dTag === "array") {
      const arr = pVal as unknown[];
      if (arr.every((el) => typeTag(el) === "object")) out[key] = arr;
    } else if (dTag === "number") {
      if (Number.isFinite(pVal as number)) out[key] = pVal;
    } else {
      out[key] = pVal;
    }
  }
  return out as Partial<FormParams>;
}

/**
 * Decode a token produced by `encodeParams` back into a full FormParams,
 * merging a sanitized diff onto DEFAULT_PARAMS. Returns null on malformed input.
 */
export function decodeParams(token: string): FormParams | null {
  try {
    const parsed = JSON.parse(fromBase64Url(token));
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return null;
    }
    return { ...DEFAULT_PARAMS, ...sanitizeParamsDiff(parsed as Record<string, unknown>) };
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
 * Consume a shared token from the current URL, if present, by seeding
 * localStorage *before* any usePersistedState hook hydrates.
 *
 * This must run synchronously during the first render of the params provider
 * (not in an effect): each page keeps its own `fire:<page>:portfolio` /
 * `:withdrawal` state that it syncs into ParamsContext, so simply setting
 * ParamsContext would be clobbered by those page-level values. By pre-writing
 * the shared FormParams plus every page's portfolio/withdrawal key here, all
 * consumers pick up the shared scenario through their normal hydration with no
 * race. The token is stripped from the address bar so a later edit + refresh
 * isn't re-overridden. Returns the decoded params (for an immediate
 * setParams), or null when absent/invalid.
 */
export function consumeSharedParams(): FormParams | null {
  if (typeof window === "undefined") return null;
  const url = new URL(window.location.href);
  const token = url.searchParams.get(SHARE_PARAM_KEY);
  if (!token) return null;
  const decoded = decodeParams(token);
  url.searchParams.delete(SHARE_PARAM_KEY);
  window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  if (!decoded) return null;
  try {
    localStorage.setItem(PARAMS_STORAGE_KEY, JSON.stringify(decoded));
    const portfolio = JSON.stringify(decoded.initial_portfolio);
    const withdrawal = JSON.stringify(decoded.annual_withdrawal);
    for (const k of PAGE_PORTFOLIO_KEYS) localStorage.setItem(k, portfolio);
    for (const k of PAGE_WITHDRAWAL_KEYS) localStorage.setItem(k, withdrawal);
  } catch {
    /* quota / disabled storage — ParamsContext setParams still applies most fields */
  }
  return decoded;
}

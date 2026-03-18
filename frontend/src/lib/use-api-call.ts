"use client";

import { useState, useCallback, useRef } from "react";
import type { ProgressEvent } from "./api";

export interface ProgressInfo {
  stage: string;
  pct: number;
  current?: number;
  total?: number;
}

/**
 * Generic hook for API calls with loading/error/progress state management.
 * Handles request deduplication (ignores concurrent calls).
 */
export function useApiCall<TReq, TRes>(
  apiFn: (req: TReq, onProgress?: (evt: ProgressEvent) => void) => Promise<TRes>,
) {
  const [data, setData] = useState<TRes | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressInfo | null>(null);
  const inflight = useRef(false);

  const run = useCallback(
    async (req: TReq, opts?: { onSuccess?: (res: TRes) => void; onBefore?: () => void }) => {
      if (inflight.current) return;
      inflight.current = true;
      setLoading(true);
      setError(null);
      setProgress(null);
      opts?.onBefore?.();
      try {
        const res = await apiFn(req, setProgress);
        setData(res);
        opts?.onSuccess?.(res);
        return res;
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Unknown error";
        setError(msg);
        return undefined;
      } finally {
        setLoading(false);
        setProgress(null);
        inflight.current = false;
      }
    },
    [apiFn],
  );

  const reset = useCallback(() => {
    setData(null);
    setError(null);
  }, []);

  return { data, loading, error, progress, run, reset, setData, setError, isInflight: inflight } as const;
}

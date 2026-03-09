"use client";

import { useState, useCallback, useRef } from "react";

/**
 * Generic hook for API calls with loading/error state management.
 * Handles request deduplication (ignores concurrent calls).
 */
export function useApiCall<TReq, TRes>(
  apiFn: (req: TReq) => Promise<TRes>,
) {
  const [data, setData] = useState<TRes | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inflight = useRef(false);

  const run = useCallback(
    async (req: TReq, opts?: { onSuccess?: (res: TRes) => void; onBefore?: () => void }) => {
      if (inflight.current) return;
      inflight.current = true;
      setLoading(true);
      setError(null);
      opts?.onBefore?.();
      try {
        const res = await apiFn(req);
        setData(res);
        opts?.onSuccess?.(res);
        return res;
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Unknown error";
        setError(msg);
        return undefined;
      } finally {
        setLoading(false);
        inflight.current = false;
      }
    },
    [apiFn],
  );

  const reset = useCallback(() => {
    setData(null);
    setError(null);
  }, []);

  return { data, loading, error, run, reset, setData, setError } as const;
}

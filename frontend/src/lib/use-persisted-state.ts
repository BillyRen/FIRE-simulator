"use client";

import { useState, useEffect, useRef, useCallback, type Dispatch, type SetStateAction } from "react";

export function usePersistedState<T>(
  key: string,
  defaultValue: T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(defaultValue);
  const defaultRef = useRef(defaultValue);
  useEffect(() => { defaultRef.current = defaultValue; }, [defaultValue]);

  // Whether this key has hydrated from localStorage yet. Writes that happen
  // BEFORE hydration (e.g. a child component's mount effect syncing stale
  // default values into a parent persisted state) must NOT be persisted —
  // otherwise they clobber the saved value that hydration is about to read,
  // and settings silently reset to defaults on full page reload.
  const hydratedRef = useRef(false);

  // Hydrate from localStorage after mount (avoids SSR hydration mismatch).
  // Also re-syncs if key changes at runtime.
  const prevKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (prevKeyRef.current === key) return;
    prevKeyRef.current = key;
    hydratedRef.current = false;
    try {
      const saved = localStorage.getItem(key);
      if (saved !== null) {
        const parsed = JSON.parse(saved);
        const def = defaultRef.current;
        if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
            && typeof def === "object" && def !== null) {
          setValue({ ...def, ...parsed } as T);
        } else {
          setValue(parsed);
        }
      } else {
        setValue(defaultRef.current);
      }
    } catch { /* ignore malformed / missing */ }
    hydratedRef.current = true;
  }, [key]);

  const setPersisted = useCallback<Dispatch<SetStateAction<T>>>(
    (action) => {
      // Capture at call time: a setter invoked before this key has hydrated is
      // a spurious pre-hydration write (e.g. a child mount effect) and must not
      // persist. Reading the ref inside the updater would be too late — the
      // hydration effect flips it true before the queued updater runs.
      const shouldPersist = hydratedRef.current;
      setValue((prev) => {
        const next =
          typeof action === "function"
            ? (action as (p: T) => T)(prev)
            : action;
        if (shouldPersist) {
          try {
            localStorage.setItem(key, JSON.stringify(next));
          } catch { /* quota exceeded etc. */ }
        }
        return next;
      });
    },
    [key],
  );

  return [value, setPersisted];
}

"use client";

import { useState, useEffect, useRef, useCallback, type Dispatch, type SetStateAction } from "react";

export function usePersistedState<T>(
  key: string,
  defaultValue: T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(defaultValue);
  const defaultRef = useRef(defaultValue);
  useEffect(() => { defaultRef.current = defaultValue; }, [defaultValue]);

  useEffect(() => {
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
      }
    } catch { /* ignore malformed / missing */ }
  }, [key]);

  const setPersisted = useCallback<Dispatch<SetStateAction<T>>>(
    (action) => {
      setValue((prev) => {
        const next =
          typeof action === "function"
            ? (action as (p: T) => T)(prev)
            : action;
        try {
          localStorage.setItem(key, JSON.stringify(next));
        } catch { /* quota exceeded etc. */ }
        return next;
      });
    },
    [key],
  );

  return [value, setPersisted];
}

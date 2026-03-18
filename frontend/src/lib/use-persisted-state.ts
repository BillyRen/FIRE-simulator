"use client";

import { useState, useEffect, useRef, useCallback, type Dispatch, type SetStateAction } from "react";

function readFromStorage<T>(key: string, defaultValue: T): T {
  if (typeof window === "undefined") return defaultValue;
  try {
    const saved = localStorage.getItem(key);
    if (saved !== null) {
      const parsed = JSON.parse(saved);
      if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
          && typeof defaultValue === "object" && defaultValue !== null) {
        return { ...defaultValue, ...parsed } as T;
      }
      return parsed;
    }
  } catch { /* ignore malformed / missing */ }
  return defaultValue;
}

export function usePersistedState<T>(
  key: string,
  defaultValue: T,
): [T, Dispatch<SetStateAction<T>>] {
  const defaultRef = useRef(defaultValue);
  useEffect(() => { defaultRef.current = defaultValue; }, [defaultValue]);

  const [value, setValue] = useState<T>(() => readFromStorage(key, defaultValue));

  // Re-sync if key changes (rare but possible)
  const prevKeyRef = useRef(key);
  useEffect(() => {
    if (prevKeyRef.current !== key) {
      prevKeyRef.current = key;
      setValue(readFromStorage(key, defaultRef.current));
    }
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

"use client";

import { useState, useEffect } from "react";

export function useIsMobile(breakpoint = 640) {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < breakpoint);
    check();
    let timer: ReturnType<typeof setTimeout>;
    const debouncedCheck = () => {
      clearTimeout(timer);
      timer = setTimeout(check, 150);
    };
    window.addEventListener("resize", debouncedCheck);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("resize", debouncedCheck);
    };
  }, [breakpoint]);
  return isMobile;
}

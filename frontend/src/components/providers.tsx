"use client";

import { ThemeProvider } from "next-themes";

/**
 * Client-side providers mounted in the root layout.
 * next-themes manages the `class` attribute on <html> (light/dark/system).
 */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      {children}
    </ThemeProvider>
  );
}

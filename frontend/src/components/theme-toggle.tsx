"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { useTranslations } from "next-intl";
import { Sun, Moon, Monitor } from "lucide-react";

const ORDER = ["system", "light", "dark"] as const;
type ThemeOption = (typeof ORDER)[number];

/** Cycles system → light → dark. Icon reflects the chosen mode. */
export function ThemeToggle() {
  const t = useTranslations("theme");
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // theme is only known on the client; render a placeholder until mounted to
  // avoid a hydration mismatch and layout shift. This one-shot mount flag is
  // the standard next-themes guard — intentionally a setState-in-effect.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setMounted(true), []);
  if (!mounted) {
    return (
      <span
        className="inline-flex h-7 w-7 shrink-0 rounded-md border"
        aria-hidden="true"
      />
    );
  }

  const current: ThemeOption =
    theme && (ORDER as readonly string[]).includes(theme)
      ? (theme as ThemeOption)
      : "system";
  const Icon = current === "light" ? Sun : current === "dark" ? Moon : Monitor;
  const next = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length];
  const label = `${t("toggle")}: ${t(current)}`;

  return (
    <button
      onClick={() => setTheme(next)}
      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border transition-colors hover:bg-accent"
      title={label}
      aria-label={label}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}

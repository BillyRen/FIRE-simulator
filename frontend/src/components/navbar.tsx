"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

export function Navbar() {
  const t = useTranslations("nav");
  const pathname = usePathname();
  const locale = useLocale();

  const NAV_ITEMS = [
    { href: "/", label: t("simulator") },
    { href: "/sensitivity", label: t("sensitivity") },
    { href: "/guardrail", label: t("guardrail") },
    { href: "/allocation", label: t("allocation") },
  ];

  const switchLocale = () => {
    const newLocale = locale === "zh" ? "en" : "zh";
    document.cookie = `locale=${newLocale};path=/;max-age=31536000`;
    window.location.reload();
  };

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex h-12 items-center px-3 sm:px-6 max-w-[1600px] mx-auto justify-between">
        <nav className="flex items-center gap-0.5 sm:gap-1 overflow-x-auto scrollbar-hide">
          {NAV_ITEMS.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "px-2 sm:px-3 py-1.5 rounded-md text-xs sm:text-sm font-medium transition-colors whitespace-nowrap",
                pathname === href
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent"
              )}
            >
              {label}
            </Link>
          ))}
        </nav>
        <button
          onClick={switchLocale}
          className="px-2 py-1 rounded-md text-xs font-medium border hover:bg-accent transition-colors shrink-0 ml-2"
        >
          {locale === "zh" ? "EN" : "中文"}
        </button>
      </div>
    </header>
  );
}

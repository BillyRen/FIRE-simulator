"use client";

import { useTranslations } from "next-intl";

export function Footer() {
  const t = useTranslations("footer");

  return (
    <footer className="border-t py-6 px-4 sm:px-6 mt-8">
      <div className="max-w-[1600px] mx-auto text-center space-y-1.5">
        <p className="text-xs text-muted-foreground">
          <span className="font-semibold">{t("brand")}</span>{" "}
          <span>{t("byLine")}</span>
          <span className="mx-2">·</span>
          <span>{t("copyright")}</span>
        </p>
        <p className="text-[11px] text-muted-foreground/70 max-w-xl mx-auto leading-relaxed">
          {t("disclaimer")}
        </p>
      </div>
    </footer>
  );
}

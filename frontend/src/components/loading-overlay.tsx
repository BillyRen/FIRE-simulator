"use client";

import { useTranslations } from "next-intl";

export function LoadingOverlay({ message }: { message?: string }) {
  const t = useTranslations("loading");
  return (
    <div className="flex flex-col items-center justify-center py-20">
      <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent mb-4" />
      <p className="text-sm text-muted-foreground">{message ?? t("default")}</p>
    </div>
  );
}

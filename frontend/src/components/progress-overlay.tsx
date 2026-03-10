"use client";

import { useTranslations } from "next-intl";

export interface ProgressInfo {
  stage: string;
  pct: number;
  current?: number;
  total?: number;
}

interface ProgressOverlayProps {
  message?: string;
  progress?: ProgressInfo | null;
}

export function ProgressOverlay({ message, progress }: ProgressOverlayProps) {
  const t = useTranslations("loading");

  let displayMessage: string;
  if (progress) {
    try {
      displayMessage =
        progress.current && progress.total
          ? t("stages." + progress.stage, {
              current: progress.current,
              total: progress.total,
            })
          : t("stages." + progress.stage);
    } catch {
      // Fallback if i18n key doesn't exist
      displayMessage = progress.stage;
    }
  } else {
    displayMessage = message ?? t("default");
  }

  return (
    <div className="flex flex-col items-center justify-center py-20">
      {progress ? (
        <div className="w-64 mb-4">
          <div className="h-2 bg-muted rounded-full overflow-hidden">
            <div
              className="h-full bg-primary rounded-full transition-all duration-500 ease-out"
              style={{ width: `${progress.pct}%` }}
            />
          </div>
          <p className="text-xs text-muted-foreground text-right mt-1">
            {progress.pct}%
          </p>
        </div>
      ) : (
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent mb-4" />
      )}
      <p className="text-sm text-muted-foreground">{displayMessage}</p>
    </div>
  );
}

// Backward-compatible alias
export { ProgressOverlay as LoadingOverlay };

"use client";

export function LoadingOverlay({ message = "模拟运行中…" }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20">
      <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent mb-4" />
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}

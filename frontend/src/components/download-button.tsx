"use client";

import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";

interface DownloadButtonProps {
  label: string;
  onClick: () => void;
  className?: string;
}

export function DownloadButton({ label, onClick, className = "" }: DownloadButtonProps) {
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={onClick}
      className={`h-7 text-xs gap-1 ${className}`}
    >
      <Download className="h-3.5 w-3.5" />
      {label}
    </Button>
  );
}

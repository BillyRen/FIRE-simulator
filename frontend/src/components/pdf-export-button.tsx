"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { FileDown, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { exportToPdf } from "@/lib/pdf-export";

interface PdfExportButtonProps {
  targetId: string;
  filename?: string;
}

export function PdfExportButton({ targetId, filename }: PdfExportButtonProps) {
  const t = useTranslations("common");
  const [exporting, setExporting] = useState(false);

  const handleExport = async () => {
    setExporting(true);
    try {
      await exportToPdf(targetId, filename);
    } finally {
      setExporting(false);
    }
  };

  return (
    <Button
      variant="outline"
      size="sm"
      className="h-7 text-xs gap-1"
      onClick={handleExport}
      disabled={exporting}
    >
      {exporting ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : (
        <FileDown className="h-3 w-3" />
      )}
      {t("exportPdf")}
    </Button>
  );
}

"use client";

import { useState, useRef, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Save, Upload, Download, Trash2, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { FormParams } from "@/lib/types";

interface SavedScenario {
  name: string;
  params: FormParams;
  createdAt: number;
}

const STORAGE_KEY = "fire:saved-scenarios";

function loadScenarios(): SavedScenario[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveScenarios(scenarios: SavedScenario[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(scenarios));
}

export function ScenarioManager({
  currentParams,
  onLoad,
}: {
  currentParams: FormParams;
  onLoad: (params: FormParams) => void;
}) {
  const t = useTranslations("scenarioManager");
  const [scenarios, setScenarios] = useState<SavedScenario[]>([]);
  useEffect(() => { setScenarios(loadScenarios()); }, []);
  const [saveName, setSaveName] = useState("");
  const [showSaveInput, setShowSaveInput] = useState(false);
  const [justSaved, setJustSaved] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleSave = () => {
    if (!saveName.trim()) return;
    const scenario: SavedScenario = {
      name: saveName.trim(),
      params: currentParams,
      createdAt: Date.now(),
    };
    const existing = scenarios.filter((s) => s.name !== scenario.name);
    const updated = [scenario, ...existing];
    saveScenarios(updated);
    setScenarios(updated);
    setSaveName("");
    setShowSaveInput(false);
    setJustSaved(true);
    setTimeout(() => setJustSaved(false), 1500);
  };

  const handleLoad = (name: string) => {
    const s = scenarios.find((sc) => sc.name === name);
    if (s) onLoad(s.params);
  };

  const handleDelete = (name: string) => {
    const updated = scenarios.filter((s) => s.name !== name);
    saveScenarios(updated);
    setScenarios(updated);
  };

  const handleExport = () => {
    const blob = new Blob([JSON.stringify(currentParams, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `fire-scenario-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const params = JSON.parse(reader.result as string) as FormParams;
        onLoad(params);
      } catch {
        /* ignore invalid JSON */
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1">
        {scenarios.length > 0 && (
          <Select onValueChange={handleLoad}>
            <SelectTrigger className="h-7 text-xs flex-1">
              <SelectValue placeholder={t("loadPlaceholder")} />
            </SelectTrigger>
            <SelectContent>
              {scenarios.map((s) => (
                <div key={s.name} className="flex items-center">
                  <SelectItem value={s.name} className="flex-1 text-xs">
                    {s.name}
                  </SelectItem>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(s.name);
                    }}
                    className="p-1 text-muted-foreground hover:text-destructive shrink-0"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </SelectContent>
          </Select>
        )}

        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2"
          onClick={() => setShowSaveInput(!showSaveInput)}
          title={t("save")}
        >
          {justSaved ? (
            <Check className="h-3.5 w-3.5 text-green-500" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
        </Button>

        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2"
          onClick={handleExport}
          title={t("export")}
        >
          <Download className="h-3.5 w-3.5" />
        </Button>

        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2"
          onClick={() => fileRef.current?.click()}
          title={t("import")}
        >
          <Upload className="h-3.5 w-3.5" />
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept=".json"
          className="hidden"
          onChange={handleImport}
        />
      </div>

      {showSaveInput && (
        <div className="flex gap-1">
          <Input
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
            placeholder={t("namePlaceholder")}
            className="h-7 text-xs flex-1"
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSave();
            }}
            autoFocus
          />
          <Button
            variant="default"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={handleSave}
            disabled={!saveName.trim()}
          >
            {t("save")}
          </Button>
        </div>
      )}
    </div>
  );
}

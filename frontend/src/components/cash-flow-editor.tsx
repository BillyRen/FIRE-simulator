"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { CashFlowItem } from "@/lib/types";

interface CashFlowEditorProps {
  value: CashFlowItem[];
  onChange: (items: CashFlowItem[]) => void;
}

const NEW_ITEM: CashFlowItem = {
  name: "",
  amount: 0,
  start_year: 1,
  duration: 10,
  inflation_adjusted: true,
};

/** 数字输入：string 中间状态 + onBlur 提交 */
function CfNumberInput({
  value,
  onChange,
  min,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
}) {
  const [display, setDisplay] = useState(String(value));

  useEffect(() => {
    setDisplay(String(value));
  }, [value]);

  const commit = () => {
    const parsed = parseFloat(display);
    if (isNaN(parsed)) {
      const fallback = min ?? 0;
      onChange(fallback);
      setDisplay(String(fallback));
    } else {
      const clamped = Math.max(min ?? -Infinity, parsed);
      onChange(clamped);
      setDisplay(String(clamped));
    }
  };

  return (
    <Input
      type="number"
      value={display}
      min={min}
      onChange={(e) => setDisplay(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
      }}
      className="h-8 text-sm"
    />
  );
}

export function CashFlowEditor({ value, onChange }: CashFlowEditorProps) {
  const t = useTranslations("cashFlow");
  const [items, setItems] = useState<CashFlowItem[]>(value);
  const [types, setTypes] = useState<("income" | "expense")[]>(
    value.map((item) => (item.amount < 0 ? "expense" : "income"))
  );

  const sync = (
    next: CashFlowItem[],
    nextTypes: ("income" | "expense")[]
  ) => {
    setItems(next);
    setTypes(nextTypes);
    onChange(next);
  };

  const add = () => {
    const newItem = { ...NEW_ITEM, name: t("defaultName", { n: items.length + 1 }) };
    sync([...items, newItem], [...types, "expense"]);
  };

  const remove = (i: number) => {
    sync(
      items.filter((_, idx) => idx !== i),
      types.filter((_, idx) => idx !== i)
    );
  };

  const update = (i: number, patch: Partial<CashFlowItem>) => {
    const copy = [...items];
    copy[i] = { ...copy[i], ...patch };
    sync(copy, types);
  };

  const setType = (i: number, type: "income" | "expense") => {
    const newTypes = [...types];
    newTypes[i] = type;
    const copy = [...items];
    const absAmt = Math.abs(copy[i].amount);
    copy[i] = { ...copy[i], amount: type === "expense" ? -absAmt : absAmt };
    sync(copy, newTypes);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label className="text-sm font-medium">{t("title")}</Label>
        <Button variant="outline" size="sm" onClick={add}>
          {t("add")}
        </Button>
      </div>

      {items.map((item, i) => (
        <div
          key={i}
          className="rounded-lg border bg-card p-3 space-y-2"
        >
          <div className="flex justify-between items-center">
            <span className="text-xs text-muted-foreground">#{i + 1}</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-destructive"
              onClick={() => remove(i)}
            >
              {t("delete")}
            </Button>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label className="text-xs">{t("name")}</Label>
              <Input
                value={item.name}
                onChange={(e) => update(i, { name: e.target.value })}
                className="h-8 text-sm"
              />
            </div>
            <div>
              <Label className="text-xs">{t("type")}</Label>
              <Select
                value={types[i] ?? "income"}
                onValueChange={(v) =>
                  setType(i, v as "income" | "expense")
                }
              >
                <SelectTrigger className="h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="income">{t("income")}</SelectItem>
                  <SelectItem value="expense">{t("expense")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2">
            <div>
              <Label className="text-xs">{t("amountLabel")}</Label>
              <CfNumberInput
                value={Math.abs(item.amount)}
                onChange={(abs) => {
                  const tp = types[i] ?? "income";
                  update(i, { amount: tp === "expense" ? -abs : abs });
                }}
                min={0}
              />
            </div>
            <div>
              <Label className="text-xs">{t("startYear")}</Label>
              <CfNumberInput
                value={item.start_year}
                onChange={(v) => update(i, { start_year: Math.round(v) })}
                min={1}
              />
            </div>
            <div>
              <Label className="text-xs">{t("duration")}</Label>
              <CfNumberInput
                value={item.duration}
                onChange={(v) => update(i, { duration: Math.round(v) })}
                min={1}
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Checkbox
              checked={item.inflation_adjusted}
              onCheckedChange={(checked) =>
                update(i, { inflation_adjusted: checked === true })
              }
            />
            <Label className="text-xs cursor-pointer">{t("inflationAdjusted")}</Label>
          </div>
        </div>
      ))}

      {items.length === 0 && (
        <p className="text-xs text-muted-foreground text-center py-2">
          {t("empty")}
        </p>
      )}
    </div>
  );
}

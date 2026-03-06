"use client";

import { useState, useEffect, useMemo } from "react";
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
  enabled: true,
};

function CfNumberInput({
  value,
  onChange,
  min,
  max,
  step,
  className,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  className?: string;
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
      let clamped = Math.max(min ?? -Infinity, parsed);
      if (max !== undefined) clamped = Math.min(max, clamped);
      onChange(clamped);
      setDisplay(String(clamped));
    }
  };

  return (
    <Input
      type="number"
      value={display}
      min={min}
      max={max}
      step={step}
      onChange={(e) => setDisplay(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
      }}
      className={className ?? "h-8 text-sm"}
    />
  );
}

function GroupNameInput({
  value,
  onCommit,
  className,
}: {
  value: string;
  onCommit: (v: string) => void;
  className?: string;
}) {
  const [display, setDisplay] = useState(value);

  useEffect(() => {
    setDisplay(value);
  }, [value]);

  const commit = () => {
    const trimmed = display.trim();
    if (trimmed && trimmed !== value) {
      onCommit(trimmed);
    } else {
      setDisplay(value);
    }
  };

  return (
    <Input
      value={display}
      onChange={(e) => setDisplay(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
      }}
      className={className ?? "h-7 text-xs w-28"}
    />
  );
}

function CashFlowCard({
  item,
  itemType,
  index,
  label,
  showProbability,
  t,
  onUpdate,
  onSetType,
  onRemove,
}: {
  item: CashFlowItem;
  itemType: "income" | "expense";
  index: number;
  label: string;
  showProbability: boolean;
  t: ReturnType<typeof useTranslations>;
  onUpdate: (patch: Partial<CashFlowItem>) => void;
  onSetType: (type: "income" | "expense") => void;
  onRemove: () => void;
}) {
  const enabled = item.enabled !== false;
  return (
    <div className="rounded-lg border bg-card p-3 space-y-2">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <Checkbox
            checked={enabled}
            onCheckedChange={(checked) => onUpdate({ enabled: checked === true })}
          />
          <span className="text-xs text-muted-foreground">{label}</span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-destructive"
          onClick={onRemove}
        >
          {t("delete")}
        </Button>
      </div>

      <div className={enabled ? "" : "opacity-40 pointer-events-none"}>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <Label className="text-xs">{t("name")}</Label>
            <Input
              value={item.name}
              onChange={(e) => onUpdate({ name: e.target.value })}
              className="h-8 text-sm"
            />
          </div>
          <div>
            <Label className="text-xs">{t("type")}</Label>
            <Select
              value={itemType}
              onValueChange={(v) => onSetType(v as "income" | "expense")}
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

        <div className={`grid ${showProbability ? "grid-cols-2" : "grid-cols-3"} gap-2 mt-2`}>
          <div>
            <Label className="text-xs">{t("amountLabel")}</Label>
            <CfNumberInput
              value={Math.abs(item.amount)}
              onChange={(abs) => {
                onUpdate({ amount: itemType === "expense" ? -abs : abs });
              }}
              min={0}
            />
          </div>
          {showProbability && (
            <div>
              <Label className="text-xs">{t("probability")}</Label>
              <CfNumberInput
                value={Math.round((item.probability ?? 1) * 100)}
                onChange={(v) => onUpdate({ probability: Math.round(v) / 100 })}
                min={1}
                max={100}
                step={1}
              />
            </div>
          )}
          <div>
            <Label className="text-xs">{t("startYear")}</Label>
            <CfNumberInput
              value={item.start_year}
              onChange={(v) => onUpdate({ start_year: Math.round(v) })}
              min={1}
            />
          </div>
          <div>
            <Label className="text-xs">{t("duration")}</Label>
            <CfNumberInput
              value={item.duration}
              onChange={(v) => onUpdate({ duration: Math.round(v) })}
              min={1}
            />
          </div>
        </div>

        <div className="flex items-center gap-2 mt-2">
          <Checkbox
            checked={item.inflation_adjusted}
            onCheckedChange={(checked) =>
              onUpdate({ inflation_adjusted: checked === true })
            }
          />
          <Label className="text-xs cursor-pointer">{t("inflationAdjusted")}</Label>
        </div>
      </div>
    </div>
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

  const remove = (i: number) => {
    sync(
      items.filter((_, idx) => idx !== i),
      types.filter((_, idx) => idx !== i)
    );
  };

  const addItem = () => {
    const newItem = { ...NEW_ITEM, name: t("defaultName", { n: items.length + 1 }) };
    sync([...items, newItem], [...types, "expense"]);
  };

  const nextGroupId = useMemo(() => {
    const groups = new Set(items.map((it) => it.group).filter(Boolean));
    let n = groups.size + 1;
    while (groups.has(`group_${n}`)) n++;
    return `group_${n}`;
  }, [items]);

  const addGroup = () => {
    const gid = nextGroupId;
    const v1: CashFlowItem = {
      ...NEW_ITEM,
      name: t("variant", { n: 1 }),
      group: gid,
      probability: 0.5,
    };
    const v2: CashFlowItem = {
      ...NEW_ITEM,
      name: t("variant", { n: 2 }),
      group: gid,
      probability: 0.5,
    };
    sync([...items, v1, v2], [...types, "income", "income"]);
  };

  const addVariant = (groupName: string) => {
    const groupItems = items.filter((it) => it.group === groupName);
    const variant: CashFlowItem = {
      ...NEW_ITEM,
      name: t("variant", { n: groupItems.length + 1 }),
      group: groupName,
      probability: 0.1,
    };
    sync([...items, variant], [...types, "income"]);
  };

  // Split into ungrouped and groups
  const ungroupedIndices: number[] = [];
  const groupMap = new Map<string, number[]>();

  items.forEach((item, i) => {
    if (item.group != null) {
      const arr = groupMap.get(item.group) ?? [];
      arr.push(i);
      groupMap.set(item.group, arr);
    } else {
      ungroupedIndices.push(i);
    }
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label className="text-sm font-medium">{t("title")}</Label>
        <div className="flex gap-1">
          <Button variant="outline" size="sm" onClick={addItem}>
            {t("add")}
          </Button>
          <Button variant="outline" size="sm" onClick={addGroup}>
            {t("addGroup")}
          </Button>
        </div>
      </div>

      {/* Ungrouped (deterministic) cash flows */}
      {ungroupedIndices.map((i) => (
        <CashFlowCard
          key={`cf-${i}`}
          item={items[i]}
          itemType={types[i] ?? "income"}
          index={i}
          label={`#${ungroupedIndices.indexOf(i) + 1}`}
          showProbability={false}
          t={t}
          onUpdate={(patch) => update(i, patch)}
          onSetType={(tp) => setType(i, tp)}
          onRemove={() => remove(i)}
        />
      ))}

      {/* Grouped (probabilistic) cash flows */}
      {Array.from(groupMap.entries()).map(([groupName, indices]) => {
        const totalProb = indices.reduce(
          (sum, i) => sum + (items[i].probability ?? 1),
          0
        );
        const overLimit = totalProb > 1.0 + 1e-9;
        const noneChance = Math.max(0, 1 - totalProb);

        return (
          <div
            key={`group-${indices[0]}`}
            className="rounded-xl border-2 border-dashed border-primary/30 p-3 space-y-2"
          >
            <div className="flex flex-wrap items-center justify-between gap-1">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <span className="text-xs font-semibold text-primary shrink-0">
                  {t("groupLabel")}
                </span>
                <GroupNameInput
                  value={groupName}
                  onCommit={(newName) => {
                    const copy = [...items];
                    indices.forEach((i) => {
                      copy[i] = { ...copy[i], group: newName };
                    });
                    sync(copy, types);
                  }}
                  className="h-7 text-xs min-w-0 flex-1"
                />
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-destructive text-xs shrink-0"
                onClick={() => {
                  const idxSet = new Set(indices);
                  sync(
                    items.filter((_, i) => !idxSet.has(i)),
                    types.filter((_, i) => !idxSet.has(i))
                  );
                }}
              >
                {t("deleteGroup")}
              </Button>
            </div>

            {indices.map((i, vi) => (
              <CashFlowCard
                key={`cf-${i}`}
                item={items[i]}
                itemType={types[i] ?? "income"}
                index={i}
                label={t("variant", { n: vi + 1 })}
                showProbability={true}
                t={t}
                onUpdate={(patch) => update(i, patch)}
                onSetType={(tp) => setType(i, tp)}
                onRemove={() => remove(i)}
              />
            ))}

            <div className="flex items-center justify-between px-1">
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-xs"
                onClick={() => addVariant(groupName)}
              >
                {t("addVariant")}
              </Button>
              <div className="text-xs text-muted-foreground">
                {t("totalProbability")}:{" "}
                <span className={overLimit ? "text-red-500 font-semibold" : ""}>
                  {Math.round(totalProb * 100)}%
                </span>
                {noneChance > 0.001 && !overLimit && (
                  <span className="ml-1">
                    ({t("noneChance", { pct: Math.round(noneChance * 100) })})
                  </span>
                )}
                {overLimit && (
                  <span className="ml-1 text-red-500">{t("probabilityExceeded")}</span>
                )}
              </div>
            </div>
          </div>
        );
      })}

      {items.length === 0 && (
        <p className="text-xs text-muted-foreground text-center py-2">
          {t("empty")}
        </p>
      )}
    </div>
  );
}

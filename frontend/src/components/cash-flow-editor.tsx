"use client";

import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, ChevronRight, X, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
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

function fmtAmount(n: number): string {
  return String(Math.round(Math.abs(n))).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

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

function CfTextInput({
  value,
  onChange: onCommit,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  className?: string;
}) {
  const [display, setDisplay] = useState(value);
  const composingRef = useRef(false);

  useEffect(() => {
    if (!composingRef.current) {
      setDisplay(value); // eslint-disable-line react-hooks/set-state-in-effect -- sync from parent prop for IME compat
    }
  }, [value]);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setDisplay(e.target.value);
      if (!composingRef.current) {
        onCommit(e.target.value);
      }
    },
    [onCommit]
  );

  const handleCompositionEnd = useCallback(
    (e: React.CompositionEvent<HTMLInputElement>) => {
      composingRef.current = false;
      onCommit((e.target as HTMLInputElement).value);
    },
    [onCommit]
  );

  return (
    <Input
      value={display}
      onChange={handleChange}
      onCompositionStart={() => {
        composingRef.current = true;
      }}
      onCompositionEnd={handleCompositionEnd}
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
  label,
  showProbability,
  expanded,
  t,
  onUpdate,
  onSetType,
  onRemove,
  onToggle,
}: {
  item: CashFlowItem;
  itemType: "income" | "expense";
  label: string;
  showProbability: boolean;
  expanded: boolean;
  t: ReturnType<typeof useTranslations>;
  onUpdate: (patch: Partial<CashFlowItem>) => void;
  onSetType: (type: "income" | "expense") => void;
  onRemove: () => void;
  onToggle: () => void;
}) {
  const enabled = item.enabled !== false;

  if (!expanded) {
    const endYear = item.start_year + item.duration - 1;
    const yearStr =
      item.duration === 1
        ? `Y${item.start_year}`
        : `Y${item.start_year}-${endYear}`;

    return (
      <div
        className={`rounded-lg border bg-card px-2.5 py-1.5 flex items-center gap-1.5 ${!enabled ? "opacity-50" : ""}`}
      >
        <Checkbox
          checked={enabled}
          onCheckedChange={(checked) =>
            onUpdate({ enabled: checked === true })
          }
          className="shrink-0"
        />
        <button
          type="button"
          onClick={onToggle}
          className="flex items-center gap-1.5 flex-1 min-w-0 text-left cursor-pointer"
        >
          <span className="text-xs font-medium truncate">
            {item.name || t("unnamed")}
          </span>
          <span
            className={`text-[10px] shrink-0 font-medium ${
              itemType === "income"
                ? "text-green-600 dark:text-green-400"
                : "text-red-500 dark:text-red-400"
            }`}
          >
            {itemType === "expense" ? "-" : "+"}${fmtAmount(item.amount)}
          </span>
          {showProbability && (
            <span className="text-[10px] text-muted-foreground shrink-0">
              {Math.round((item.probability ?? 1) * 100)}%
            </span>
          )}
          <span className="text-[10px] text-muted-foreground shrink-0">
            {yearStr}
          </span>
        </button>
        <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0 pointer-events-none" />
        <button
          type="button"
          onClick={onRemove}
          className="text-muted-foreground hover:text-destructive shrink-0 p-0.5 cursor-pointer"
        >
          <X className="h-3 w-3" />
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card p-3 space-y-2">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <Checkbox
            checked={enabled}
            onCheckedChange={(checked) =>
              onUpdate({ enabled: checked === true })
            }
          />
          <button
            type="button"
            onClick={onToggle}
            className="flex items-center gap-1 cursor-pointer"
          >
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground">{label}</span>
          </button>
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
            <CfTextInput
              value={item.name}
              onChange={(v) => onUpdate({ name: v })}
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

        <div
          className={`grid ${showProbability ? "grid-cols-2" : "grid-cols-3"} gap-2 mt-2`}
        >
          <div>
            <Label className="text-xs">
              {t("amountLabel")}{" "}
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button type="button" className="inline-flex items-center align-middle p-0 border-0 bg-transparent appearance-none" aria-label={item.inflation_adjusted ? t("amountHintReal") : t("amountHintNominal")}>
                      <Info className="h-3 w-3 text-muted-foreground cursor-help" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <p>{item.inflation_adjusted ? t("amountHintReal") : t("amountHintNominal")}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </Label>
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
                onChange={(v) =>
                  onUpdate({ probability: Math.round(v) / 100 })
                }
                min={1}
                max={100}
                step={1}
              />
            </div>
          )}
          <div>
            <Label className="text-xs">
              {t("cfStartYear")}{" "}
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button type="button" className="inline-flex items-center align-middle p-0 border-0 bg-transparent appearance-none" aria-label={t("cfStartYearHint")}>
                      <Info className="h-3 w-3 text-muted-foreground cursor-help" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <p>{t("cfStartYearHint")}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </Label>
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
          <Label className="text-xs cursor-pointer">
            {t("inflationAdjusted")}
          </Label>
          <div className="flex items-center gap-1 ml-auto">
            <Label className="text-xs text-muted-foreground whitespace-nowrap" title={item.inflation_adjusted ? t("growthRateHintReal") : t("growthRateHintNominal")}>
              {t("growthRate")}
            </Label>
            <CfNumberInput
              value={Math.round((item.growth_rate ?? 0) * 1000) / 10}
              onChange={(v) => onUpdate({ growth_rate: Math.round(v * 10) / 1000 })}
              min={-50}
              max={50}
              step={0.5}
              className="h-7 text-xs w-16"
            />
          </div>
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
  const [expandedCards, setExpandedCards] = useState<Set<number>>(new Set());
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
    new Set()
  );

  // Sync internal state when value prop changes externally (e.g. scenario load)
  // Using useState (not useRef) to track previous value — safe under concurrent rendering
  const [prevValue, setPrevValue] = useState(value);
  if (prevValue !== value) {
    setPrevValue(value);
    setItems(value);
    setTypes(value.map((item) => (item.amount < 0 ? "expense" : "income")));
  }

  const sync = (
    next: CashFlowItem[],
    nextTypes: ("income" | "expense")[]
  ) => {
    setPrevValue(next);
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
    setExpandedCards((prev) => {
      const next = new Set<number>();
      for (const idx of prev) {
        if (idx < i) next.add(idx);
        else if (idx > i) next.add(idx - 1);
      }
      return next;
    });
    sync(
      items.filter((_, idx) => idx !== i),
      types.filter((_, idx) => idx !== i)
    );
  };

  const removeGroup = (groupName: string, indices: number[]) => {
    const idxSet = new Set(indices);
    setExpandedCards((prev) => {
      const next = new Set<number>();
      for (const idx of prev) {
        if (idxSet.has(idx)) continue;
        const shift = indices.filter((r) => r < idx).length;
        next.add(idx - shift);
      }
      return next;
    });
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      next.delete(groupName);
      return next;
    });
    sync(
      items.filter((_, i) => !idxSet.has(i)),
      types.filter((_, i) => !idxSet.has(i))
    );
  };

  const toggleCard = (i: number) => {
    setExpandedCards((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  };

  const toggleGroup = (groupName: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupName)) next.delete(groupName);
      else next.add(groupName);
      return next;
    });
  };

  const addItem = () => {
    const newIdx = items.length;
    const newItem = {
      ...NEW_ITEM,
      name: t("defaultName", { n: items.length + 1 }),
    };
    setExpandedCards(new Set([newIdx]));
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
    setExpandedCards(new Set([items.length, items.length + 1]));
    setExpandedGroups(new Set([gid]));
    sync([...items, v1, v2], [...types, "income", "income"]);
  };

  const addVariant = (groupName: string) => {
    const newIdx = items.length;
    const groupItems = items.filter((it) => it.group === groupName);
    const uniqueNames = new Set(groupItems.map((it) => it.name));
    const variant: CashFlowItem = {
      ...NEW_ITEM,
      name: t("variant", { n: uniqueNames.size + 1 }),
      group: groupName,
      probability: 0.1,
    };
    setExpandedCards((prev) => new Set([...prev, newIdx]));
    sync([...items, variant], [...types, "income"]);
  };

  const addPhase = (groupName: string, variantName: string) => {
    const newIdx = items.length;
    const ref = items.find(
      (it) => it.group === groupName && it.name === variantName
    );
    const phase: CashFlowItem = {
      ...NEW_ITEM,
      name: variantName,
      group: groupName,
      probability: ref?.probability ?? 0.5,
    };
    setExpandedCards((prev) => new Set([...prev, newIdx]));
    sync([...items, phase], [...types, "expense"]);
  };

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

  const hasAnyExpanded = expandedCards.size > 0 || expandedGroups.size > 0;

  const toggleAll = () => {
    if (hasAnyExpanded) {
      setExpandedCards(new Set());
      setExpandedGroups(new Set());
    } else {
      setExpandedCards(new Set(items.map((_, i) => i)));
      setExpandedGroups(new Set(groupMap.keys()));
    }
  };

  return (
    <div className="space-y-2">
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

      {items.length > 1 && (
        <div className="flex justify-end -mt-1">
          <button
            type="button"
            onClick={toggleAll}
            className="text-[10px] text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          >
            {hasAnyExpanded ? t("collapseAll") : t("expandAll")}
          </button>
        </div>
      )}

      {ungroupedIndices.map((i) => (
        <CashFlowCard
          key={`cf-${i}`}
          item={items[i]}
          itemType={types[i] ?? "income"}
          label={`#${ungroupedIndices.indexOf(i) + 1}`}
          showProbability={false}
          expanded={expandedCards.has(i)}
          t={t}
          onUpdate={(patch) => update(i, patch)}
          onSetType={(tp) => setType(i, tp)}
          onRemove={() => remove(i)}
          onToggle={() => toggleCard(i)}
        />
      ))}

      {Array.from(groupMap.entries()).map(([groupName, indices]) => {
        const variantMap = new Map<string, number[]>();
        indices.forEach((i) => {
          const name = items[i].name;
          const arr = variantMap.get(name) ?? [];
          arr.push(i);
          variantMap.set(name, arr);
        });

        const variantProbs = new Map<string, number>();
        indices.forEach((i) => {
          const name = items[i].name;
          if (!variantProbs.has(name))
            variantProbs.set(name, items[i].probability ?? 1);
        });
        const totalProb = Array.from(variantProbs.values()).reduce(
          (a, b) => a + b,
          0
        );
        const overLimit = totalProb > 1.0 + 1e-9;
        const noneChance = Math.max(0, 1 - totalProb);
        const groupExpanded = expandedGroups.has(groupName);

        if (!groupExpanded) {
          return (
            <div
              key={`group-${indices[0]}`}
              className="rounded-xl border-2 border-dashed border-primary/30 px-3 py-2"
            >
              <div className="flex items-center justify-between gap-1">
                <button
                  type="button"
                  onClick={() => toggleGroup(groupName)}
                  className="flex items-center gap-1.5 flex-1 min-w-0 text-left cursor-pointer"
                >
                  <ChevronRight className="h-3.5 w-3.5 text-primary shrink-0" />
                  <span className="text-xs font-semibold text-primary shrink-0">
                    {t("groupLabel")}
                  </span>
                  <span className="text-xs truncate">{groupName}</span>
                  <span className="text-[10px] text-muted-foreground shrink-0">
                    {t("variantCount", { n: variantMap.size })} ·{" "}
                    {Math.round(totalProb * 100)}%
                  </span>
                </button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-destructive text-xs shrink-0"
                  onClick={() => removeGroup(groupName, indices)}
                >
                  {t("deleteGroup")}
                </Button>
              </div>
            </div>
          );
        }

        const variantEntries = Array.from(variantMap.entries());

        return (
          <div
            key={`group-${indices[0]}`}
            className="rounded-xl border-2 border-dashed border-primary/30 p-3 space-y-2"
          >
            <div className="flex flex-wrap items-center justify-between gap-1">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <button
                  type="button"
                  onClick={() => toggleGroup(groupName)}
                  className="shrink-0 cursor-pointer"
                >
                  <ChevronDown className="h-3.5 w-3.5 text-primary" />
                </button>
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
                    setExpandedGroups((prev) => {
                      if (!prev.has(groupName)) return prev;
                      const next = new Set(prev);
                      next.delete(groupName);
                      next.add(newName);
                      return next;
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
                onClick={() => removeGroup(groupName, indices)}
              >
                {t("deleteGroup")}
              </Button>
            </div>

            {variantEntries.map(([vname, vindices], vi) => {
              const isMultiPhase = vindices.length > 1;
              return (
                <div
                  key={`variant-${vindices[0]}`}
                  className={
                    isMultiPhase
                      ? "border-l-2 border-primary/20 pl-2 space-y-2"
                      : ""
                  }
                >
                  {vindices.map((i, pi) => (
                    <CashFlowCard
                      key={`cf-${i}`}
                      item={items[i]}
                      itemType={types[i] ?? "income"}
                      label={
                        isMultiPhase
                          ? t("phase", { n: pi + 1 })
                          : t("variant", { n: vi + 1 })
                      }
                      showProbability={pi === 0}
                      expanded={expandedCards.has(i)}
                      t={t}
                      onUpdate={(patch) => {
                        if (
                          "probability" in patch &&
                          patch.probability !== undefined
                        ) {
                          const copy = [...items];
                          vindices.forEach((j) => {
                            copy[j] = {
                              ...copy[j],
                              probability: patch.probability!,
                            };
                          });
                          copy[i] = { ...copy[i], ...patch };
                          sync(copy, types);
                        } else {
                          update(i, patch);
                        }
                      }}
                      onSetType={(tp) => setType(i, tp)}
                      onRemove={() => remove(i)}
                      onToggle={() => toggleCard(i)}
                    />
                  ))}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-5 px-2 text-[10px] text-muted-foreground"
                    onClick={() => addPhase(groupName, vname)}
                  >
                    {t("addPhase")}
                  </Button>
                </div>
              );
            })}

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
                <span
                  className={overLimit ? "text-red-500 font-semibold" : ""}
                >
                  {Math.round(totalProb * 100)}%
                </span>
                {noneChance > 0.001 && !overLimit && (
                  <span className="ml-1">
                    ({t("noneChance", { pct: Math.round(noneChance * 100) })})
                  </span>
                )}
                {overLimit && (
                  <span className="ml-1 text-red-500">
                    {t("probabilityExceeded")}
                  </span>
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

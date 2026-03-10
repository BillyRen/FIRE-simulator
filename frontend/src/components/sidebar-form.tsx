"use client";

import { useState, useEffect, useMemo, memo } from "react";
import { useTranslations, useLocale } from "next-intl";
import { Info, ChevronDown } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { CashFlowEditor } from "./cash-flow-editor";
import { ScenarioManager } from "./scenario-manager";
import { fetchCountries } from "@/lib/api";
import { DEFAULT_PARAMS } from "@/lib/types";
import type { FormParams, CountryInfo } from "@/lib/types";
import { countryFlag } from "@/lib/utils";

interface SidebarFormProps {
  params: FormParams;
  onChange: (params: FormParams) => void;
  showWithdrawalStrategy?: boolean;
  showAllocation?: boolean;
  hideRetirementAge?: boolean;
  children?: React.ReactNode;
}

function InfoTip({ text }: { text: string }) {
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Info className="h-3 w-3 text-muted-foreground cursor-help shrink-0" />
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-[220px] text-xs">
          {text}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step,
  suffix,
  help,
  tooltip,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
  help?: string;
  tooltip?: string;
}) {
  const t = useTranslations("sidebar");
  const [display, setDisplay] = useState(String(value));
  const [validationMsg, setValidationMsg] = useState<string>("");

  useEffect(() => {
    setDisplay(String(value));
  }, [value]);

  const commit = () => {
    const parsed = parseFloat(display);
    if (isNaN(parsed)) {
      const fallback = min ?? 0;
      onChange(fallback);
      setDisplay(String(fallback));
      setValidationMsg(t("adjustedTo", { value: fallback }));
      setTimeout(() => setValidationMsg(""), 3000);
    } else {
      const clamped =
        Math.min(max ?? Infinity, Math.max(min ?? -Infinity, parsed));
      if (clamped !== parsed) {
        setValidationMsg(t("adjustedToRange", { value: clamped, min: min ?? "-∞", max: max ?? "∞" }));
        setTimeout(() => setValidationMsg(""), 3000);
      } else {
        setValidationMsg("");
      }
      onChange(clamped);
      setDisplay(String(clamped));
    }
  };

  return (
    <div>
      <Label className="text-xs inline-flex items-center gap-1">
        {label}
        {tooltip && <InfoTip text={tooltip} />}
      </Label>
      <div className="flex items-center gap-1">
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
          className="h-8 text-sm"
        />
        {suffix && <span className="text-xs text-muted-foreground shrink-0">{suffix}</span>}
      </div>
      {help && <p className="text-[10px] text-muted-foreground mt-0.5">{help}</p>}
      {validationMsg && (
        <p className="text-[10px] text-amber-600 dark:text-amber-500 mt-0.5 animate-in fade-in duration-200">
          ⚠️ {validationMsg}
        </p>
      )}
    </div>
  );
}

function ModifiedDot() {
  return <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />;
}

function SectionTrigger({
  label,
  modified,
}: {
  label: string;
  modified: boolean;
}) {
  return (
    <AccordionTrigger className="text-sm font-semibold py-2">
      <span className="flex items-center gap-1.5">
        {label}
        {modified && <ModifiedDot />}
      </span>
    </AccordionTrigger>
  );
}

export const SidebarForm = memo(function SidebarForm({
  params,
  onChange,
  showWithdrawalStrategy = true,
  showAllocation = true,
  hideRetirementAge = false,
  children,
}: SidebarFormProps) {
  const t = useTranslations("sidebar");
  const locale = useLocale();
  const p = params;
  const set = <K extends keyof FormParams>(key: K, val: FormParams[K]) =>
    onChange({ ...p, [key]: val });

  const [showLifeExpectancy, setShowLifeExpectancy] = useState(false);
  const [countries, setCountries] = useState<CountryInfo[]>([]);
  useEffect(() => {
    fetchCountries(p.data_source).then(setCountries).catch(() => { /* non-critical init data */ });
  }, [p.data_source]);

  const countryName = (c: CountryInfo) =>
    locale === "zh" ? c.name_zh : c.name_en;

  const isModified = useMemo(() => {
    const check = (keys: (keyof FormParams)[]) =>
      keys.some(
        (k) => JSON.stringify(p[k]) !== JSON.stringify(DEFAULT_PARAMS[k])
      );
    return {
      dataRange: check(["data_source", "country", "pooling_method", "data_start_year"]),
      allocation: check(["allocation", "expense_ratios"]),
      simulation: check(["num_simulations", "min_block", "max_block"]),
      withdrawal: check(["withdrawal_strategy", "dynamic_ceiling", "dynamic_floor"]),
      leverage: check(["leverage", "borrowing_spread"]),
      cashFlows: p.cash_flows.length > 0,
    };
  }, [p]);

  const coreDefaults = ["allocation", ...(showWithdrawalStrategy ? ["withdrawal"] : []), "cashflow"];

  return (
    <div className="space-y-2">
      {!hideRetirementAge && (
        <div className="space-y-1.5">
          <NumberField
            label={t("retirementAge")}
            value={p.retirement_age}
            onChange={(v) => {
              onChange({ ...p, retirement_age: v, retirement_years: Math.max(1, p.life_expectancy - v) });
            }}
            min={18}
            max={p.life_expectancy - 1}
            step={1}
          />
          <p className="text-xs text-muted-foreground">
            {t("computedYears", { years: p.life_expectancy - p.retirement_age })}
            {" · "}
            <button
              type="button"
              className="inline-flex items-center gap-0.5 hover:text-foreground transition-colors"
              onClick={() => setShowLifeExpectancy(v => !v)}
            >
              {t("lifeExpectancy")}: {p.life_expectancy}
              <ChevronDown className={`h-3 w-3 transition-transform ${showLifeExpectancy ? "rotate-180" : ""}`} />
            </button>
          </p>
          {showLifeExpectancy && (
            <NumberField
              label={t("lifeExpectancy")}
              value={p.life_expectancy}
              onChange={(v) => {
                onChange({ ...p, life_expectancy: v, retirement_years: Math.max(1, v - p.retirement_age) });
              }}
              min={p.retirement_age + 1}
              max={120}
              step={1}
            />
          )}
        </div>
      )}

      {/* ── Core sections ── */}
      <Accordion type="multiple" defaultValue={coreDefaults}>
        {/* Asset Allocation */}
        <AccordionItem value="allocation">
          <SectionTrigger
            label={showAllocation ? t("assetAllocation") : t("assetExpenseRatio")}
            modified={isModified.allocation}
          />
          <AccordionContent>
            {showAllocation && (
              <>
                <div className="grid grid-cols-3 gap-2">
                  <NumberField
                    label={t("domesticStock")}
                    value={Math.round(p.allocation.domestic_stock * 100)}
                    onChange={(v) =>
                      set("allocation", { ...p.allocation, domestic_stock: v / 100 })
                    }
                    min={0}
                    max={100}
                  />
                  <NumberField
                    label={t("globalStock")}
                    value={Math.round(p.allocation.global_stock * 100)}
                    onChange={(v) =>
                      set("allocation", { ...p.allocation, global_stock: v / 100 })
                    }
                    min={0}
                    max={100}
                  />
                  <NumberField
                    label={t("domesticBond")}
                    value={Math.round(p.allocation.domestic_bond * 100)}
                    onChange={(v) =>
                      set("allocation", { ...p.allocation, domestic_bond: v / 100 })
                    }
                    min={0}
                    max={100}
                  />
                </div>
                {Math.abs(
                  p.allocation.domestic_stock + p.allocation.global_stock + p.allocation.domestic_bond - 1
                ) > 0.01 && (
                  <p className="text-[10px] text-red-500 mt-1">{t("allocationWarning")}</p>
                )}

                <div className="flex items-center gap-2 mt-3">
                  <input
                    type="checkbox"
                    checked={p.glide_path_enabled}
                    onChange={(e) => set("glide_path_enabled", e.target.checked)}
                    className="h-3.5 w-3.5"
                    id="glide-path-toggle"
                  />
                  <Label htmlFor="glide-path-toggle" className="text-xs cursor-pointer">
                    {t("glidePath")}
                  </Label>
                  <InfoTip text={t("glidePathHelp")} />
                </div>

                {p.glide_path_enabled && (
                  <div className="space-y-2 mt-2 pl-2 border-l-2 border-primary/20">
                    <p className="text-[10px] text-muted-foreground">{t("glidePathEnd")}</p>
                    <div className="grid grid-cols-3 gap-2">
                      <NumberField
                        label={t("domesticStock")}
                        value={Math.round(p.glide_path_end_allocation.domestic_stock * 100)}
                        onChange={(v) =>
                          set("glide_path_end_allocation", { ...p.glide_path_end_allocation, domestic_stock: v / 100 })
                        }
                        min={0}
                        max={100}
                      />
                      <NumberField
                        label={t("globalStock")}
                        value={Math.round(p.glide_path_end_allocation.global_stock * 100)}
                        onChange={(v) =>
                          set("glide_path_end_allocation", { ...p.glide_path_end_allocation, global_stock: v / 100 })
                        }
                        min={0}
                        max={100}
                      />
                      <NumberField
                        label={t("domesticBond")}
                        value={Math.round(p.glide_path_end_allocation.domestic_bond * 100)}
                        onChange={(v) =>
                          set("glide_path_end_allocation", { ...p.glide_path_end_allocation, domestic_bond: v / 100 })
                        }
                        min={0}
                        max={100}
                      />
                    </div>
                    <NumberField
                      label={t("glidePathYears")}
                      value={p.glide_path_years}
                      onChange={(v) => set("glide_path_years", v)}
                      min={1}
                      max={100}
                      step={1}
                      suffix={t("yearsSuffix")}
                    />
                  </div>
                )}
              </>
            )}

            <div className={`grid grid-cols-3 gap-2 ${showAllocation ? "mt-2" : ""}`}>
              <NumberField
                label={t("domesticStockFee")}
                value={+(p.expense_ratios.domestic_stock * 100).toFixed(2)}
                onChange={(v) =>
                  set("expense_ratios", { ...p.expense_ratios, domestic_stock: v / 100 })
                }
                step={0.01}
                min={0}
              />
              <NumberField
                label={t("globalStockFee")}
                value={+(p.expense_ratios.global_stock * 100).toFixed(2)}
                onChange={(v) =>
                  set("expense_ratios", { ...p.expense_ratios, global_stock: v / 100 })
                }
                step={0.01}
                min={0}
              />
              <NumberField
                label={t("domesticBondFee")}
                value={+(p.expense_ratios.domestic_bond * 100).toFixed(2)}
                onChange={(v) =>
                  set("expense_ratios", { ...p.expense_ratios, domestic_bond: v / 100 })
                }
                step={0.01}
                min={0}
              />
            </div>
          </AccordionContent>
        </AccordionItem>

        {/* Withdrawal Strategy */}
        {showWithdrawalStrategy && (
          <AccordionItem value="withdrawal">
            <SectionTrigger
              label={t("withdrawalStrategy")}
              modified={isModified.withdrawal}
            />
            <AccordionContent>
              <Select
                value={p.withdrawal_strategy}
                onValueChange={(v) =>
                  set("withdrawal_strategy", v as "fixed" | "dynamic" | "declining" | "smile")
                }
              >
                <SelectTrigger className="h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="fixed">{t("fixedWithdrawal")}</SelectItem>
                  <SelectItem value="dynamic">{t("dynamicWithdrawal")}</SelectItem>
                  <SelectItem value="declining">{t("decliningWithdrawal")}</SelectItem>
                  <SelectItem value="smile">{t("smileWithdrawal")}</SelectItem>
                </SelectContent>
              </Select>

              {p.withdrawal_strategy === "dynamic" && (
                <div className="grid grid-cols-2 gap-2 mt-2">
                  <NumberField
                    label={t("dynamicCeiling")}
                    value={+(p.dynamic_ceiling * 100).toFixed(1)}
                    onChange={(v) => set("dynamic_ceiling", v / 100)}
                    min={0}
                    max={100}
                    step={0.5}
                  />
                  <NumberField
                    label={t("dynamicFloor")}
                    value={+(p.dynamic_floor * 100).toFixed(1)}
                    onChange={(v) => set("dynamic_floor", v / 100)}
                    min={0}
                    max={100}
                    step={0.5}
                  />
                </div>
              )}

              {p.withdrawal_strategy === "declining" && (
                <div className="grid grid-cols-2 gap-2 mt-2">
                  <NumberField
                    label={t("decliningRate")}
                    value={+(p.declining_rate * 100).toFixed(1)}
                    onChange={(v) => set("declining_rate", v / 100)}
                    min={0}
                    max={10}
                    step={0.1}
                    suffix="%"
                    tooltip={t("decliningRateHelp")}
                  />
                  <NumberField
                    label={t("decliningStartAge")}
                    value={p.declining_start_age}
                    onChange={(v) => set("declining_start_age", v)}
                    min={30}
                    max={100}
                    step={1}
                    tooltip={t("decliningStartAgeHelp")}
                  />
                </div>
              )}

              {p.withdrawal_strategy === "smile" && (
                <div className="space-y-2 mt-2">
                  <div className="grid grid-cols-2 gap-2">
                    <NumberField
                      label={t("smileDeclineRate")}
                      value={+(p.smile_decline_rate * 100).toFixed(1)}
                      onChange={(v) => set("smile_decline_rate", v / 100)}
                      min={0}
                      max={10}
                      step={0.1}
                      suffix="%"
                    />
                    <NumberField
                      label={t("smileDeclineStartAge")}
                      value={p.smile_decline_start_age}
                      onChange={(v) => set("smile_decline_start_age", v)}
                      min={18}
                      max={100}
                      step={1}
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <NumberField
                      label={t("smileMinAge")}
                      value={p.smile_min_age}
                      onChange={(v) => set("smile_min_age", v)}
                      min={30}
                      max={100}
                      step={1}
                    />
                    <NumberField
                      label={t("smileIncreaseRate")}
                      value={+(p.smile_increase_rate * 100).toFixed(1)}
                      onChange={(v) => set("smile_increase_rate", v / 100)}
                      min={0}
                      max={10}
                      step={0.1}
                      suffix="%"
                    />
                  </div>
                </div>
              )}
            </AccordionContent>
          </AccordionItem>
        )}

        {/* Custom Cash Flows */}
        <AccordionItem value="cashflow" className="border-b-0">
          <SectionTrigger
            label={t("cashFlowTitle")}
            modified={isModified.cashFlows}
          />
          <AccordionContent>
            <CashFlowEditor
              value={p.cash_flows}
              onChange={(cfs) => set("cash_flows", cfs)}
            />
          </AccordionContent>
        </AccordionItem>
      </Accordion>

      {/* Extra children (Guardrail settings, etc.) */}
      {children}

      {/* ── Advanced sections ── */}
      <p className="text-[10px] text-muted-foreground uppercase tracking-wider pt-2">
        {t("advancedSettings")}
      </p>
      <Accordion type="multiple" defaultValue={[]}>
        {/* Data Range */}
        <AccordionItem value="data-range">
          <SectionTrigger
            label={t("dataRange")}
            modified={isModified.dataRange}
          />
          <AccordionContent>
            <div className="mb-2">
              <Label className="text-xs inline-flex items-center gap-1">
                {t("dataSource")}
                <InfoTip
                  text={
                    p.data_source === "fire_dataset"
                      ? t("dataSourceFireDesc")
                      : t("dataSourceJstDesc")
                  }
                />
              </Label>
              <Select
                value={p.data_source}
                onValueChange={(v) => {
                  const ds = v as "jst" | "fire_dataset";
                  if (ds === "fire_dataset") {
                    onChange({ ...p, data_source: ds, country: "USA" });
                  } else {
                    onChange({ ...p, data_source: ds });
                  }
                }}
              >
                <SelectTrigger className="h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="jst">{t("dataSourceJst")}</SelectItem>
                  <SelectItem value="fire_dataset">{t("dataSourceFire")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {p.data_source === "jst" && (
              <div className="mb-2">
                <Label className="text-xs">{t("country")}</Label>
                <Select
                  value={p.country}
                  onValueChange={(v) => {
                    set("country", v);
                    const info = countries.find((c) => c.iso === v);
                    if (info && p.data_start_year < info.min_year) {
                      onChange({ ...p, country: v, data_start_year: info.min_year });
                    }
                  }}
                >
                  <SelectTrigger className="h-8 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ALL">{t("allCountries")}</SelectItem>
                    {countries.map((c) => (
                      <SelectItem key={c.iso} value={c.iso}>
                        {countryFlag(c.iso)} {countryName(c)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {p.data_source === "jst" && p.country === "ALL" && (
              <div className="mb-2">
                <Label className="text-xs inline-flex items-center gap-1">
                  {t("poolingMethod")}
                  <InfoTip
                    text={
                      p.pooling_method === "gdp_sqrt"
                        ? t("poolingGdpSqrtHelp")
                        : t("poolingEqualHelp")
                    }
                  />
                </Label>
                <Select
                  value={p.pooling_method}
                  onValueChange={(v) =>
                    set("pooling_method", v as "equal" | "gdp_sqrt")
                  }
                >
                  <SelectTrigger className="h-8 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="equal">{t("poolingEqual")}</SelectItem>
                    <SelectItem value="gdp_sqrt">{t("poolingGdpSqrt")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}

            <NumberField
              label={t("dataStartYear")}
              value={p.data_start_year}
              onChange={(v) => set("data_start_year", v)}
              min={1871}
              max={2025}
              step={1}
            />
          </AccordionContent>
        </AccordionItem>

        {/* Simulation Settings */}
        <AccordionItem value="simulation">
          <SectionTrigger
            label={t("simulationSettings")}
            modified={isModified.simulation}
          />
          <AccordionContent>
            <div className="grid grid-cols-2 gap-2">
              <NumberField
                label={t("numSimulations")}
                value={p.num_simulations}
                onChange={(v) => set("num_simulations", v)}
                min={100}
                max={50000}
                step={1000}
              />
              <NumberField
                label={t("minBlock")}
                value={p.min_block}
                onChange={(v) => set("min_block", v)}
                min={1}
                max={p.max_block}
                suffix={t("yearsSuffix")}
              />
              <NumberField
                label={t("maxBlock")}
                value={p.max_block}
                onChange={(v) => set("max_block", v)}
                min={p.min_block}
                max={55}
                suffix={t("yearsSuffix")}
              />
            </div>
          </AccordionContent>
        </AccordionItem>

        {/* Leverage */}
        <AccordionItem value="leverage" className="border-b-0">
          <SectionTrigger
            label={t("leverage")}
            modified={isModified.leverage}
          />
          <AccordionContent>
            <NumberField
              label={t("leverageMultiplier")}
              value={p.leverage}
              onChange={(v) => set("leverage", v)}
              min={1}
              max={5}
              step={0.1}
              suffix="x"
              tooltip={t("noLeverage")}
            />
            {p.leverage > 1 && (
              <div className="mt-2">
                <NumberField
                  label={t("borrowingSpread")}
                  value={+(p.borrowing_spread * 100).toFixed(2)}
                  onChange={(v) => set("borrowing_spread", v / 100)}
                  min={0}
                  max={20}
                  step={0.1}
                  tooltip={t("borrowingCostHelp")}
                />
              </div>
            )}
          </AccordionContent>
        </AccordionItem>
      </Accordion>

      <ScenarioManager currentParams={p} onLoad={onChange} />
    </div>
  );
});

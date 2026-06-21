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

// Curated "market history" presets that bundle data_source + country + start year
// into one-click choices. Sentinel keys ("__"-prefixed) cannot collide with ISO
// codes, which are used as values for the single-country options. Note: the
// legacy "fire_dataset" source (pre-1970 international = US backfill) is no longer
// offered; "fire_dataset_intl" (real distinct international history) supersedes it.
const MARKET_PRESETS: Record<
  string,
  { data_source: FormParams["data_source"]; country: string; data_start_year: number }
> = {
  __global_pool: { data_source: "jst", country: "ALL", data_start_year: 1900 },
  __us_long: { data_source: "jst", country: "USA", data_start_year: 1900 },
  __us_real_global: { data_source: "fire_dataset_intl", country: "USA", data_start_year: 1970 },
};

/** Map current params to the market-selector value (preset sentinel or ISO).
 *
 * The three named presets carry an explicit window in their label ("from 1900"
 * / "from 1970"), so they only match when the FULL bundle (source + country +
 * start year) is exact — otherwise we return "__custom" rather than mislabel a
 * persisted/imported scenario that would silently run a different window (the
 * data-source / start-year controls are no longer shown). Single JST countries
 * have no year claim in their label, so they match on source + country alone. */
function deriveMarketValue(p: FormParams): string {
  const { data_source: ds, country: c, data_start_year: y } = p;
  if (ds === "jst" && c === "ALL" && y === 1900) return "__global_pool";
  if (ds === "jst" && c === "USA" && y === 1900) return "__us_long";
  if (ds === "fire_dataset_intl" && c === "USA" && y === 1970) return "__us_real_global";
  if (ds === "jst" && c !== "ALL" && c !== "USA") return c; // single JST country
  return "__custom";
}

interface SidebarFormProps {
  params: FormParams;
  onChange: (params: FormParams) => void;
  showWithdrawalStrategy?: boolean;
  showAllocation?: boolean;
  hideRetirementAge?: boolean;
  children?: React.ReactNode;
  countries?: CountryInfo[];
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
  countries: countriesProp,
}: SidebarFormProps) {
  const t = useTranslations("sidebar");
  const locale = useLocale();
  const p = params;
  const set = <K extends keyof FormParams>(key: K, val: FormParams[K]) =>
    onChange({ ...p, [key]: val });

  const [showLifeExpectancy, setShowLifeExpectancy] = useState(false);
  // The single-country picker always uses the JST country list, regardless of the
  // active data_source (a US-dataset preset would otherwise shrink the list to USA).
  const [jstCountries, setJstCountries] = useState<CountryInfo[]>(countriesProp ?? []);
  useEffect(() => {
    fetchCountries("jst").then(setJstCountries).catch(() => { /* non-critical init data */ });
  }, []);
  const countries = jstCountries;

  const countryName = (c: CountryInfo) =>
    locale === "zh" ? c.name_zh : c.name_en;

  const marketValue = deriveMarketValue(p);
  const applyMarket = (v: string) => {
    if (v === "__custom") {
      return; // informational only; selecting it must not corrupt params
    }
    if (v in MARKET_PRESETS) {
      onChange({ ...p, ...MARKET_PRESETS[v] });
    } else {
      const info = countries.find((c) => c.iso === v);
      onChange({
        ...p,
        data_source: "jst",
        country: v,
        data_start_year: info ? info.min_year : p.data_start_year,
      });
    }
  };

  const isModified = useMemo(() => {
    const check = (keys: (keyof FormParams)[]) =>
      keys.some(
        (k) => JSON.stringify(p[k]) !== JSON.stringify(DEFAULT_PARAMS[k])
      );
    return {
      allocation: check(["allocation"]),
      expense: check(["expense_ratios"]),
      glidePath: check(["glide_path_enabled", "glide_path_end_allocation", "glide_path_years"]),
      withdrawal: check(["withdrawal_strategy"]),
      strategyTuning: check([
        "dynamic_ceiling", "dynamic_floor", "declining_rate", "declining_start_age",
        "smile_decline_rate", "smile_decline_start_age", "smile_min_age", "smile_increase_rate",
        "cape_intercept", "cape_slope", "cape_floor", "cape_ceiling",
      ]),
      leverage: check(["leverage", "borrowing_spread"]),
      cashFlows: p.cash_flows.length > 0,
    };
  }, [p]);

  const coreDefaults = [
    ...(showAllocation ? ["allocation"] : []),
    ...(showWithdrawalStrategy ? ["withdrawal"] : []),
    "cashflow",
  ];
  // Advanced "strategy tuning" only applies to strategies with coefficients.
  const hasStrategyCoeffs = p.withdrawal_strategy !== "fixed";

  // Strategy coefficient fields (rendered in the Advanced > strategy-tuning
  // section; the strategy SELECTOR stays in the core section).
  const strategyCoeffFields = (
    <>
      {p.withdrawal_strategy === "dynamic" && (
        <div className="grid grid-cols-2 gap-2">
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
        <div className="grid grid-cols-2 gap-2">
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
        <div className="space-y-2">
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

      {p.withdrawal_strategy === "cape" && (
        <div className="space-y-2">
          <p className="text-[11px] text-muted-foreground leading-snug">
            {t("capeWithdrawalHelp")}
          </p>
          <div className="grid grid-cols-2 gap-2">
            <NumberField
              label={t("capeIntercept")}
              value={+(((p.cape_intercept ?? 0.015) * 100).toFixed(2))}
              onChange={(v) => set("cape_intercept", v / 100)}
              min={0}
              max={10}
              step={0.1}
              suffix="%"
              tooltip={t("capeInterceptHelp")}
            />
            <NumberField
              label={t("capeSlope")}
              value={p.cape_slope ?? 0.5}
              onChange={(v) => set("cape_slope", v)}
              min={0}
              max={2}
              step={0.05}
              tooltip={t("capeSlopeHelp")}
            />
            <NumberField
              label={t("capeFloor")}
              value={+(((p.cape_floor ?? 0.02) * 100).toFixed(1))}
              onChange={(v) => set("cape_floor", v / 100)}
              min={0.5}
              max={20}
              step={0.25}
              suffix="%"
            />
            <NumberField
              label={t("capeCeiling")}
              value={+(((p.cape_ceiling ?? 0.08) * 100).toFixed(1))}
              onChange={(v) => set("cape_ceiling", v / 100)}
              min={1}
              max={30}
              step={0.25}
              suffix="%"
            />
          </div>
        </div>
      )}
    </>
  );

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
      <div className="space-y-1">
        <Label className="text-xs inline-flex items-center gap-1">
          {t("marketHistory")}
          <InfoTip text={t("marketHistoryHelp")} />
        </Label>
        <Select value={marketValue} onValueChange={applyMarket}>
          <SelectTrigger className="h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {marketValue === "__custom" && (
              <SelectItem value="__custom">{t("presetCustom")}</SelectItem>
            )}
            <SelectItem value="__global_pool">{t("presetGlobalPool")}</SelectItem>
            <SelectItem value="__us_long">{t("presetUsLong")}</SelectItem>
            <SelectItem value="__us_real_global">{t("presetUsRealGlobal")}</SelectItem>
            {countries.filter((c) => c.iso !== "USA").length > 0 && (
              <>
                <div className="px-2 py-1 text-[10px] text-muted-foreground uppercase tracking-wider">
                  {t("groupSingleCountry")}
                </div>
                {countries
                  .filter((c) => c.iso !== "USA")
                  .map((c) => (
                    <SelectItem key={c.iso} value={c.iso}>
                      {countryFlag(c.iso)} {countryName(c)}
                    </SelectItem>
                  ))}
              </>
            )}
          </SelectContent>
        </Select>
      </div>

      <Accordion type="multiple" defaultValue={coreDefaults}>
        {/* Asset Allocation (sliders only; fees + glide path live in Advanced) */}
        {showAllocation && (
        <AccordionItem value="allocation">
          <SectionTrigger
            label={t("assetAllocation")}
            modified={isModified.allocation}
          />
          <AccordionContent>
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

            </>
          </AccordionContent>
        </AccordionItem>
        )}

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
                  set("withdrawal_strategy", v as "fixed" | "dynamic" | "declining" | "smile" | "cape")
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
                  <SelectItem value="cape">{t("capeWithdrawal")}</SelectItem>
                </SelectContent>
              </Select>
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
        {/* Expense ratios (3 separate per-asset fees) */}
        <AccordionItem value="expense">
          <SectionTrigger
            label={t("assetExpenseRatio")}
            modified={isModified.expense}
          />
          <AccordionContent>
            <div className="grid grid-cols-3 gap-2">
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

        {/* Strategy tuning (coefficients for the selected non-fixed strategy) */}
        {showWithdrawalStrategy && hasStrategyCoeffs && (
          <AccordionItem value="strategy-tuning">
            <SectionTrigger
              label={t("strategyTuning")}
              modified={isModified.strategyTuning}
            />
            <AccordionContent>{strategyCoeffFields}</AccordionContent>
          </AccordionItem>
        )}

        {/* Glide path (allocation drift over retirement) */}
        {showAllocation && (
          <AccordionItem value="glide-path">
            <SectionTrigger
              label={t("glidePath")}
              modified={isModified.glidePath}
            />
            <AccordionContent>
              <div className="flex items-center gap-2">
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
                    max={p.retirement_years}
                    step={1}
                    suffix={t("yearsSuffix")}
                  />
                </div>
              )}
            </AccordionContent>
          </AccordionItem>
        )}

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

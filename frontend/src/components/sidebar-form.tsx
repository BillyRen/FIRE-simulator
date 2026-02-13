"use client";

import { useState, useEffect } from "react";
import { useTranslations, useLocale } from "next-intl";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CashFlowEditor } from "./cash-flow-editor";
import { fetchCountries } from "@/lib/api";
import type { FormParams, CountryInfo } from "@/lib/types";

interface SidebarFormProps {
  params: FormParams;
  onChange: (params: FormParams) => void;
  showWithdrawalStrategy?: boolean;
  showAllocation?: boolean;
  children?: React.ReactNode;
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
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
  help?: string;
}) {
  const [display, setDisplay] = useState(String(value));

  useEffect(() => {
    setDisplay(String(value));
  }, [value]);

  const commit = () => {
    const parsed = parseFloat(display);
    if (isNaN(parsed)) {
      onChange(min ?? 0);
      setDisplay(String(min ?? 0));
    } else {
      const clamped =
        Math.min(max ?? Infinity, Math.max(min ?? -Infinity, parsed));
      onChange(clamped);
      setDisplay(String(clamped));
    }
  };

  return (
    <div>
      <Label className="text-xs">{label}</Label>
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
    </div>
  );
}

export function SidebarForm({
  params,
  onChange,
  showWithdrawalStrategy = true,
  showAllocation = true,
  children,
}: SidebarFormProps) {
  const t = useTranslations("sidebar");
  const locale = useLocale();
  const p = params;
  const set = <K extends keyof FormParams>(key: K, val: FormParams[K]) =>
    onChange({ ...p, [key]: val });

  // 加载国家列表
  const [countries, setCountries] = useState<CountryInfo[]>([]);
  useEffect(() => {
    fetchCountries().then(setCountries).catch(() => {});
  }, []);

  const countryName = (c: CountryInfo) =>
    locale === "zh" ? c.name_zh : c.name_en;

  return (
    <div className="space-y-4">
      {/* 数据范围 */}
      <div>
        <h3 className="text-sm font-semibold mb-2">{t("dataRange")}</h3>

        <div className="mb-2">
          <Label className="text-xs">{t("country")}</Label>
          <Select
            value={p.country}
            onValueChange={(v) => {
              set("country", v);
              // 自动调整 data_start_year 到该国最小年份（如果当前值超出范围）
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
                  {countryName(c)} ({c.iso})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {p.country === "ALL" && (
          <div className="mb-2">
            <Label className="text-xs">{t("poolingMethod")}</Label>
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
            <p className="text-[10px] text-muted-foreground mt-0.5">
              {p.pooling_method === "gdp_sqrt" ? t("poolingGdpSqrtHelp") : t("poolingEqualHelp")}
            </p>
          </div>
        )}

        <NumberField
          label={t("dataStartYear")}
          value={p.data_start_year}
          onChange={(v) => set("data_start_year", v)}
          min={1871}
          max={2020}
          step={1}
        />
      </div>

      <Separator />

      {/* 资产配置 */}
      <div>
        <h3 className="text-sm font-semibold mb-2">
          {showAllocation ? t("assetAllocation") : t("assetExpenseRatio")}
        </h3>
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
      </div>

      <Separator />

      {/* 模拟设置 */}
      <div>
        <h3 className="text-sm font-semibold mb-2">{t("simulationSettings")}</h3>
        <div className="grid grid-cols-2 gap-2">
          <NumberField
            label={t("retirementYears")}
            value={p.retirement_years}
            onChange={(v) => set("retirement_years", v)}
            min={1}
            max={100}
          />
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
      </div>

      {showWithdrawalStrategy && (
        <>
          <Separator />
          <div>
            <h3 className="text-sm font-semibold mb-2">{t("withdrawalStrategy")}</h3>
            <Select
              value={p.withdrawal_strategy}
              onValueChange={(v) =>
                set("withdrawal_strategy", v as "fixed" | "dynamic")
              }
            >
              <SelectTrigger className="h-8 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fixed">{t("fixedWithdrawal")}</SelectItem>
                <SelectItem value="dynamic">{t("dynamicWithdrawal")}</SelectItem>
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
          </div>
        </>
      )}

      <Separator />

      {/* 杠杆设置 */}
      <div>
        <h3 className="text-sm font-semibold mb-2">{t("leverage")}</h3>
        <NumberField
          label={t("leverageMultiplier")}
          value={p.leverage}
          onChange={(v) => set("leverage", v)}
          min={1}
          max={5}
          step={0.1}
          suffix="x"
          help={t("noLeverage")}
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
              help={t("borrowingCostHelp")}
            />
          </div>
        )}
      </div>

      {/* 额外子元素（Guardrail 参数等） */}
      {children}

      <Separator />

      {/* 现金流 */}
      <CashFlowEditor
        value={p.cash_flows}
        onChange={(cfs) => set("cash_flows", cfs)}
      />
    </div>
  );
}

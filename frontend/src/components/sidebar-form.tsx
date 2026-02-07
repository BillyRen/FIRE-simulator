"use client";

import { useState, useEffect } from "react";
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
import type { FormParams } from "@/lib/types";

interface SidebarFormProps {
  params: FormParams;
  onChange: (params: FormParams) => void;
  /** 是否展示提取策略选择（敏感性页面不需要） */
  showWithdrawalStrategy?: boolean;
  /** 额外的子元素（如 guardrail 特有参数） */
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

  // 外部 value 变化时同步到 display（仅在 input 未聚焦时）
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
  children,
}: SidebarFormProps) {
  const p = params;
  const set = <K extends keyof FormParams>(key: K, val: FormParams[K]) =>
    onChange({ ...p, [key]: val });

  return (
    <div className="space-y-4">
      {/* 数据范围 */}
      <div>
        <h3 className="text-sm font-semibold mb-2">📅 数据范围</h3>
        <NumberField
          label="数据起始年"
          value={p.data_start_year}
          onChange={(v) => set("data_start_year", v)}
          min={1871}
          max={2024}
          step={1}
        />
        {p.data_start_year < 1970 && (
          <p className="text-[10px] text-amber-600 mt-1">
            ⚠️ 1970 年以前国际股票数据由美股模拟
          </p>
        )}
      </div>

      <Separator />

      {/* 资产配置 */}
      <div>
        <h3 className="text-sm font-semibold mb-2">📊 资产配置</h3>
        <div className="grid grid-cols-3 gap-2">
          <NumberField
            label="美股 %"
            value={Math.round(p.allocation.us_stock * 100)}
            onChange={(v) =>
              set("allocation", { ...p.allocation, us_stock: v / 100 })
            }
            min={0}
            max={100}
          />
          <NumberField
            label="国际股 %"
            value={Math.round(p.allocation.intl_stock * 100)}
            onChange={(v) =>
              set("allocation", { ...p.allocation, intl_stock: v / 100 })
            }
            min={0}
            max={100}
          />
          <NumberField
            label="美债 %"
            value={Math.round(p.allocation.us_bond * 100)}
            onChange={(v) =>
              set("allocation", { ...p.allocation, us_bond: v / 100 })
            }
            min={0}
            max={100}
          />
        </div>
        {Math.abs(
          p.allocation.us_stock + p.allocation.intl_stock + p.allocation.us_bond - 1
        ) > 0.01 && (
          <p className="text-[10px] text-red-500 mt-1">⚠️ 配置比例之和需为 100%</p>
        )}

        <div className="grid grid-cols-3 gap-2 mt-2">
          <NumberField
            label="美股费率 %"
            value={+(p.expense_ratios.us_stock * 100).toFixed(2)}
            onChange={(v) =>
              set("expense_ratios", { ...p.expense_ratios, us_stock: v / 100 })
            }
            step={0.01}
            min={0}
          />
          <NumberField
            label="国际股费率 %"
            value={+(p.expense_ratios.intl_stock * 100).toFixed(2)}
            onChange={(v) =>
              set("expense_ratios", { ...p.expense_ratios, intl_stock: v / 100 })
            }
            step={0.01}
            min={0}
          />
          <NumberField
            label="美债费率 %"
            value={+(p.expense_ratios.us_bond * 100).toFixed(2)}
            onChange={(v) =>
              set("expense_ratios", { ...p.expense_ratios, us_bond: v / 100 })
            }
            step={0.01}
            min={0}
          />
        </div>
      </div>

      <Separator />

      {/* 模拟设置 */}
      <div>
        <h3 className="text-sm font-semibold mb-2">⚙️ 模拟设置</h3>
        <div className="grid grid-cols-2 gap-2">
          <NumberField
            label="退休年限"
            value={p.retirement_years}
            onChange={(v) => set("retirement_years", v)}
            min={1}
            max={100}
          />
          <NumberField
            label="模拟次数"
            value={p.num_simulations}
            onChange={(v) => set("num_simulations", v)}
            min={100}
            max={50000}
            step={1000}
          />
          <NumberField
            label="最小采样窗口"
            value={p.min_block}
            onChange={(v) => set("min_block", v)}
            min={1}
            max={p.max_block}
            suffix="年"
          />
          <NumberField
            label="最大采样窗口"
            value={p.max_block}
            onChange={(v) => set("max_block", v)}
            min={p.min_block}
            max={55}
            suffix="年"
          />
        </div>
      </div>

      {showWithdrawalStrategy && (
        <>
          <Separator />
          <div>
            <h3 className="text-sm font-semibold mb-2">💰 提取策略</h3>
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
                <SelectItem value="fixed">固定提取</SelectItem>
                <SelectItem value="dynamic">动态提取 (Vanguard)</SelectItem>
              </SelectContent>
            </Select>

            {p.withdrawal_strategy === "dynamic" && (
              <div className="grid grid-cols-2 gap-2 mt-2">
                <NumberField
                  label="年度上调上限 %"
                  value={+(p.dynamic_ceiling * 100).toFixed(1)}
                  onChange={(v) => set("dynamic_ceiling", v / 100)}
                  min={0}
                  max={100}
                  step={0.5}
                />
                <NumberField
                  label="年度下调上限 %"
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

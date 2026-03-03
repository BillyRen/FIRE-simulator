"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { DEFAULT_PARAMS } from "./types";
import type { FormParams } from "./types";

interface SharedParamsState {
  params: FormParams;
  setParams: (p: FormParams) => void;

  // Guardrail
  guardrailTargetSuccess: number;
  setGuardrailTargetSuccess: (v: number) => void;
  guardrailUpperGuardrail: number;
  setGuardrailUpperGuardrail: (v: number) => void;
  guardrailLowerGuardrail: number;
  setGuardrailLowerGuardrail: (v: number) => void;
  guardrailAdjustmentPct: number;
  setGuardrailAdjustmentPct: (v: number) => void;
  guardrailAdjustmentMode: "amount" | "success_rate";
  setGuardrailAdjustmentMode: (v: "amount" | "success_rate") => void;
  guardrailMinRemainingYears: number;
  setGuardrailMinRemainingYears: (v: number) => void;
  guardrailBaselineRate: number;
  setGuardrailBaselineRate: (v: number) => void;

  // Sensitivity
  sensitivityRateMax: number;
  setSensitivityRateMax: (v: number) => void;
  sensitivityRateStep: number;
  setSensitivityRateStep: (v: number) => void;
  sensitivityMetric: "success_rate" | "funded_ratio";
  setSensitivityMetric: (v: "success_rate" | "funded_ratio") => void;

  // Allocation
  allocationAllocStep: number;
  setAllocationAllocStep: (v: number) => void;

  // Backtest common
  histStartYear: number;
  setHistStartYear: (v: number) => void;
  singleCountry: string;
  setSingleCountry: (v: string) => void;
}

const ParamsContext = createContext<SharedParamsState | null>(null);

export function ParamsProvider({ children }: { children: ReactNode }) {
  const [params, setParams] = useState<FormParams>(DEFAULT_PARAMS);

  // Guardrail
  const [guardrailTargetSuccess, setGuardrailTargetSuccess] = useState(0.85);
  const [guardrailUpperGuardrail, setGuardrailUpperGuardrail] = useState(0.99);
  const [guardrailLowerGuardrail, setGuardrailLowerGuardrail] = useState(0.7);
  const [guardrailAdjustmentPct, setGuardrailAdjustmentPct] = useState(0.1);
  const [guardrailAdjustmentMode, setGuardrailAdjustmentMode] = useState<"amount" | "success_rate">("amount");
  const [guardrailMinRemainingYears, setGuardrailMinRemainingYears] = useState(5);
  const [guardrailBaselineRate, setGuardrailBaselineRate] = useState(0.033);

  // Sensitivity
  const [sensitivityRateMax, setSensitivityRateMax] = useState(0.12);
  const [sensitivityRateStep, setSensitivityRateStep] = useState(0.002);
  const [sensitivityMetric, setSensitivityMetric] = useState<"success_rate" | "funded_ratio">("success_rate");

  // Allocation
  const [allocationAllocStep, setAllocationAllocStep] = useState(0.1);

  // Backtest common
  const [histStartYear, setHistStartYear] = useState(1990);
  const [singleCountry, setSingleCountry] = useState("USA");

  return (
    <ParamsContext.Provider
      value={{
        params, setParams,
        guardrailTargetSuccess, setGuardrailTargetSuccess,
        guardrailUpperGuardrail, setGuardrailUpperGuardrail,
        guardrailLowerGuardrail, setGuardrailLowerGuardrail,
        guardrailAdjustmentPct, setGuardrailAdjustmentPct,
        guardrailAdjustmentMode, setGuardrailAdjustmentMode,
        guardrailMinRemainingYears, setGuardrailMinRemainingYears,
        guardrailBaselineRate, setGuardrailBaselineRate,
        sensitivityRateMax, setSensitivityRateMax,
        sensitivityRateStep, setSensitivityRateStep,
        sensitivityMetric, setSensitivityMetric,
        allocationAllocStep, setAllocationAllocStep,
        histStartYear, setHistStartYear,
        singleCountry, setSingleCountry,
      }}
    >
      {children}
    </ParamsContext.Provider>
  );
}

export function useSharedParams(): SharedParamsState {
  const ctx = useContext(ParamsContext);
  if (!ctx) throw new Error("useSharedParams must be used within ParamsProvider");
  return ctx;
}

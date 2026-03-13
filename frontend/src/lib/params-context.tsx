"use client";

import { createContext, useContext, useEffect, useRef, type ReactNode, type Dispatch, type SetStateAction } from "react";
import { DEFAULT_PARAMS } from "./types";
import type { FormParams } from "./types";
import { usePersistedState } from "./use-persisted-state";
import { fetchServerDefaults } from "./api";

interface SharedParamsState {
  params: FormParams;
  setParams: Dispatch<SetStateAction<FormParams>>;

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
  guardrailConsumptionFloor: number;
  setGuardrailConsumptionFloor: (v: number) => void;
  guardrailConsumptionFloorAmount: number;
  setGuardrailConsumptionFloorAmount: (v: number) => void;

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
  const [params, setParams] = usePersistedState<FormParams>("fire:params", DEFAULT_PARAMS);

  // Apply server-recommended num_simulations on first load (only if user never changed it)
  const applied = useRef(false);
  useEffect(() => {
    if (applied.current) return;
    applied.current = true;
    const hasUserSaved = localStorage.getItem("fire:params") !== null;
    if (hasUserSaved) return; // user already has persisted params, don't override
    fetchServerDefaults()
      .then((defaults) => {
        setParams((p) => ({ ...p, num_simulations: defaults.recommended_sim_counts.default }));
      })
      .catch(() => { /* use static default on failure */ });
  }, [setParams]);

  // Guardrail
  const [guardrailTargetSuccess, setGuardrailTargetSuccess] = usePersistedState("fire:guardrailTargetSuccess", 0.85);
  const [guardrailUpperGuardrail, setGuardrailUpperGuardrail] = usePersistedState("fire:guardrailUpperGuardrail", 0.99);
  const [guardrailLowerGuardrail, setGuardrailLowerGuardrail] = usePersistedState("fire:guardrailLowerGuardrail", 0.6);
  const [guardrailAdjustmentPct, setGuardrailAdjustmentPct] = usePersistedState("fire:guardrailAdjustmentPct", 0.1);
  const [guardrailAdjustmentMode, setGuardrailAdjustmentMode] = usePersistedState<"amount" | "success_rate">("fire:guardrailAdjustmentMode", "amount");
  const [guardrailMinRemainingYears, setGuardrailMinRemainingYears] = usePersistedState("fire:guardrailMinRemainingYears", 5);
  const [guardrailBaselineRate, setGuardrailBaselineRate] = usePersistedState("fire:guardrailBaselineRate", 0.033);
  const [guardrailConsumptionFloor, setGuardrailConsumptionFloor] = usePersistedState("fire:guardrailConsumptionFloor", 0.50);
  const [guardrailConsumptionFloorAmount, setGuardrailConsumptionFloorAmount] = usePersistedState("fire:guardrailConsumptionFloorAmount", 0);

  // Sensitivity
  const [sensitivityRateMax, setSensitivityRateMax] = usePersistedState("fire:sensitivityRateMax", 0.12);
  const [sensitivityRateStep, setSensitivityRateStep] = usePersistedState("fire:sensitivityRateStep", 0.002);
  const [sensitivityMetric, setSensitivityMetric] = usePersistedState<"success_rate" | "funded_ratio">("fire:sensitivityMetric", "success_rate");

  // Allocation
  const [allocationAllocStep, setAllocationAllocStep] = usePersistedState("fire:allocationAllocStep", 0.1);

  // Backtest common
  const [histStartYear, setHistStartYear] = usePersistedState("fire:histStartYear", 1990);
  const [singleCountry, setSingleCountry] = usePersistedState("fire:singleCountry", "USA");

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
        guardrailConsumptionFloor, setGuardrailConsumptionFloor,
        guardrailConsumptionFloorAmount, setGuardrailConsumptionFloorAmount,
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

"use client";

import { createContext, useContext, useEffect, useRef, useState, useCallback, type ReactNode, type Dispatch, type SetStateAction } from "react";
import { DEFAULT_PARAMS } from "./types";
import type { FormParams } from "./types";
import { usePersistedState } from "./use-persisted-state";
import { fetchServerDefaults, type ServerDefaults } from "./api";

/** Page-weight categories for num_simulations recommendations. */
export type SimCountCategory = "default" | "heavy" | "guardrail" | "allocation";

interface SharedParamsState {
  params: FormParams;
  setParams: Dispatch<SetStateAction<FormParams>>;

  /** Returns the recommended num_simulations for a given page category.
   *  For heavy pages, caps at the server-recommended value for that category. */
  getSimCount: (category?: SimCountCategory) => number;

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

const SIM_COUNTS_KEY = "fire:serverSimCounts";

function loadCachedSimCounts(): ServerDefaults["recommended_sim_counts"] | null {
  try {
    const raw = localStorage.getItem(SIM_COUNTS_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

export function ParamsProvider({ children }: { children: ReactNode }) {
  const [params, setParams] = usePersistedState<FormParams>("fire:params", DEFAULT_PARAMS);
  // Initialize from localStorage cache so heavy-page caps are available synchronously
  const [serverSimCounts, setServerSimCounts] = useState<ServerDefaults["recommended_sim_counts"] | null>(
    () => loadCachedSimCounts()
  );

  // Fetch fresh server defaults and update cache
  const applied = useRef(false);
  useEffect(() => {
    if (applied.current) return;
    applied.current = true;
    fetchServerDefaults()
      .then((defaults) => {
        setServerSimCounts(defaults.recommended_sim_counts);
        try { localStorage.setItem(SIM_COUNTS_KEY, JSON.stringify(defaults.recommended_sim_counts)); } catch { /* quota */ }
        const hasUserSaved = localStorage.getItem("fire:params") !== null;
        if (!hasUserSaved) {
          setParams((p) => ({ ...p, num_simulations: defaults.recommended_sim_counts.default }));
        }
      })
      .catch(() => { /* use cached or static default on failure */ });
  }, [setParams]);

  const getSimCount = useCallback((category: SimCountCategory = "default") => {
    if (category === "default" || !serverSimCounts) {
      return params.num_simulations;
    }
    // For heavy categories, cap at the server-recommended value
    const cap = serverSimCounts[category];
    return Math.min(params.num_simulations, cap);
  }, [params.num_simulations, serverSimCounts]);

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
        getSimCount,
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

"use client";

import { createContext, useContext, useEffect, useRef, useState, useCallback, type ReactNode, type Dispatch, type SetStateAction } from "react";
import { DEFAULT_PARAMS } from "./types";
import type { FormParams } from "./types";
import { usePersistedState } from "./use-persisted-state";
import { fetchServerDefaults, type ServerDefaults } from "./api";
import { consumeSharedParams } from "./share-url";

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
  guardrailEnforceConsumptionFloor: boolean;
  setGuardrailEnforceConsumptionFloor: (v: boolean) => void;

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

/** Conservative hard caps when server defaults are unknown (first visit, SSR). */
/** Matches the low-tier server recommendation (backend/routes/common.py). */
const FALLBACK_HEAVY_CAP = 500;

export function ParamsProvider({ children }: { children: ReactNode }) {
  // Consume a shared-link token before any persisted state hydrates, seeding
  // localStorage so every page-level control picks up the shared values
  // race-free. A lazy useState initializer runs exactly once during the first
  // render — before the usePersistedState hydration effects below — and the
  // token is stripped from the URL on read, so it is safe under strict-mode
  // double-invocation. The decoded value is also applied via setParams below
  // as a fallback for environments where localStorage seeding fails.
  const [sharedParams] = useState(() =>
    typeof window !== "undefined" ? consumeSharedParams() : null,
  );

  const [params, setParams] = usePersistedState<FormParams>("fire:params", DEFAULT_PARAMS);
  const [serverSimCounts, setServerSimCounts] = useState<ServerDefaults["recommended_sim_counts"] | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      const raw = localStorage.getItem(SIM_COUNTS_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  });

  // Apply a consumed shared link to the context. This runs after the
  // usePersistedState hydration effect (declared above), so it wins, and it is
  // the fallback path when localStorage seeding inside consumeSharedParams
  // failed (private browsing / disabled / quota). No-op when no link present.
  const sharedApplied = useRef(false);
  useEffect(() => {
    if (sharedApplied.current || !sharedParams) return;
    sharedApplied.current = true;
    setParams(sharedParams);
  }, [sharedParams, setParams]);

  // Keep the retirement_years invariant: it must equal life_expectancy −
  // retirement_age (the sidebar derives it that way and the UI hint shows it).
  // A persisted blob from an older config can carry an out-of-sync
  // retirement_years (merged on top of a newer default life_expectancy), which
  // would silently make the simulation run a different number of years than the
  // UI states (e.g. age 35 + life 100 should be 65 yrs → age 100, not 110).
  // Reconcile after hydration; only fires when age/life_expectancy change, so it
  // never clobbers the accumulation page's own retirement_years writes.
  useEffect(() => {
    setParams((p) => {
      const expected = Math.max(1, p.life_expectancy - p.retirement_age);
      return p.retirement_years === expected ? p : { ...p, retirement_years: expected };
    });
  }, [params.life_expectancy, params.retirement_age, setParams]);

  // On mount: fetch fresh server defaults
  const applied = useRef(false);
  useEffect(() => {
    if (applied.current) return;
    applied.current = true;
    fetchServerDefaults()
      .then((defaults) => {
        setServerSimCounts(defaults.recommended_sim_counts);
        try { localStorage.setItem(SIM_COUNTS_KEY, JSON.stringify(defaults.recommended_sim_counts)); } catch { /* quota */ }
        // Always cap the displayed num_simulations to the server-recommended default
        const cap = defaults.recommended_sim_counts.default;
        setParams((p) => p.num_simulations > cap ? { ...p, num_simulations: cap } : p);
      })
      .catch(() => { /* use cached or static default on failure */ });
  }, [setParams]);

  const getSimCount = useCallback((category: SimCountCategory = "default") => {
    if (!serverSimCounts) {
      // Server defaults not yet loaded — use conservative fallback for heavy pages
      if (category !== "default") return Math.min(params.num_simulations, FALLBACK_HEAVY_CAP);
      return params.num_simulations;
    }
    // Cap at server-recommended value for this category
    return Math.min(params.num_simulations, serverSimCounts[category]);
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
  const [guardrailEnforceConsumptionFloor, setGuardrailEnforceConsumptionFloor] = usePersistedState("fire:guardrailEnforceConsumptionFloor", false);

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
        guardrailEnforceConsumptionFloor, setGuardrailEnforceConsumptionFloor,
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

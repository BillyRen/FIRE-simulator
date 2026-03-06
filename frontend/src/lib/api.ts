const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

import type {
  SimulationRequest,
  SimulationResponse,
  SweepRequest,
  SweepResponse,
  GuardrailRequest,
  GuardrailResponse,
  BacktestRequest,
  BacktestResponse,
  SimBacktestRequest,
  SimBacktestResponse,
  SimBatchBacktestResponse,
  GuardrailBatchBacktestResponse,
  AllocationSweepRequest,
  AllocationSweepResponse,
  CountryInfo,
  FormParams,
  BuyVsRentSimpleRequest,
  BuyVsRentSimpleResponse,
  BuyVsRentMCRequest,
  BuyVsRentMCResponse,
  HousingCountryInfo,
  BreakevenSimpleRequest,
  BreakevenMCRequest,
  BreakevenResponse,
  AccumulationRequest,
  AccumulationResponse,
  ScenarioAnalysisResponse,
  SensitivityAnalysisResponse,
} from "./types";

const API_TIMEOUT_MS = 120_000; // 2 minutes

async function post<TReq, TRes>(path: string, body: TReq): Promise<TRes> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`API error ${res.status}: ${detail}`);
    }
    return res.json();
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Request timed out. Try reducing simulation count or parameters.");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function runSimulation(req: SimulationRequest): Promise<SimulationResponse> {
  return post<SimulationRequest, SimulationResponse>("/api/simulate", req);
}

export async function runSweep(req: SweepRequest): Promise<SweepResponse> {
  return post<SweepRequest, SweepResponse>("/api/sweep", req);
}

export async function runGuardrail(req: GuardrailRequest): Promise<GuardrailResponse> {
  return post<GuardrailRequest, GuardrailResponse>("/api/guardrail", req);
}

export async function runBacktest(req: BacktestRequest): Promise<BacktestResponse> {
  return post<BacktestRequest, BacktestResponse>("/api/guardrail/backtest", req);
}

export async function runSimBacktest(req: SimBacktestRequest): Promise<SimBacktestResponse> {
  return post<SimBacktestRequest, SimBacktestResponse>("/api/simulate/backtest", req);
}

export async function runAllocationSweep(req: AllocationSweepRequest): Promise<AllocationSweepResponse> {
  return post<AllocationSweepRequest, AllocationSweepResponse>("/api/allocation-sweep", req);
}

// 批量历史回测：主模拟页
export async function runSimBatchBacktest(params: FormParams): Promise<SimBatchBacktestResponse> {
  return post<FormParams, SimBatchBacktestResponse>("/api/simulate/backtest-batch", params);
}

// 批量历史回测：Guardrail 页
export async function runGuardrailBatchBacktest(req: Record<string, unknown>): Promise<GuardrailBatchBacktestResponse> {
  return post<Record<string, unknown>, GuardrailBatchBacktestResponse>("/api/guardrail/backtest-batch", req);
}

// 情景分析：现金流情景分解（护栏页）
export async function runGuardrailScenarios(req: GuardrailRequest): Promise<ScenarioAnalysisResponse> {
  return post<GuardrailRequest, ScenarioAnalysisResponse>("/api/guardrail/scenarios", req);
}

// 参数敏感性分析（护栏页 — 龙卷风图）
export async function runGuardrailSensitivity(req: GuardrailRequest): Promise<SensitivityAnalysisResponse> {
  return post<GuardrailRequest, SensitivityAnalysisResponse>("/api/guardrail/sensitivity", req);
}

// 情景分析：现金流情景分解（退休模拟页）
export async function runSimScenarios(req: SimulationRequest): Promise<ScenarioAnalysisResponse> {
  return post<SimulationRequest, ScenarioAnalysisResponse>("/api/simulate/scenarios", req);
}

// 参数敏感性分析（退休模拟页 — 龙卷风图）
export async function runSimSensitivity(req: SimulationRequest): Promise<SensitivityAnalysisResponse> {
  return post<SimulationRequest, SensitivityAnalysisResponse>("/api/simulate/sensitivity", req);
}

// 买房 vs 租房
export async function runBuyVsRentSimple(req: BuyVsRentSimpleRequest): Promise<BuyVsRentSimpleResponse> {
  return post<BuyVsRentSimpleRequest, BuyVsRentSimpleResponse>("/api/buy-vs-rent/simple", req);
}

export async function runBuyVsRentMC(req: BuyVsRentMCRequest): Promise<BuyVsRentMCResponse> {
  return post<BuyVsRentMCRequest, BuyVsRentMCResponse>("/api/buy-vs-rent/simulate", req);
}

export async function runBreakevenSimple(req: BreakevenSimpleRequest): Promise<BreakevenResponse> {
  return post<BreakevenSimpleRequest, BreakevenResponse>("/api/buy-vs-rent/breakeven/simple", req);
}

export async function runBreakevenMC(req: BreakevenMCRequest): Promise<BreakevenResponse> {
  return post<BreakevenMCRequest, BreakevenResponse>("/api/buy-vs-rent/breakeven/mc", req);
}

export async function fetchHousingCountries(): Promise<HousingCountryInfo[]> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE}/api/buy-vs-rent/countries`, { signal: controller.signal });
    if (!res.ok) throw new Error(`API error ${res.status}`);
    const data = await res.json();
    return data.countries;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Request timed out.");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function runAccumulation(req: AccumulationRequest): Promise<AccumulationResponse> {
  return post<AccumulationRequest, AccumulationResponse>("/api/accumulation", req);
}

export async function fetchCountries(dataSource: string = "jst"): Promise<CountryInfo[]> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE}/api/countries?data_source=${dataSource}`, { signal: controller.signal });
    if (!res.ok) throw new Error(`API error ${res.status}`);
    const data = await res.json();
    return data.countries;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Request timed out.");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

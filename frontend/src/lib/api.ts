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
} from "./types";

async function post<TReq, TRes>(path: string, body: TReq): Promise<TRes> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return res.json();
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

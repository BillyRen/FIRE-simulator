import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Risk Guardrail Strategy",
  description:
    "Simulate risk-based guardrail withdrawal strategies with dynamic spending adjustments. Includes Monte Carlo analysis and historical backtesting. 基于风险护栏的动态提取策略模拟，含蒙特卡洛分析和历史回测。",
  alternates: { canonical: "https://fire.rens.ai/guardrail" },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}

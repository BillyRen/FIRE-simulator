import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "FIRE Calculator",
  description:
    "Calculate when you can achieve financial independence (FIRE) based on your income, expenses, and savings. Monte Carlo simulation with dynamic safe withdrawal rate. FIRE 积累阶段计算器 — 动态交叉法蒙特卡洛模拟。",
  alternates: { canonical: "https://fire.rens.ai/accumulation" },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}

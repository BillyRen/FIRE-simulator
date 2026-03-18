import type { Metadata } from "next";
import { PageHero } from "@/components/page-hero";

export const metadata: Metadata = {
  title: "Safe Withdrawal Rate Calculator",
  description:
    "Find the optimal withdrawal rate for your target success rate. Analyze how different withdrawal rates affect retirement outcomes with Monte Carlo simulation. 安全提取率计算器 — 分析不同提取率对退休成功率的影响。",
  alternates: { canonical: "https://fire.rens.ai/sensitivity" },
  openGraph: {
    title: "Safe Withdrawal Rate Calculator | FIRE Lab",
    description:
      "Find the optimal withdrawal rate for your target success rate using Monte Carlo simulation with 150+ years of historical data.",
    url: "https://fire.rens.ai/sensitivity",
    siteName: "FIRE Lab",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "Safe Withdrawal Rate Calculator | FIRE Lab",
    description:
      "Find the optimal withdrawal rate for your target success rate using Monte Carlo simulation.",
  },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHero ns="sensitivity" />
      {children}
    </>
  );
}

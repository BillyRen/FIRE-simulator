import type { Metadata } from "next";
import { getOgLocale } from "@/lib/og-locale";
import { PageHero } from "@/components/page-hero";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getOgLocale();
  return {
    title: "Guardrail Withdrawal Strategy Simulator",
    description:
      "Simulate dynamic guardrail spending rules that adjust withdrawals based on portfolio performance. Monte Carlo analysis and historical backtesting with 150+ years of data. 护栏提取策略模拟器 — 基于投资组合表现动态调整提取金额。",
    alternates: { canonical: "https://fire.rens.ai/guardrail" },
    openGraph: {
      title: "Guardrail Withdrawal Strategy Simulator | FIRE Lab",
      description:
        "Simulate dynamic spending rules with automatic withdrawal adjustments. Compare guardrail vs fixed strategies with Monte Carlo and historical backtesting.",
      url: "https://fire.rens.ai/guardrail",
      siteName: "FIRE Lab",
      locale,
      type: "website",
    },
    twitter: {
      card: "summary",
      title: "Guardrail Withdrawal Strategy Simulator | FIRE Lab",
      description:
        "Simulate dynamic spending rules with automatic withdrawal adjustments based on portfolio performance.",
    },
  };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHero ns="guardrail" />
      {children}
    </>
  );
}

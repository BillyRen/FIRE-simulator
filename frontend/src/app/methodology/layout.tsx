import type { Metadata } from "next";
import { getOgLocale } from "@/lib/og-locale";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getOgLocale();
  return {
    title: "Methodology — How FIRE Lab Works",
    description:
      "Monte Carlo simulation, Block Bootstrap resampling, guardrail withdrawal strategy, and data sources explained. 方法论 — FIRE Lab 的核心模拟方法、数据来源和关键假设。",
    alternates: { canonical: "https://fire.rens.ai/methodology" },
    openGraph: {
      title: "Methodology | FIRE Lab",
      description:
        "How FIRE Lab simulates retirement: Block Bootstrap, Monte Carlo, success rate, funded ratio, and guardrail strategies explained.",
      url: "https://fire.rens.ai/methodology",
      siteName: "FIRE Lab",
      locale,
      type: "article",
    },
    twitter: {
      card: "summary",
      title: "Methodology | FIRE Lab",
      description:
        "How FIRE Lab simulates retirement scenarios with historical data.",
    },
  };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}

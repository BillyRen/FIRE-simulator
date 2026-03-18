import type { Metadata } from "next";
import { getOgLocale } from "@/lib/og-locale";
import { PageHero } from "@/components/page-hero";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getOgLocale();
  return {
    title: "Risk-Based Guardrail Retirement Calculator (Free)",
    description:
      "Free risk-based guardrail calculator using probability-of-success Monte Carlo guardrails — not Guyton-Klinger. Dynamically adjust retirement withdrawals based on real-time survival probability. 150+ years of data, 16 countries. Open alternative to IncomeLab. 基于成功概率的风险护栏退休计算器。",
    alternates: { canonical: "https://fire.rens.ai/guardrail" },
    openGraph: {
      title: "Risk-Based Guardrail Retirement Calculator | FIRE Lab",
      description:
        "Free probability-of-success guardrail calculator. Dynamically adjust retirement withdrawals — an open alternative to IncomeLab. Monte Carlo with 150+ years of data.",
      url: "https://fire.rens.ai/guardrail",
      siteName: "FIRE Lab",
      locale,
      type: "website",
    },
    twitter: {
      card: "summary",
      title: "Risk-Based Guardrail Strategy | FIRE Lab",
      description:
        "Free risk-based guardrail calculator — dynamically adjust retirement withdrawals based on survival probability.",
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

import type { Metadata } from "next";
import { getOgLocale } from "@/lib/og-locale";
import { PageHero } from "@/components/page-hero";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getOgLocale();
  return {
    title: "FIRE Calculator — Financial Independence Planner",
    description:
      "Calculate when you can achieve financial independence (FIRE) based on income, expenses, and savings. Monte Carlo simulation with dynamic safe withdrawal rate. FIRE 积累阶段计算器 — 动态交叉法蒙特卡洛模拟。",
    alternates: { canonical: "https://fire.rens.ai/accumulation" },
    openGraph: {
      title: "FIRE Calculator | FIRE Lab",
      description:
        "Calculate your FIRE age with Monte Carlo simulation. Find when you can achieve financial independence based on your savings rate.",
      url: "https://fire.rens.ai/accumulation",
      siteName: "FIRE Lab",
      locale,
      type: "website",
    },
    twitter: {
      card: "summary",
      title: "FIRE Calculator | FIRE Lab",
      description:
        "Calculate when you can achieve financial independence using Monte Carlo simulation.",
    },
  };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHero ns="accumulation" />
      {children}
    </>
  );
}

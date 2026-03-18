import type { Metadata } from "next";
import { getOgLocale } from "@/lib/og-locale";
import { PageHero } from "@/components/page-hero";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getOgLocale();
  return {
    title: "Retirement Asset Allocation Optimizer",
    description:
      "Find the optimal mix of domestic stocks, international stocks, and bonds for retirement. Scan hundreds of combinations with Monte Carlo simulation. 退休资产配置优化器 — 找到最优资产配比。",
    alternates: { canonical: "https://fire.rens.ai/allocation" },
    openGraph: {
      title: "Retirement Asset Allocation Optimizer | FIRE Lab",
      description:
        "Scan hundreds of asset allocation combinations to find the optimal portfolio for retirement. Heatmaps, ternary plots, and Pareto frontiers.",
      url: "https://fire.rens.ai/allocation",
      siteName: "FIRE Lab",
      locale,
      type: "website",
    },
    twitter: {
      card: "summary",
      title: "Retirement Asset Allocation Optimizer | FIRE Lab",
      description:
        "Find the optimal asset allocation for retirement across hundreds of stock and bond combinations.",
    },
  };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHero ns="allocation" />
      {children}
    </>
  );
}

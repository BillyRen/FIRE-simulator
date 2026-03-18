import type { Metadata } from "next";
import { PageHero } from "@/components/page-hero";

export const metadata: Metadata = {
  title: "Buy vs Rent Calculator",
  description:
    "Compare buying vs renting a home using historical data and Monte Carlo simulation. Analyze net worth, breakeven prices, and long-term financial outcomes. 买房租房计算器 — 基于历史数据对比买房与租房的财务结果。",
  alternates: { canonical: "https://fire.rens.ai/buy-vs-rent" },
  openGraph: {
    title: "Buy vs Rent Calculator | FIRE Lab",
    description:
      "Compare buying vs renting with Monte Carlo simulation. Find breakeven prices and analyze long-term financial outcomes.",
    url: "https://fire.rens.ai/buy-vs-rent",
    siteName: "FIRE Lab",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "Buy vs Rent Calculator | FIRE Lab",
    description:
      "Compare buying vs renting a home with Monte Carlo simulation and historical market data.",
  },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHero ns="buyVsRent" />
      {children}
    </>
  );
}

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Buy vs Rent Comparison",
  description:
    "Compare the financial outcomes of buying vs renting a home using historical data and Monte Carlo simulation. 基于历史数据和蒙特卡洛模拟比较买房与租房的财务结果。",
  alternates: { canonical: "https://fire.rens.ai/buy-vs-rent" },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}

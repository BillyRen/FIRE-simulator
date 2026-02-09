import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Optimal Asset Allocation",
  description:
    "Compare different asset allocation combinations to find the optimal mix of US stocks, international stocks, and bonds for retirement. 比较不同资产配置组合，找到最优的退休资产配比。",
  alternates: { canonical: "https://fire.rens.ai/allocation" },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}

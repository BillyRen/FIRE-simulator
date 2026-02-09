import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sensitivity Analysis",
  description:
    "Analyze how different withdrawal rates affect retirement success probability. Find the optimal withdrawal rate for your target success rate. 分析不同提取率对退休成功率的影响。",
  alternates: { canonical: "https://fire.rens.ai/sensitivity" },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}

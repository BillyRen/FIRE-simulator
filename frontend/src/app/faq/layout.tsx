import type { Metadata } from "next";
import { getOgLocale } from "@/lib/og-locale";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getOgLocale();
  return {
    title: "FAQ — Frequently Asked Questions",
    description:
      "Common questions about retirement simulation, the 4% rule, Monte Carlo methods, guardrail strategies, and how to use FIRE Lab. 常见问题 — 退休模拟、4% 法则、蒙特卡洛方法和护栏策略。",
    alternates: { canonical: "https://fire.rens.ai/faq" },
    openGraph: {
      title: "FAQ | FIRE Lab",
      description:
        "Answers to common questions about retirement simulation, withdrawal strategies, and FIRE planning.",
      url: "https://fire.rens.ai/faq",
      siteName: "FIRE Lab",
      locale,
      type: "website",
    },
    twitter: {
      card: "summary",
      title: "FAQ | FIRE Lab",
      description:
        "Common questions about retirement simulation and withdrawal strategies.",
    },
  };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}

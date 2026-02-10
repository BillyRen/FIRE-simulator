import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import "./globals.css";
import { Navbar } from "@/components/navbar";
import { Footer } from "@/components/footer";

const OG_LOCALE_MAP: Record<string, string> = {
  en: "en_US",
  zh: "zh_CN",
};

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getLocale();
  const ogLocale = OG_LOCALE_MAP[locale] ?? "en_US";

  return {
    title: {
      default: "FIRE Lab by Rens.AI — Retirement Simulator",
      template: "%s | FIRE Lab",
    },
    description:
      "Free Monte Carlo simulation tool for retirement planning (FIRE). Analyze withdrawal strategies, asset allocation, and risk guardrails with historical data. 免费的蒙特卡洛退休模拟工具，支持提取策略分析、资产配置优化和风险护栏策略。",
    keywords: [
      "FIRE",
      "retirement simulator",
      "Monte Carlo simulation",
      "withdrawal strategy",
      "asset allocation",
      "financial independence",
      "retire early",
      "退休模拟",
      "蒙特卡洛模拟",
      "提前退休",
    ],
    metadataBase: new URL("https://fire.rens.ai"),
    openGraph: {
      title: "FIRE Lab — Monte Carlo Retirement Simulator",
      description:
        "Free tool to simulate retirement scenarios with historical market data. Test withdrawal rates, dynamic spending, and risk guardrails.",
      url: "https://fire.rens.ai",
      siteName: "FIRE Lab",
      locale: ogLocale,
      type: "website",
    },
    twitter: {
      card: "summary",
      title: "FIRE Lab — Monte Carlo Retirement Simulator",
      description:
        "Free tool to simulate retirement scenarios with historical market data.",
    },
    alternates: {
      canonical: "https://fire.rens.ai",
    },
  };
}

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const locale = await getLocale();
  const messages = await getMessages();

  return (
    <html lang={locale}>
      <body
        className="antialiased min-h-screen bg-background flex flex-col font-sans"
      >
        <NextIntlClientProvider locale={locale} messages={messages}>
          <Navbar />
          <main className="flex-1">{children}</main>
          <Footer />
        </NextIntlClientProvider>
        <Analytics />
        <SpeedInsights />
      </body>
    </html>
  );
}

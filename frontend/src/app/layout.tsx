import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import "./globals.css";
import { Navbar } from "@/components/navbar";
import { Footer } from "@/components/footer";
import { ParamsProvider } from "@/lib/params-context";
import { getOgLocale } from "@/lib/og-locale";

export async function generateMetadata(): Promise<Metadata> {
  const ogLocale = await getOgLocale();

  return {
    title: {
      default: "FIRE Lab by Rens.AI — Retirement Simulator",
      template: "%s | FIRE Lab",
    },
    description:
      "Free Monte Carlo simulation tool for retirement planning (FIRE). Analyze withdrawal strategies, asset allocation, and risk guardrails with 150+ years of historical data.",
    keywords: [
      "FIRE",
      "retirement simulator",
      "Monte Carlo simulation",
      "withdrawal strategy",
      "asset allocation",
      "financial independence",
      "retire early",
      "risk-based guardrails",
      "guardrail withdrawal strategy",
      "safe withdrawal rate calculator",
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

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "FIRE Lab",
  url: "https://fire.rens.ai",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
  description:
    "Free Monte Carlo retirement simulator with 150+ years of historical data from 16 countries. Analyze withdrawal strategies, asset allocation, and risk guardrails.",
  creator: {
    "@type": "Organization",
    name: "Rens.AI",
    url: "https://rens.ai",
  },
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const locale = await getLocale();
  const messages = await getMessages();

  return (
    <html lang={locale}>
      <head>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </head>
      <body
        className="antialiased min-h-screen bg-background flex flex-col font-sans"
      >
        <NextIntlClientProvider locale={locale} messages={messages}>
          <ParamsProvider>
            <Navbar />
            <main className="flex-1">{children}</main>
            <Footer />
          </ParamsProvider>
        </NextIntlClientProvider>
        <Analytics />
        <SpeedInsights />
      </body>
    </html>
  );
}

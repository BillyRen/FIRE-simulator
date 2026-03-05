"use client";

import { useState, useEffect } from "react";
import { useTranslations, useLocale } from "next-intl";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { NumberField } from "@/components/sidebar-form";
import { MetricCard } from "@/components/metric-card";
import { LoadingOverlay } from "@/components/loading-overlay";
import PlotlyChart from "@/components/plotly-chart";
import { useIsMobile } from "@/components/fan-chart";
import {
  runBuyVsRentSimple,
  runBuyVsRentMC,
  fetchHousingCountries,
} from "@/lib/api";
import { useSharedParams } from "@/lib/params-context";
import { fmt, pct } from "@/lib/utils";
import type {
  BuyVsRentSimpleResponse,
  BuyVsRentMCResponse,
  HousingCountryInfo,
} from "@/lib/types";

export default function BuyVsRentPage() {
  const t = useTranslations("buyVsRent");
  const ts = useTranslations("sidebar");
  const tc = useTranslations("common");
  const locale = useLocale();
  const isMobile = useIsMobile();
  const { params } = useSharedParams();

  // Home params
  const [homePrice, setHomePrice] = useState(500_000);
  const [downPaymentPct, setDownPaymentPct] = useState(20);
  const [mortgageTerm, setMortgageTerm] = useState(30);
  const [buyingCostPct, setBuyingCostPct] = useState(3);
  const [sellingCostPct, setSellingCostPct] = useState(6);
  const [propertyTaxPct, setPropertyTaxPct] = useState(1);
  const [maintenancePct, setMaintenancePct] = useState(1);
  const [insuranceAnnual, setInsuranceAnnual] = useState(1200);
  const [annualRent, setAnnualRent] = useState(20_000);
  const [analysisYears, setAnalysisYears] = useState(30);

  // Simple mode rates
  const [mortgageRate, setMortgageRate] = useState(6.5);
  const [rentGrowthRate, setRentGrowthRate] = useState(3);
  const [homeAppreciationRate, setHomeAppreciationRate] = useState(3.5);
  const [investmentReturnRate, setInvestmentReturnRate] = useState(8);
  const [inflationRate, setInflationRate] = useState(2.5);

  // MC mode params
  const [mortgageRateSpread, setMortgageRateSpread] = useState(1.7);
  const [mcCountry, setMcCountry] = useState("USA");
  const [mcPooling, setMcPooling] = useState<"equal" | "gdp_sqrt">("equal");
  const [mcDataStartYear, setMcDataStartYear] = useState(1900);
  const [mcNumSim, setMcNumSim] = useState(2000);
  const [mcMinBlock, setMcMinBlock] = useState(5);
  const [mcMaxBlock, setMcMaxBlock] = useState(15);

  // Override toggles
  const [overrideHA, setOverrideHA] = useState(false);
  const [overrideRG, setOverrideRG] = useState(false);
  const [overrideMR, setOverrideMR] = useState(false);
  const [overrideHAVal, setOverrideHAVal] = useState(3.5);
  const [overrideRGVal, setOverrideRGVal] = useState(3);
  const [overrideMRVal, setOverrideMRVal] = useState(6.5);

  // Countries
  const [countries, setCountries] = useState<HousingCountryInfo[]>([]);
  useEffect(() => {
    fetchHousingCountries().then(setCountries).catch(() => {});
  }, []);

  // Results
  const [simpleResult, setSimpleResult] = useState<BuyVsRentSimpleResponse | null>(null);
  const [mcResult, setMcResult] = useState<BuyVsRentMCResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>("simple");

  const handleRunSimple = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await runBuyVsRentSimple({
        home_price: homePrice,
        down_payment_pct: downPaymentPct / 100,
        mortgage_term: mortgageTerm,
        buying_cost_pct: buyingCostPct / 100,
        selling_cost_pct: sellingCostPct / 100,
        property_tax_pct: propertyTaxPct / 100,
        maintenance_pct: maintenancePct / 100,
        insurance_annual: insuranceAnnual,
        annual_rent: annualRent,
        analysis_years: analysisYears,
        mortgage_rate: mortgageRate / 100,
        rent_growth_rate: rentGrowthRate / 100,
        home_appreciation_rate: homeAppreciationRate / 100,
        investment_return_rate: investmentReturnRate / 100,
        inflation_rate: inflationRate / 100,
      });
      setSimpleResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setLoading(false);
    }
  };

  const handleRunMC = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await runBuyVsRentMC({
        home_price: homePrice,
        down_payment_pct: downPaymentPct / 100,
        mortgage_term: mortgageTerm,
        buying_cost_pct: buyingCostPct / 100,
        selling_cost_pct: sellingCostPct / 100,
        property_tax_pct: propertyTaxPct / 100,
        maintenance_pct: maintenancePct / 100,
        insurance_annual: insuranceAnnual,
        annual_rent: annualRent,
        analysis_years: analysisYears,
        mortgage_rate_spread: mortgageRateSpread / 100,
        allocation: params.allocation,
        expense_ratios: params.expense_ratios,
        min_block: mcMinBlock,
        max_block: mcMaxBlock,
        num_simulations: mcNumSim,
        data_start_year: mcDataStartYear,
        country: mcCountry,
        pooling_method: mcPooling,
        leverage: params.leverage,
        borrowing_spread: params.borrowing_spread,
        override_home_appreciation: overrideHA ? overrideHAVal / 100 : null,
        override_rent_growth: overrideRG ? overrideRGVal / 100 : null,
        override_mortgage_rate: overrideMR ? overrideMRVal / 100 : null,
      });
      setMcResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setLoading(false);
    }
  };

  // ======================== RENDER ========================
  return (
    <div className="flex flex-col lg:flex-row gap-4 px-3 sm:px-6 py-4 max-w-[1600px] mx-auto">
      {loading && <LoadingOverlay />}

      {/* Sidebar */}
      <div className="w-full lg:w-[340px] shrink-0">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t("title")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {/* Home section */}
            <div className="font-medium text-xs text-muted-foreground">{t("sectionHome")}</div>
            <NumberField label={t("homePrice")} value={homePrice} onChange={setHomePrice} min={10000} step={10000} />
            <NumberField label={t("downPaymentPct")} value={downPaymentPct} onChange={setDownPaymentPct} min={0} max={100} step={1} suffix="%" />
            <NumberField label={t("mortgageTerm")} value={mortgageTerm} onChange={setMortgageTerm} min={1} max={50} step={1} />

            <Separator />
            <div className="font-medium text-xs text-muted-foreground">{t("sectionCosts")}</div>
            <NumberField label={t("buyingCostPct")} value={buyingCostPct} onChange={setBuyingCostPct} min={0} max={20} step={0.5} suffix="%" />
            <NumberField label={t("sellingCostPct")} value={sellingCostPct} onChange={setSellingCostPct} min={0} max={20} step={0.5} suffix="%" />
            <NumberField label={t("propertyTaxPct")} value={propertyTaxPct} onChange={setPropertyTaxPct} min={0} max={10} step={0.1} suffix="%" />
            <NumberField label={t("maintenancePct")} value={maintenancePct} onChange={setMaintenancePct} min={0} max={10} step={0.1} suffix="%" />
            <NumberField label={t("insuranceAnnual")} value={insuranceAnnual} onChange={setInsuranceAnnual} min={0} step={100} />

            <Separator />
            <div className="font-medium text-xs text-muted-foreground">{t("sectionRent")}</div>
            <NumberField label={t("annualRent")} value={annualRent} onChange={setAnnualRent} min={0} step={1000} />
            <p className="text-xs text-muted-foreground">{t("rentSuggest")}</p>

            <Separator />
            <NumberField label={t("analysisYears")} value={analysisYears} onChange={setAnalysisYears} min={1} max={60} step={1} />

            <Separator />

            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList className="w-full">
                <TabsTrigger value="simple" className="flex-1 text-xs">{t("tabSimple")}</TabsTrigger>
                <TabsTrigger value="mc" className="flex-1 text-xs">{t("tabMC")}</TabsTrigger>
              </TabsList>

              <TabsContent value="simple" className="space-y-3 mt-3">
                <div className="font-medium text-xs text-muted-foreground">{t("sectionRates")}</div>
                <NumberField label={t("mortgageRate")} value={mortgageRate} onChange={setMortgageRate} min={0} max={30} step={0.1} suffix="%" />
                <NumberField label={t("rentGrowthRate")} value={rentGrowthRate} onChange={setRentGrowthRate} min={-10} max={20} step={0.1} suffix="%" />
                <NumberField label={t("homeAppreciationRate")} value={homeAppreciationRate} onChange={setHomeAppreciationRate} min={-20} max={30} step={0.1} suffix="%" />
                <NumberField label={t("investmentReturnRate")} value={investmentReturnRate} onChange={setInvestmentReturnRate} min={-10} max={30} step={0.1} suffix="%" />
                <NumberField label={t("inflationRate")} value={inflationRate} onChange={setInflationRate} min={-5} max={20} step={0.1} suffix="%" />
                <Button className="w-full" onClick={handleRunSimple}>{t("runSimple")}</Button>
              </TabsContent>

              <TabsContent value="mc" className="space-y-3 mt-3">
                <div className="font-medium text-xs text-muted-foreground">{t("sectionSimulation")}</div>

                {/* Country */}
                <div>
                  <Label className="text-xs">{ts("country")}</Label>
                  <Select value={mcCountry} onValueChange={setMcCountry}>
                    <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ALL">ALL</SelectItem>
                      {countries.map((c) => (
                        <SelectItem key={c.iso} value={c.iso}>
                          {c.iso} — {locale === "zh" ? c.name_zh : c.name_en} ({c.housing_years}y)
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {mcCountry === "ALL" && (
                  <div>
                    <Label className="text-xs">{ts("poolingMethod")}</Label>
                    <Select value={mcPooling} onValueChange={(v) => setMcPooling(v as "equal" | "gdp_sqrt")}>
                      <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="equal">{ts("poolingEqual")}</SelectItem>
                        <SelectItem value="gdp_sqrt">{ts("poolingGdpSqrt")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}

                <NumberField label={ts("dataStartYear")} value={mcDataStartYear} onChange={setMcDataStartYear} min={1871} max={2020} step={1} />
                <NumberField label={ts("numSimulations")} value={mcNumSim} onChange={setMcNumSim} min={100} max={20000} step={100} />
                <NumberField label={ts("minBlock")} value={mcMinBlock} onChange={setMcMinBlock} min={1} max={30} step={1} />
                <NumberField label={ts("maxBlock")} value={mcMaxBlock} onChange={setMcMaxBlock} min={1} max={55} step={1} />

                <Separator />
                <div className="font-medium text-xs text-muted-foreground">{t("sectionInvestment")}</div>
                <NumberField label={ts("domesticStock")} value={params.allocation.domestic_stock * 100} onChange={() => {}} min={0} max={100} step={5} suffix="%" />
                <NumberField label={t("mortgageRateSpread")} value={mortgageRateSpread} onChange={setMortgageRateSpread} min={0} max={10} step={0.1} suffix="%" />

                <Separator />

                {/* Override toggles */}
                <OverrideToggle label={t("overrideHomeAppreciation")} checked={overrideHA} onCheckedChange={setOverrideHA}>
                  {overrideHA && <NumberField label={t("homeAppreciationRate")} value={overrideHAVal} onChange={setOverrideHAVal} min={-20} max={30} step={0.1} suffix="%" />}
                </OverrideToggle>
                <OverrideToggle label={t("overrideRentGrowth")} checked={overrideRG} onCheckedChange={setOverrideRG}>
                  {overrideRG && <NumberField label={t("rentGrowthRate")} value={overrideRGVal} onChange={setOverrideRGVal} min={-10} max={20} step={0.1} suffix="%" />}
                </OverrideToggle>
                <OverrideToggle label={t("overrideMortgageRate")} checked={overrideMR} onCheckedChange={setOverrideMR}>
                  {overrideMR && <NumberField label={t("mortgageRate")} value={overrideMRVal} onChange={setOverrideMRVal} min={0} max={30} step={0.1} suffix="%" />}
                </OverrideToggle>

                <Button className="w-full" onClick={handleRunMC}>{t("runMC")}</Button>
              </TabsContent>
            </Tabs>

            {error && <p className="text-xs text-destructive">{error}</p>}
          </CardContent>
        </Card>
      </div>

      {/* Main content */}
      <div className="flex-1 min-w-0 space-y-4">
        {activeTab === "simple" && simpleResult && (
          <SimpleResults result={simpleResult} t={t} isMobile={isMobile} />
        )}
        {activeTab === "mc" && mcResult && (
          <MCResults result={mcResult} t={t} isMobile={isMobile} />
        )}
        {!simpleResult && !mcResult && (
          <Card>
            <CardContent className="py-12 text-center text-muted-foreground text-sm">
              {locale === "zh" ? "输入参数后点击计算或运行模拟" : "Enter parameters and click Calculate or Run Simulation"}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

function OverrideToggle({
  label, checked, onCheckedChange, children,
}: {
  label: string;
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  children?: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Switch checked={checked} onCheckedChange={onCheckedChange} className="scale-75" />
        <span className="text-xs">{label}</span>
      </div>
      {children}
    </div>
  );
}

// ======================== Simple Results ========================
function SimpleResults({
  result, t, isMobile,
}: {
  result: BuyVsRentSimpleResponse;
  t: ReturnType<typeof useTranslations>;
  isMobile: boolean;
}) {
  const s = result.summary;
  const yrs = Array.from({ length: result.analysis_years + 1 }, (_, i) => i);
  const costYrs = Array.from({ length: result.analysis_years }, (_, i) => i + 1);

  return (
    <>
      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        <MetricCard label={t("buyNetWorth")} value={fmt(s.final_buy_net_worth as number)} />
        <MetricCard label={t("rentNetWorth")} value={fmt(s.final_rent_net_worth as number)} />
        <MetricCard label={t("advantage")} value={fmt(s.final_advantage as number)} />
        <MetricCard
          label={t("breakevenYear")}
          value={s.breakeven_year != null ? `${s.breakeven_year}` : t("noBreakeven")}
        />
      </div>

      {/* Net Worth Chart */}
      <Card>
        <CardHeader className="pb-1"><CardTitle className="text-sm">{t("netWorthComparison")}</CardTitle></CardHeader>
        <CardContent>
          <PlotlyChart
            data={[
              { x: yrs, y: result.buy_net_worth_real, type: "scatter", mode: "lines", name: t("buyLabel"), line: { color: "#2563eb" } },
              { x: yrs, y: result.rent_net_worth_real, type: "scatter", mode: "lines", name: t("rentLabel"), line: { color: "#16a34a" } },
            ]}
            layout={{
              height: isMobile ? 280 : 360,
              margin: { l: 60, r: 20, t: 10, b: 40 },
              xaxis: { title: { text: t("years") } },
              yaxis: { title: { text: "$" }, tickformat: ",.0f" },
              legend: { x: 0, y: 1, bgcolor: "rgba(0,0,0,0)" },
              hovermode: "x unified",
            }}
          />
        </CardContent>
      </Card>

      {/* Cost Comparison Chart */}
      <Card>
        <CardHeader className="pb-1"><CardTitle className="text-sm">{t("annualCostComparison")}</CardTitle></CardHeader>
        <CardContent>
          <PlotlyChart
            data={[
              { x: costYrs, y: result.buy_cost_interest_real, type: "bar", name: t("interest"), marker: { color: "#ef4444" } },
              { x: costYrs, y: result.buy_cost_principal_real, type: "bar", name: t("principal"), marker: { color: "#3b82f6" } },
              { x: costYrs, y: result.buy_cost_tax_real, type: "bar", name: t("tax"), marker: { color: "#f59e0b" } },
              { x: costYrs, y: result.buy_cost_maintenance_real, type: "bar", name: t("maintenance"), marker: { color: "#8b5cf6" } },
              { x: costYrs, y: result.buy_cost_insurance_real, type: "bar", name: t("insurance"), marker: { color: "#6b7280" } },
              { x: costYrs, y: result.rent_cost_real, type: "scatter", mode: "lines", name: t("rent"), line: { color: "#16a34a", width: 3 } },
            ]}
            layout={{
              height: isMobile ? 280 : 360,
              barmode: "stack",
              margin: { l: 60, r: 20, t: 10, b: 40 },
              xaxis: { title: { text: t("years") } },
              yaxis: { title: { text: "$" }, tickformat: ",.0f" },
              legend: { x: 0, y: 1, bgcolor: "rgba(0,0,0,0)" },
              hovermode: "x unified",
            }}
          />
        </CardContent>
      </Card>
    </>
  );
}

// ======================== MC Results ========================
function MCResults({
  result, t, isMobile,
}: {
  result: BuyVsRentMCResponse;
  t: ReturnType<typeof useTranslations>;
  isMobile: boolean;
}) {
  const s = result.summary;
  const yrs = Array.from({ length: result.analysis_years + 1 }, (_, i) => i);
  const costYrs = Array.from({ length: result.analysis_years }, (_, i) => i + 1);

  const buyP = result.buy_percentile_trajectories;
  const rentP = result.rent_percentile_trajectories;
  const advP = result.advantage_percentile_trajectories;

  return (
    <>
      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        <MetricCard label={t("finalBuyMedian")} value={fmt(s.final_buy_median as number)} />
        <MetricCard label={t("finalRentMedian")} value={fmt(s.final_rent_median as number)} />
        <MetricCard label={t("buyWinsPct")} value={pct(s.final_buy_wins_pct as number)} />
        <MetricCard
          label={t("breakevenMedian")}
          value={
            s.breakeven_median != null
              ? `${Math.round(s.breakeven_median as number)} ${t("years")}`
              : t("noBreakeven")
          }
        />
      </div>

      {/* Net Worth Fan Chart */}
      <Card>
        <CardHeader className="pb-1"><CardTitle className="text-sm">{t("netWorthComparison")}</CardTitle></CardHeader>
        <CardContent>
          <PlotlyChart
            data={[
              // Buy band P10-P90
              { x: yrs, y: buyP.P90, type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
              { x: yrs, y: buyP.P10, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(37,99,235,0.15)", showlegend: false, hoverinfo: "skip" },
              // Buy P25-P75
              { x: yrs, y: buyP.P75, type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
              { x: yrs, y: buyP.P25, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(37,99,235,0.25)", showlegend: false, hoverinfo: "skip" },
              // Buy median
              { x: yrs, y: buyP.P50, type: "scatter", mode: "lines", name: t("buyLabel"), line: { color: "#2563eb", width: 2.5 } },
              // Rent band P10-P90
              { x: yrs, y: rentP.P90, type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
              { x: yrs, y: rentP.P10, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(22,163,74,0.15)", showlegend: false, hoverinfo: "skip" },
              // Rent P25-P75
              { x: yrs, y: rentP.P75, type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
              { x: yrs, y: rentP.P25, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(22,163,74,0.25)", showlegend: false, hoverinfo: "skip" },
              // Rent median
              { x: yrs, y: rentP.P50, type: "scatter", mode: "lines", name: t("rentLabel"), line: { color: "#16a34a", width: 2.5 } },
            ]}
            layout={{
              height: isMobile ? 300 : 400,
              margin: { l: 60, r: 20, t: 10, b: 40 },
              xaxis: { title: { text: t("years") } },
              yaxis: { title: { text: "$" }, tickformat: ",.0f" },
              legend: { x: 0, y: 1, bgcolor: "rgba(0,0,0,0)" },
              hovermode: "x unified",
            }}
          />
        </CardContent>
      </Card>

      {/* Buy Advantage + Probability */}
      <Card>
        <CardHeader className="pb-1"><CardTitle className="text-sm">{t("buyAdvantage")}</CardTitle></CardHeader>
        <CardContent>
          <PlotlyChart
            data={[
              // Advantage band
              { x: yrs, y: advP.P90, type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
              { x: yrs, y: advP.P10, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(139,92,246,0.15)", showlegend: false, hoverinfo: "skip" },
              { x: yrs, y: advP.P75, type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
              { x: yrs, y: advP.P25, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(139,92,246,0.25)", showlegend: false, hoverinfo: "skip" },
              { x: yrs, y: advP.P50, type: "scatter", mode: "lines", name: t("advantage"), line: { color: "#8b5cf6", width: 2.5 } },
              // Zero line
              { x: [0, result.analysis_years], y: [0, 0], type: "scatter", mode: "lines", line: { color: "#9ca3af", dash: "dash", width: 1 }, showlegend: false },
              // P(buy wins) on secondary axis
              { x: yrs, y: result.buy_wins_probability.map((v: number) => v * 100), type: "scatter", mode: "lines", name: t("buyWinsPct"), line: { color: "#f59e0b", width: 2 }, yaxis: "y2" },
            ]}
            layout={{
              height: isMobile ? 300 : 400,
              margin: { l: 60, r: 60, t: 10, b: 40 },
              xaxis: { title: { text: t("years") } },
              yaxis: { title: { text: "$" }, tickformat: ",.0f", side: "left" },
              yaxis2: { title: { text: "%" }, overlaying: "y", side: "right", range: [0, 105], ticksuffix: "%" },
              legend: { x: 0, y: 1, bgcolor: "rgba(0,0,0,0)" },
              hovermode: "x unified",
            }}
          />
        </CardContent>
      </Card>

      {/* Median Cost Comparison */}
      <Card>
        <CardHeader className="pb-1"><CardTitle className="text-sm">{t("annualCostComparison")}</CardTitle></CardHeader>
        <CardContent>
          <PlotlyChart
            data={[
              { x: costYrs, y: result.buy_cost_median, type: "bar", name: t("buyLabel"), marker: { color: "#3b82f6" } },
              { x: costYrs, y: result.rent_cost_median, type: "bar", name: t("rentLabel"), marker: { color: "#16a34a" } },
            ]}
            layout={{
              height: isMobile ? 280 : 340,
              barmode: "group",
              margin: { l: 60, r: 20, t: 10, b: 40 },
              xaxis: { title: { text: t("years") } },
              yaxis: { title: { text: "$" }, tickformat: ",.0f" },
              legend: { x: 0, y: 1, bgcolor: "rgba(0,0,0,0)" },
              hovermode: "x unified",
            }}
          />
        </CardContent>
      </Card>
    </>
  );
}

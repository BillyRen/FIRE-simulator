"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
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
import { StatsTable } from "@/components/stats-table";
import { useIsMobile } from "@/components/fan-chart";
import { CHART_COLORS, MARGINS } from "@/lib/chart-theme";
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

const PRESETS = {
  us: {
    homePrice: 400_000, downPaymentPct: 20, mortgageTerm: 30,
    buyingCostPct: 3, sellingCostPct: 6,
    propertyTaxPct: 1, maintenancePct: 1, insuranceAnnual: 1500,
    annualRent: 24_000,
    mortgageRate: 6.5, rentGrowthRate: 3, homeAppreciationRate: 3.5,
    investmentReturnRate: 8, inflationRate: 2.5,
  },
  cn: {
    homePrice: 3_000_000, downPaymentPct: 30, mortgageTerm: 30,
    buyingCostPct: 3, sellingCostPct: 2,
    propertyTaxPct: 0, maintenancePct: 0.5, insuranceAnnual: 0,
    annualRent: 60_000,
    mortgageRate: 3.5, rentGrowthRate: 3, homeAppreciationRate: 2,
    investmentReturnRate: 6, inflationRate: 2,
  },
} satisfies Record<string, Record<string, number>>;

type PresetKey = keyof typeof PRESETS | "custom";

export default function BuyVsRentPage() {
  const t = useTranslations("buyVsRent");
  const ts = useTranslations("sidebar");
  const tc = useTranslations("common");
  const locale = useLocale();
  const isMobile = useIsMobile();
  const { params } = useSharedParams();

  // Market preset
  const defaultPreset: PresetKey = locale === "zh" ? "cn" : "us";
  const initP = PRESETS[defaultPreset];
  const [preset, setPreset] = useState<PresetKey>(defaultPreset);

  // Home params
  const [homePrice, setHomePrice] = useState(initP.homePrice);
  const [downPaymentPct, setDownPaymentPct] = useState(initP.downPaymentPct);
  const [mortgageTerm, setMortgageTerm] = useState(initP.mortgageTerm);
  const [buyingCostPct, setBuyingCostPct] = useState(initP.buyingCostPct);
  const [sellingCostPct, setSellingCostPct] = useState(initP.sellingCostPct);
  const [propertyTaxPct, setPropertyTaxPct] = useState(initP.propertyTaxPct);
  const [maintenancePct, setMaintenancePct] = useState(initP.maintenancePct);
  const [insuranceAnnual, setInsuranceAnnual] = useState(initP.insuranceAnnual);
  const [annualRent, setAnnualRent] = useState(initP.annualRent);
  const [analysisYears, setAnalysisYears] = useState(30);

  // Simple mode rates
  const [mortgageRate, setMortgageRate] = useState(initP.mortgageRate);
  const [rentGrowthRate, setRentGrowthRate] = useState(initP.rentGrowthRate);
  const [homeAppreciationRate, setHomeAppreciationRate] = useState(initP.homeAppreciationRate);
  const [investmentReturnRate, setInvestmentReturnRate] = useState(initP.investmentReturnRate);
  const [inflationRate, setInflationRate] = useState(initP.inflationRate);

  // Auto-estimate home appreciation
  const [autoEstimateHA, setAutoEstimateHA] = useState(false);
  const [fairPE, setFairPE] = useState(30);
  const [reversionYears, setReversionYears] = useState(20);
  const [autoFairPE, setAutoFairPE] = useState(false);

  const derivedFairPE = useMemo(() => {
    const spread = mortgageRate / 100 - rentGrowthRate / 100;
    if (spread <= 0) return 35;
    return Math.min(Math.max(Math.round(1 / spread), 10), 35);
  }, [mortgageRate, rentGrowthRate]);

  useEffect(() => {
    if (autoFairPE) {
      setFairPE(derivedFairPE);
    }
  }, [autoFairPE, derivedFairPE]);

  const currentPE = annualRent > 0 ? homePrice / annualRent : 0;
  const estimatedHA = useMemo(() => {
    if (annualRent <= 0 || homePrice <= 0 || reversionYears <= 0) return 0;
    const rg = rentGrowthRate / 100;
    const futureRent = annualRent * Math.pow(1 + rg, reversionYears);
    const fairValue = futureRent * fairPE;
    return (Math.pow(fairValue / homePrice, 1 / reversionYears) - 1) * 100;
  }, [annualRent, homePrice, rentGrowthRate, fairPE, reversionYears]);

  useEffect(() => {
    if (autoEstimateHA) {
      setHomeAppreciationRate(+estimatedHA.toFixed(2));
    }
  }, [autoEstimateHA, estimatedHA]);

  // Auto-estimate investment return
  const [autoEstimateIR, setAutoEstimateIR] = useState(false);
  const [baseReturn, setBaseReturn] = useState(6);
  const [fullEquityReturn, setFullEquityReturn] = useState(8);
  const [borrowingSpread, setBorrowingSpread] = useState(1);

  const currentLeverage = downPaymentPct > 0 ? 1 / (downPaymentPct / 100) : 1;
  const estimatedIR = useMemo(() => {
    const br = baseReturn / 100;
    const fer = fullEquityReturn / 100;
    const mr = mortgageRate / 100;
    const bs = borrowingSpread / 100;

    const effLev = Math.min(currentLeverage, 2);
    const leveraged = br * effLev - (effLev - 1) * (mr + bs);

    const eqPct = Math.min(0.5 * currentLeverage, 1.0);
    const bondRet = 2 * br - fer;
    const equityTilt = eqPct * fer + (1 - eqPct) * bondRet;

    return Math.max(leveraged, equityTilt) * 100;
  }, [currentLeverage, baseReturn, fullEquityReturn, mortgageRate, borrowingSpread]);

  useEffect(() => {
    if (autoEstimateIR) {
      setInvestmentReturnRate(+estimatedIR.toFixed(2));
    }
  }, [autoEstimateIR, estimatedIR]);

  const applyPreset = (key: PresetKey) => {
    setPreset(key);
    if (key === "custom") return;
    const p = PRESETS[key];
    setHomePrice(p.homePrice);
    setDownPaymentPct(p.downPaymentPct);
    setMortgageTerm(p.mortgageTerm);
    setBuyingCostPct(p.buyingCostPct);
    setSellingCostPct(p.sellingCostPct);
    setPropertyTaxPct(p.propertyTaxPct);
    setMaintenancePct(p.maintenancePct);
    setInsuranceAnnual(p.insuranceAnnual);
    setAnnualRent(p.annualRent);
    setMortgageRate(p.mortgageRate);
    setRentGrowthRate(p.rentGrowthRate);
    setHomeAppreciationRate(p.homeAppreciationRate);
    setInvestmentReturnRate(p.investmentReturnRate);
    setInflationRate(p.inflationRate);
    setAutoEstimateHA(false);
    setAutoEstimateIR(false);
    setAutoFairPE(false);
  };

  const customSet = useCallback(<T,>(setter: (v: T) => void) => {
    return (v: T) => { setPreset("custom"); setter(v); };
  }, []);

  // MC mode — allocation & expense ratios (local state, initialized from shared params)
  const [allocation, setAllocation] = useState({
    domestic_stock: params.allocation.domestic_stock,
    global_stock: params.allocation.global_stock,
    domestic_bond: params.allocation.domestic_bond,
  });
  const [expenseRatios, setExpenseRatios] = useState({
    domestic_stock: params.expense_ratios.domestic_stock,
    global_stock: params.expense_ratios.global_stock,
    domestic_bond: params.expense_ratios.domestic_bond,
  });

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
        allocation,
        expense_ratios: expenseRatios,
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
      {/* Sidebar */}
      <div className="w-full lg:w-[340px] shrink-0">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t("title")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {/* Market preset */}
            <div>
              <Label className="text-xs">{t("preset")}</Label>
              <Select value={preset} onValueChange={(v) => applyPreset(v as PresetKey)}>
                <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="us">{t("presetUS")}</SelectItem>
                  <SelectItem value="cn">{t("presetCN")}</SelectItem>
                  <SelectItem value="custom">{t("presetCustom")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Separator />

            {/* Home section */}
            <div className="font-medium text-xs text-muted-foreground">{t("sectionHome")}</div>
            <NumberField label={t("homePrice")} value={homePrice} onChange={customSet(setHomePrice)} min={10000} step={10000} />
            <NumberField label={t("downPaymentPct")} value={downPaymentPct} onChange={customSet(setDownPaymentPct)} min={0} max={100} step={1} suffix="%" />
            <NumberField label={t("mortgageTerm")} value={mortgageTerm} onChange={customSet(setMortgageTerm)} min={1} max={50} step={1} />

            <Separator />
            <div className="font-medium text-xs text-muted-foreground">{t("sectionCosts")}</div>
            <NumberField label={t("buyingCostPct")} value={buyingCostPct} onChange={customSet(setBuyingCostPct)} min={0} max={20} step={0.5} suffix="%" />
            <NumberField label={t("sellingCostPct")} value={sellingCostPct} onChange={customSet(setSellingCostPct)} min={0} max={20} step={0.5} suffix="%" />
            <NumberField label={t("propertyTaxPct")} value={propertyTaxPct} onChange={customSet(setPropertyTaxPct)} min={0} max={10} step={0.1} suffix="%" />
            <NumberField label={t("maintenancePct")} value={maintenancePct} onChange={customSet(setMaintenancePct)} min={0} max={10} step={0.1} suffix="%" />
            <NumberField label={t("insuranceAnnual")} value={insuranceAnnual} onChange={customSet(setInsuranceAnnual)} min={0} step={100} />

            <Separator />
            <div className="font-medium text-xs text-muted-foreground">{t("sectionRent")}</div>
            <NumberField label={t("annualRent")} value={annualRent} onChange={customSet(setAnnualRent)} min={0} step={1000} />
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
                <NumberField label={t("mortgageRate")} value={mortgageRate} onChange={customSet(setMortgageRate)} min={0} max={30} step={0.1} suffix="%" />
                <NumberField label={t("rentGrowthRate")} value={rentGrowthRate} onChange={customSet(setRentGrowthRate)} min={-10} max={20} step={0.1} suffix="%" />
                <NumberField label={t("homeAppreciationRate")} value={+homeAppreciationRate.toFixed(2)} onChange={autoEstimateHA ? () => {} : customSet(setHomeAppreciationRate)} min={-20} max={30} step={0.1} suffix="%" />
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Switch checked={autoEstimateHA} onCheckedChange={setAutoEstimateHA} className="scale-75" />
                    <span className="text-xs">{t("autoEstimateHA")}</span>
                  </div>
                  {autoEstimateHA && (
                    <div className="space-y-2 pl-1 border-l-2 border-muted ml-2">
                      <div className="grid grid-cols-2 gap-2">
                        <div className="space-y-1">
                          <NumberField label={t("fairPE")} value={fairPE} onChange={autoFairPE ? () => {} : setFairPE} min={5} max={100} step={1} />
                          <div className="flex items-center gap-1">
                            <Switch checked={autoFairPE} onCheckedChange={setAutoFairPE} className="scale-[0.6]" />
                            <span className="text-[10px] text-muted-foreground">{t("autoFairPE")}</span>
                          </div>
                        </div>
                        <NumberField label={t("reversionYears")} value={reversionYears} onChange={setReversionYears} min={5} max={50} step={1} />
                      </div>
                      <p className="text-[10px] text-muted-foreground">
                        {t("currentPE", { value: currentPE.toFixed(1) })}
                        {" · "}
                        {t("estimatedRate", { value: estimatedHA.toFixed(2) })}
                      </p>
                    </div>
                  )}
                </div>
                <NumberField label={t("investmentReturnRate")} value={+investmentReturnRate.toFixed(2)} onChange={autoEstimateIR ? () => {} : customSet(setInvestmentReturnRate)} min={-10} max={30} step={0.1} suffix="%" />
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Switch checked={autoEstimateIR} onCheckedChange={setAutoEstimateIR} className="scale-75" />
                    <span className="text-xs">{t("autoEstimateIR")}</span>
                  </div>
                  {autoEstimateIR && (
                    <div className="space-y-2 pl-1 border-l-2 border-muted ml-2">
                      <div className="grid grid-cols-3 gap-2">
                        <NumberField label={t("baseReturn")} value={baseReturn} onChange={setBaseReturn} min={0} max={20} step={0.5} suffix="%" />
                        <NumberField label={t("fullEquityReturn")} value={fullEquityReturn} onChange={setFullEquityReturn} min={0} max={30} step={0.5} suffix="%" />
                        <NumberField label={t("borrowingSpread")} value={borrowingSpread} onChange={setBorrowingSpread} min={0} max={10} step={0.5} suffix="%" />
                      </div>
                      <p className="text-[10px] text-muted-foreground">
                        {t("currentLeverage", { value: currentLeverage.toFixed(1) })}
                        {" · "}
                        {t("estimatedIR", { value: estimatedIR.toFixed(2) })}
                      </p>
                    </div>
                  )}
                </div>
                <NumberField label={t("inflationRate")} value={inflationRate} onChange={customSet(setInflationRate)} min={-5} max={20} step={0.1} suffix="%" />
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
                <div className="grid grid-cols-3 gap-2">
                  <NumberField
                    label={ts("domesticStock")}
                    value={Math.round(allocation.domestic_stock * 100)}
                    onChange={(v) => setAllocation({ ...allocation, domestic_stock: v / 100 })}
                    min={0} max={100} step={5} suffix="%"
                  />
                  <NumberField
                    label={ts("globalStock")}
                    value={Math.round(allocation.global_stock * 100)}
                    onChange={(v) => setAllocation({ ...allocation, global_stock: v / 100 })}
                    min={0} max={100} step={5} suffix="%"
                  />
                  <NumberField
                    label={ts("domesticBond")}
                    value={Math.round(allocation.domestic_bond * 100)}
                    onChange={(v) => setAllocation({ ...allocation, domestic_bond: v / 100 })}
                    min={0} max={100} step={5} suffix="%"
                  />
                </div>
                {Math.abs(allocation.domestic_stock + allocation.global_stock + allocation.domestic_bond - 1) > 0.01 && (
                  <p className="text-[10px] text-red-500 mt-1">{ts("allocationWarning")}</p>
                )}
                <div className="grid grid-cols-3 gap-2 mt-2">
                  <NumberField
                    label={ts("domesticStockFee")}
                    value={+(expenseRatios.domestic_stock * 100).toFixed(2)}
                    onChange={(v) => setExpenseRatios({ ...expenseRatios, domestic_stock: v / 100 })}
                    min={0} max={10} step={0.1} suffix="%"
                  />
                  <NumberField
                    label={ts("globalStockFee")}
                    value={+(expenseRatios.global_stock * 100).toFixed(2)}
                    onChange={(v) => setExpenseRatios({ ...expenseRatios, global_stock: v / 100 })}
                    min={0} max={10} step={0.1} suffix="%"
                  />
                  <NumberField
                    label={ts("domesticBondFee")}
                    value={+(expenseRatios.domestic_bond * 100).toFixed(2)}
                    onChange={(v) => setExpenseRatios({ ...expenseRatios, domestic_bond: v / 100 })}
                    min={0} max={10} step={0.1} suffix="%"
                  />
                </div>
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
        {loading && <LoadingOverlay />}
        {activeTab === "simple" && simpleResult && (
          <SimpleResults result={simpleResult} t={t} isMobile={isMobile} />
        )}
        {activeTab === "mc" && mcResult && (
          <MCResults result={mcResult} t={t} tc={tc} isMobile={isMobile} />
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
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-2">
        <MetricCard label={t("buyNetWorth")} value={fmt(s.final_buy_net_worth as number)} />
        <MetricCard label={t("rentNetWorth")} value={fmt(s.final_rent_net_worth as number)} />
        <MetricCard label={t("advantage")} value={fmt(s.final_advantage as number)} />
        <MetricCard label={t("advantagePct")} value={s.final_rent_net_worth ? pct((s.final_advantage as number) / (s.final_rent_net_worth as number)) : "N/A"} />
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
              { x: yrs, y: result.buy_net_worth_real, type: "scatter", mode: "lines", name: t("buyLabel"), line: { color: CHART_COLORS.primary.hex } },
              { x: yrs, y: result.rent_net_worth_real, type: "scatter", mode: "lines", name: t("rentLabel"), line: { color: CHART_COLORS.secondary.hex } },
            ]}
            layout={{
              height: isMobile ? 280 : 360,
              margin: MARGINS.default(isMobile),
              xaxis: { title: { text: t("years") } },
              yaxis: { title: { text: "$" }, tickformat: ",.0f" },
              legend: { x: 0, y: 1 },
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
              { x: costYrs, y: result.buy_cost_interest_real, type: "bar", name: t("interest"), marker: { color: CHART_COLORS.danger.hex } },
              { x: costYrs, y: result.buy_cost_principal_real, type: "bar", name: t("principal"), marker: { color: CHART_COLORS.primary.hex } },
              { x: costYrs, y: result.buy_cost_tax_real, type: "bar", name: t("tax"), marker: { color: CHART_COLORS.warning.hex } },
              { x: costYrs, y: result.buy_cost_maintenance_real, type: "bar", name: t("maintenance"), marker: { color: CHART_COLORS.accent.hex } },
              { x: costYrs, y: result.buy_cost_insurance_real, type: "bar", name: t("insurance"), marker: { color: CHART_COLORS.neutral.hex } },
              { x: costYrs, y: result.rent_cost_real, type: "scatter", mode: "lines", name: t("rent"), line: { color: CHART_COLORS.secondary.hex, width: 3 } },
            ]}
            layout={{
              height: isMobile ? 280 : 360,
              barmode: "stack",
              margin: { ...MARGINS.default(isMobile), b: 60 },
              xaxis: { title: { text: t("years") } },
              yaxis: { title: { text: "$" }, tickformat: ",.0f" },
              legend: { orientation: "h", x: 0.5, xanchor: "center", y: -0.2 },
            }}
          />
        </CardContent>
      </Card>
    </>
  );
}

// ======================== MC Results ========================
function MCResults({
  result, t, tc, isMobile,
}: {
  result: BuyVsRentMCResponse;
  t: ReturnType<typeof useTranslations>;
  tc: ReturnType<typeof useTranslations>;
  isMobile: boolean;
}) {
  const [nwLog, setNwLog] = useState(false);
  const [advLog, setAdvLog] = useState(false);
  const [costLog, setCostLog] = useState(false);

  const s = result.summary;
  const yrs = Array.from({ length: result.analysis_years + 1 }, (_, i) => i);
  const costYrs = Array.from({ length: result.analysis_years }, (_, i) => i + 1);

  const buyP = result.buy_percentile_trajectories;
  const rentP = result.rent_percentile_trajectories;
  const advP = result.advantage_percentile_trajectories;

  const hfmt = "$,.0f";

  const logBtn = (on: boolean, toggle: () => void) => (
    <Button variant="outline" size="sm" className="h-6 px-2 text-xs" onClick={toggle}>
      {on ? tc("linearScale") : tc("logScale")}
    </Button>
  );

  const yaxLog = (log: boolean) => ({
    title: { text: "$" },
    type: log ? ("log" as const) : ("linear" as const),
    tickformat: log ? "$~s" : "$,.0f",
  });

  /** Build fan traces for a single series with percentile hovertemplates */
  function fanTraces(
    pcts: Record<string, number[]>,
    label: string,
    rgb: string,
  ) {
    const traces: Plotly.Data[] = [];
    // Bands (no hover)
    traces.push(
      { x: yrs, y: pcts.P90, type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
      { x: yrs, y: pcts.P10, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: `rgba(${rgb},0.15)`, showlegend: false, hoverinfo: "skip" },
      { x: yrs, y: pcts.P75, type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
      { x: yrs, y: pcts.P25, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: `rgba(${rgb},0.25)`, showlegend: false, hoverinfo: "skip" },
    );
    // Percentile lines (high → low for unified tooltip order)
    for (const p of ["90", "75", "50", "25", "10"]) {
      if (!pcts[`P${p}`]) continue;
      const isMedian = p === "50";
      traces.push({
        x: yrs,
        y: pcts[`P${p}`],
        type: "scatter",
        mode: "lines",
        name: isMedian ? label : `${label} P${p}`,
        line: isMedian ? { color: `rgb(${rgb})`, width: 2.5 } : { width: 0, color: "transparent" },
        showlegend: isMedian,
        hovertemplate: `${label} P${p}: %{y:${hfmt}}<extra></extra>`,
      });
    }
    return traces;
  }

  return (
    <>
      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-2">
        <MetricCard label={t("finalBuyMedian")} value={fmt(s.final_buy_median as number)} />
        <MetricCard label={t("finalRentMedian")} value={fmt(s.final_rent_median as number)} />
        <MetricCard label={t("advantagePct")} value={s.final_rent_median ? pct((s.final_advantage_median as number) / (s.final_rent_median as number)) : "N/A"} />
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
        <CardHeader className="pb-1 flex flex-row items-center justify-between">
          <CardTitle className="text-sm">{t("netWorthComparison")}</CardTitle>
          {logBtn(nwLog, () => setNwLog(v => !v))}
        </CardHeader>
        <CardContent>
          <PlotlyChart
            data={[
              ...fanTraces(buyP, t("buyLabel"), CHART_COLORS.primary.rgb),
              ...fanTraces(rentP, t("rentLabel"), CHART_COLORS.secondary.rgb),
            ]}
            layout={{
              height: isMobile ? 300 : 400,
              margin: MARGINS.default(isMobile),
              xaxis: { title: { text: t("years") } },
              yaxis: yaxLog(nwLog),
              legend: { x: 0, y: 1 },
            }}
          />
        </CardContent>
      </Card>

      {/* Buy Advantage + Probability */}
      <Card>
        <CardHeader className="pb-1 flex flex-row items-center justify-between">
          <CardTitle className="text-sm">{t("buyAdvantage")}</CardTitle>
          {logBtn(advLog, () => setAdvLog(v => !v))}
        </CardHeader>
        <CardContent>
          <PlotlyChart
            data={[
              // Advantage band (no hover)
              { x: yrs, y: advP.P90, type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
              { x: yrs, y: advP.P10, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: `rgba(${CHART_COLORS.accent.rgb},0.15)`, showlegend: false, hoverinfo: "skip" },
              { x: yrs, y: advP.P75, type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
              { x: yrs, y: advP.P25, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: `rgba(${CHART_COLORS.accent.rgb},0.25)`, showlegend: false, hoverinfo: "skip" },
              // Advantage percentile lines with hover
              ...["90", "75", "50", "25", "10"].map(p => ({
                x: yrs,
                y: advP[`P${p}`],
                type: "scatter" as const,
                mode: "lines" as const,
                name: p === "50" ? t("advantage") : `P${p}`,
                line: p === "50" ? { color: CHART_COLORS.accent.hex, width: 2.5 } : { width: 0, color: "transparent" },
                showlegend: p === "50",
                hovertemplate: `P${p}: %{y:${hfmt}}<extra></extra>`,
              })),
              // Zero line
              { x: [0, result.analysis_years], y: [0, 0], type: "scatter", mode: "lines", line: { color: CHART_COLORS.neutral.hex, dash: "dash", width: 1 }, showlegend: false, hoverinfo: "skip" },
              { x: yrs, y: result.buy_wins_probability.map((v: number) => v * 100), type: "scatter", mode: "lines", name: t("buyWinsPct"), line: { color: CHART_COLORS.warning.hex, width: 2 }, yaxis: "y2", hovertemplate: `${t("buyWinsPct")}: %{y:.1f}%<extra></extra>` },
            ]}
            layout={{
              height: isMobile ? 300 : 400,
              margin: MARGINS.dualAxis(isMobile),
              xaxis: { title: { text: t("years") } },
              yaxis: { ...yaxLog(advLog), side: "left" as const },
              yaxis2: { title: { text: "%" }, overlaying: "y" as const, side: "right" as const, range: [0, 105], ticksuffix: "%" },
              legend: { x: 0, y: 1 },
            }}
          />
        </CardContent>
      </Card>

      {/* Median Cost Comparison */}
      <Card>
        <CardHeader className="pb-1 flex flex-row items-center justify-between">
          <CardTitle className="text-sm">{t("annualCostComparison")}</CardTitle>
          {logBtn(costLog, () => setCostLog(v => !v))}
        </CardHeader>
        <CardContent>
          <PlotlyChart
            data={[
              { x: costYrs, y: result.buy_cost_median, type: "bar", name: t("buyLabel"), marker: { color: CHART_COLORS.primary.hex } },
              { x: costYrs, y: result.rent_cost_median, type: "bar", name: t("rentLabel"), marker: { color: CHART_COLORS.secondary.hex } },
            ]}
            layout={{
              height: isMobile ? 280 : 340,
              barmode: "group",
              margin: { ...MARGINS.default(isMobile), b: 50 },
              xaxis: { title: { text: t("years") } },
              yaxis: yaxLog(costLog),
              legend: { orientation: "h", x: 0.5, xanchor: "center", y: -0.2 },
            }}
          />
        </CardContent>
      </Card>

      {/* Sampled Data Statistics */}
      {result.sampled_stats && result.sampled_stats.length > 0 && (
        <Card>
          <CardHeader className="pb-1"><CardTitle className="text-sm">{t("sampledStats")}</CardTitle></CardHeader>
          <CardContent>
            <StatsTable rows={result.sampled_stats} downloadName="buy_vs_rent_sampled_stats" />
          </CardContent>
        </Card>
      )}
    </>
  );
}

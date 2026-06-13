# US REIT data — FTSE Nareit U.S. Real Estate Index Series

Long-history total-return data for publicly-traded US REITs, used to compare an
**investable real-estate-equity** asset against the repo's JST `Housing_TR`
(physical residential housing). See `docs/reit-vs-jst-housing-2026-06-13.md`.

## Source

Nareit's official monthly history of the FTSE Nareit U.S. Real Estate Index
Series, total-return back to **December 1971** (index base = 100):

  `reit.com/sites/default/files/returns/MonthlyHistoricalReturns.xls`

The live URL sits behind a bot challenge, so the pipeline pulls the identical
file from a Wayback Machine raw snapshot. Re-download / re-parse (needs `xlrd`,
a data-prep-only dependency — `pip install xlrd`):

```bash
python3 scripts/download_nareit_reits.py            # download + parse
python3 scripts/download_nareit_reits.py --skip-download   # parse cached raw
```

## Files

| file | contents |
|---|---|
| `raw/nareit_monthly_historical.xls` | unmodified Nareit workbook (**gitignored**) |
| `nareit_monthly_total_return.csv`   | `Year,Month` + decimal monthly TR per variant + All-Equity dividend yield, 1972-01 .. latest |
| `nareit_annual_total_return.csv`    | Jan-Dec compounded annual TR, decimal, **full calendar years only** (1972-2024 in current snapshot) |

## Index variants (monthly TOTAL return, incl. dividends)

| column | Nareit index | note |
|---|---|---|
| `all_equity_reits` | **All Equity REITs** | headline; incl. timber/infrastructure; the standard "REITs as an asset class" |
| `equity_reits`     | Equity REITs | classic property sectors only (== All Equity pre-2021) |
| `all_reits`        | All REITs | equity + mortgage |
| `mortgage_reits`   | Mortgage REITs | bond-like; not a property-equity proxy |

## Conventions (mirror `data/factors/`, `FIRE_dataset`)

* NOMINAL TOTAL returns (incl. dividends), USD, **gross of fees** — like JST.
* Nareit stores percent; pipeline divides by 100 → decimal.
* Annual = ∏(1+monthly) − 1 over the 12 calendar months; partial current year
  dropped (current snapshot ends 2025-04, so 2025 is excluded from annual).

## Spot-check (validation)

`all_equity_reits`: 1972 +8.01%, 2008 −37.73%, 2021 +41.30%, 2022 −24.95%,
2023 +11.36% — match published Nareit figures.

## NOT the same as JST housing

REITs are **levered, exchange-traded commercial-real-estate equity** (stock-like
~18% vol, −51% GFC drawdown, 0.55 correlation with stocks). JST `Housing_TR` is
the **unlevered, appraisal/transaction-smoothed** total return to residential
dwellings (~4% measured vol, bond-like). Correlation between the two over
1972-2024 is only 0.29. They are different assets — see the analysis doc.

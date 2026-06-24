import { test, expect, type Page } from "@playwright/test";

// Stub the lightweight GETs every page fires on mount so the smoke tests never
// depend on a live backend. Heavy compute endpoints are only hit on user
// action (a "run" button), which these tests deliberately never click.
async function mockInitApi(page: Page) {
  await page.route("**/api/defaults", (route) =>
    route.fulfill({
      json: {
        tier: "mid",
        cores: 4,
        memory_gb: 8,
        recommended_sim_counts: { default: 1000, heavy: 1000, guardrail: 500, allocation: 500 },
      },
    }),
  );
  await page.route("**/api/countries**", (route) =>
    route.fulfill({
      json: {
        countries: [
          { iso: "USA", name_en: "United States", name_zh: "美国", min_year: 1900, max_year: 2025, n_years: 126 },
        ],
      },
    }),
  );
  await page.route("**/api/historical-events**", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/buy-vs-rent/countries**", (route) => route.fulfill({ json: { countries: [] } }));
}

const PAGES = [
  { name: "simulator (home)", path: "/" },
  { name: "guardrail", path: "/guardrail" },
  { name: "allocation", path: "/allocation" },
  { name: "accumulation", path: "/accumulation" },
  { name: "methodology", path: "/methodology" },
];

// Network failures for un-mocked/asset requests and third-party analytics are
// not what these smoke tests are guarding against — only app-level crashes
// (hydration errors, missing i18n keys, render exceptions) should fail a page.
const IGNORE = /analytics|speed-insights|vitals|favicon|net::ERR_|Failed to load resource/i;

for (const { name, path } of PAGES) {
  test(`${name} loads without crashing`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(`console.error: ${m.text()}`);
    });

    await mockInitApi(page);
    const resp = await page.goto(path, { waitUntil: "domcontentloaded" });
    expect(resp?.status(), `HTTP status for ${path}`).toBeLessThan(400);

    // The navbar lives in the root layout, so its presence proves routing +
    // client hydration completed without throwing.
    await expect(page.locator("nav").first()).toBeVisible({ timeout: 15_000 });

    const real = errors.filter((e) => !IGNORE.test(e));
    expect(real, `unexpected errors on ${path}:\n${real.join("\n")}`).toEqual([]);
  });
}

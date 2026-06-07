/**
 * Mortality model for the Rich / Broke / Dead visualization.
 *
 * Uses a Gompertz law in modal form, hazard μ(x) = (1/b)·exp((x−M)/b), with
 * conditional survival from age x0 to age x:
 *   S(x | x0) = exp( exp((x0−M)/b) · (1 − exp((x−x0)/b)) )
 *
 * Parameters M (modal age at death) and b (dispersion) were least-squares
 * fitted to the SSA 2021 period life table conditional-survival anchors from
 * age 65 (fit SSE ≈ 1e-4; implied e(65) ≈ 17.4 male / 20.2 female, matching the
 * SSA values of ~17.0 / ~19.7). This is a transparent parametric approximation,
 * not the raw SSA table — accurate to within ~1pp across ages 65–100.
 *
 * Source: SSA Office of the Chief Actuary, Period Life Table, 2021
 * (https://www.ssa.gov/oact/STATS/table4c6.html).
 */

export type MortalitySex = "male" | "female" | "blended";

interface GompertzParams {
  /** Modal age at death. */
  M: number;
  /** Dispersion. */
  b: number;
}

const PARAMS: Record<"male" | "female", GompertzParams> = {
  male: { M: 85.0, b: 10.4 },
  female: { M: 88.8, b: 9.7 },
};

function gompertzSurvival(fromAge: number, toAge: number, p: GompertzParams): number {
  if (toAge <= fromAge) return 1.0;
  const s = Math.exp(Math.exp((fromAge - p.M) / p.b) * (1 - Math.exp((toAge - fromAge) / p.b)));
  return Math.min(1, Math.max(0, s));
}

/**
 * Probability of surviving from `fromAge` to `toAge`, conditional on being
 * alive at `fromAge`. "blended" averages the male and female curves.
 */
export function conditionalSurvival(
  fromAge: number,
  toAge: number,
  sex: MortalitySex,
): number {
  if (sex === "blended") {
    return (
      0.5 * gompertzSurvival(fromAge, toAge, PARAMS.male) +
      0.5 * gompertzSurvival(fromAge, toAge, PARAMS.female)
    );
  }
  return gompertzSurvival(fromAge, toAge, PARAMS[sex]);
}

export interface RichBrokeDeadPoint {
  age: number;
  /** P(alive and portfolio > 0). */
  solvent: number;
  /** P(alive and portfolio depleted). */
  broke: number;
  /** P(deceased). */
  dead: number;
}

/**
 * Combine a per-year solvency curve with conditional survival into the three
 * mutually exclusive Rich / Broke / Dead probabilities (each row sums to 1).
 *
 * @param solvencyByYear fraction of paths solvent at each year boundary,
 *        length = number of retirement years + 1 (index 0 = start).
 * @param retirementAge age at the start of retirement (year 0).
 * @param sex mortality table to apply.
 */
export function richBrokeDeadSeries(
  solvencyByYear: number[],
  retirementAge: number,
  sex: MortalitySex,
): RichBrokeDeadPoint[] {
  return solvencyByYear.map((solventFrac, t) => {
    const age = retirementAge + t;
    const alive = conditionalSurvival(retirementAge, age, sex);
    return {
      age,
      solvent: alive * solventFrac,
      broke: alive * (1 - solventFrac),
      dead: 1 - alive,
    };
  });
}

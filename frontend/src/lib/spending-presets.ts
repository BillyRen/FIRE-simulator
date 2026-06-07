/**
 * Named spending-pattern presets.
 *
 * These are research-backed bundles of withdrawal-strategy parameters that map
 * onto the existing engine strategies (fixed / declining / smile). They give
 * users a recognizable starting point (e.g. "Bernicke Reality Retirement")
 * without having to hand-tune the underlying knobs. Selecting a preset applies
 * its `params`; the advanced strategy controls remain available for tweaking.
 *
 * Sources:
 * - Constant real ("4% rule"): Bengen 1994 / Trinity study — flat real spending.
 * - Bernicke Reality Retirement (Ty Bernicke, 2005): real spending declines
 *   through active retirement, stabilizing around age 76.
 * - Retirement Spending Smile (David Blanchett, 2014): real spending declines
 *   in the "go-go/slow-go" years then rises late for healthcare ("no-go").
 */
import type { FormParams } from "./types";

/** The subset of FormParams a preset controls. */
export type SpendingPresetParams = Pick<
  FormParams,
  | "withdrawal_strategy"
  | "declining_rate"
  | "declining_start_age"
  | "smile_decline_rate"
  | "smile_decline_start_age"
  | "smile_min_age"
  | "smile_increase_rate"
>;

export interface SpendingPreset {
  /** Stable id; also the i18n key suffix under `spendingPreset.*`. */
  id: string;
  params: SpendingPresetParams;
}

/** Sentinel id used when current params match no known preset. */
export const CUSTOM_PRESET_ID = "custom";

export const SPENDING_PRESETS: SpendingPreset[] = [
  {
    id: "constant_real",
    params: {
      withdrawal_strategy: "fixed",
      declining_rate: 0.02,
      declining_start_age: 65,
      smile_decline_rate: 0.01,
      smile_decline_start_age: 65,
      smile_min_age: 80,
      smile_increase_rate: 0.01,
    },
  },
  {
    id: "bernicke",
    params: {
      withdrawal_strategy: "declining",
      declining_rate: 0.025,
      declining_start_age: 56,
      smile_decline_rate: 0.01,
      smile_decline_start_age: 65,
      smile_min_age: 80,
      smile_increase_rate: 0.01,
    },
  },
  {
    id: "retirement_smile",
    params: {
      withdrawal_strategy: "smile",
      declining_rate: 0.02,
      declining_start_age: 65,
      smile_decline_rate: 0.015,
      smile_decline_start_age: 65,
      smile_min_age: 80,
      smile_increase_rate: 0.015,
    },
  },
];

const PRESET_KEYS = Object.keys(SPENDING_PRESETS[0].params) as (keyof SpendingPresetParams)[];

/**
 * Return the id of the preset whose controlled params all match `p`, or
 * CUSTOM_PRESET_ID if none match. For `fixed`, only the strategy matters
 * (declining/smile knobs are inert), so we match on strategy alone there.
 */
export function matchSpendingPreset(p: FormParams): string {
  for (const preset of SPENDING_PRESETS) {
    if (preset.params.withdrawal_strategy !== p.withdrawal_strategy) continue;
    if (p.withdrawal_strategy === "fixed") return preset.id;
    const allMatch = PRESET_KEYS.every((k) => preset.params[k] === p[k]);
    if (allMatch) return preset.id;
  }
  return CUSTOM_PRESET_ID;
}

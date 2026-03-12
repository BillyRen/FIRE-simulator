"use client";

import { memo } from "react";
import dynamic from "next/dynamic";
import type { PlotParams } from "react-plotly.js";
import { mergeLayout, mergeConfig } from "@/lib/chart-theme";

const Plot = dynamic(
  () =>
    import("react-plotly.js/factory").then((factory) => {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const Plotly = require("plotly.js/lib/core");
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      Plotly.register([require("plotly.js/lib/scatter"), require("plotly.js/lib/scatterternary"), require("plotly.js/lib/bar")]);
      return factory.default(Plotly);
    }),
  { ssr: false }
);

export default memo(function PlotlyChart({ layout, config, style, ...rest }: PlotParams) {
  return (
    <Plot
      {...rest}
      layout={mergeLayout(layout)}
      config={mergeConfig(config)}
      style={{ width: "100%", ...style }}
    />
  );
});

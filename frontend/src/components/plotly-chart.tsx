"use client";

import dynamic from "next/dynamic";
import type { PlotParams } from "react-plotly.js";

const Plot = dynamic(
  () =>
    import("react-plotly.js/factory").then((factory) => {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const Plotly = require("plotly.js/lib/core");
      // Only register the trace types we actually use
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      Plotly.register([require("plotly.js/lib/scatter"), require("plotly.js/lib/scatterternary")]);
      return factory.default(Plotly);
    }),
  { ssr: false }
);

export default function PlotlyChart(props: PlotParams) {
  return <Plot {...props} />;
}

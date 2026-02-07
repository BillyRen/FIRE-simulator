"use client";

import dynamic from "next/dynamic";
import type { PlotParams } from "react-plotly.js";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

export default function PlotlyChart(props: PlotParams) {
  return <Plot {...props} />;
}

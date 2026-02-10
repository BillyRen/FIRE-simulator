/* eslint-disable @typescript-eslint/no-explicit-any */
declare module "plotly.js/lib/core" {
  const Plotly: any;
  export = Plotly;
}

declare module "plotly.js/lib/scatter" {
  const scatter: any;
  export = scatter;
}

declare module "plotly.js/lib/scatterternary" {
  const scatterternary: any;
  export = scatterternary;
}

declare module "react-plotly.js/factory" {
  import type { PlotParams } from "react-plotly.js";
  import type { ComponentType } from "react";
  function createPlotlyComponent(plotly: any): ComponentType<PlotParams>;
  export default createPlotlyComponent;
}

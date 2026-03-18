import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "FIRE Lab — Monte Carlo Retirement Simulator";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          background: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "16px",
            marginBottom: "24px",
          }}
        >
          <span style={{ fontSize: "72px" }}>🔥</span>
          <span
            style={{
              fontSize: "64px",
              fontWeight: 800,
              color: "#f8fafc",
              letterSpacing: "-2px",
            }}
          >
            FIRE Lab
          </span>
        </div>
        <div
          style={{
            fontSize: "28px",
            color: "#94a3b8",
            textAlign: "center",
            maxWidth: "800px",
            lineHeight: 1.4,
          }}
        >
          Monte Carlo Retirement Simulator
        </div>
        <div
          style={{
            display: "flex",
            gap: "32px",
            marginTop: "40px",
            color: "#64748b",
            fontSize: "18px",
          }}
        >
          <span>150+ Years of Data</span>
          <span>·</span>
          <span>16 Countries</span>
          <span>·</span>
          <span>Block Bootstrap</span>
          <span>·</span>
          <span>Free & Open</span>
        </div>
        <div
          style={{
            position: "absolute",
            bottom: "32px",
            right: "40px",
            fontSize: "16px",
            color: "#475569",
          }}
        >
          fire.rens.ai
        </div>
      </div>
    ),
    { ...size }
  );
}

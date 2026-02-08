/**
 * CSV 下载工具函数
 */

/** 将二维数据转为 CSV 并触发浏览器下载 */
export function downloadCSV(
  filename: string,
  headers: string[],
  rows: (string | number)[][]
) {
  const escape = (v: string | number) => {
    const s = String(v);
    return s.includes(",") || s.includes('"') || s.includes("\n")
      ? `"${s.replace(/"/g, '""')}"`
      : s;
  };

  const lines = [
    headers.map(escape).join(","),
    ...rows.map((row) => row.map(escape).join(",")),
  ];
  const csv = "\uFEFF" + lines.join("\n"); // BOM for Excel Chinese support

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** 将 Record<string, number[]> 格式的轨迹数据转为行格式 CSV 下载 */
export function downloadTrajectories(
  filename: string,
  trajectories: Record<string, number[]>,
  xHeader = "年",
  xLabels?: (number | string)[]
) {
  const keys = Object.keys(trajectories).sort(
    (a, b) => Number(a) - Number(b)
  );
  const n = trajectories[keys[0]]?.length ?? 0;

  const headers = [xHeader, ...keys.map((k) => `P${k}`)];
  const rows: (string | number)[][] = [];
  for (let i = 0; i < n; i++) {
    const row: (string | number)[] = [xLabels ? xLabels[i] : i];
    for (const k of keys) {
      row.push(Math.round(trajectories[k][i] * 100) / 100);
    }
    rows.push(row);
  }

  downloadCSV(filename, headers, rows);
}

/** 将 Record<string, string>[] 格式的表格直接导出 CSV */
export function downloadTableRows(
  filename: string,
  rows: Array<Record<string, string>>
) {
  if (!rows || rows.length === 0) return;
  const headers = Object.keys(rows[0]);
  const data = rows.map((row) => headers.map((h) => row[h] ?? ""));
  downloadCSV(filename, headers, data);
}

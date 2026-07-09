// Client-side XLSX export. Works over data already loaded in the browser.
// Mirrors the old csv.js signature so call sites can swap drop-in.

/**
 * Trigger an .xlsx download from in-memory rows.
 * SheetJS is heavy (~1MB), so it is imported lazily here — only users who
 * actually export pay for it, and it stays out of the entry chunk.
 * @param {string} filename  e.g. "monitoring-stok-2026-06-30.xlsx"
 * @param {Array<{key:string,label:string}>} columns
 * @param {Array<object>} rows
 * @param {string} sheetName  worksheet tab name (max 31 chars)
 */
export async function downloadXlsx(filename, columns, rows, sheetName = "Data") {
  const XLSX = await import("xlsx");
  const header = columns.map((c) => c.label);
  const body = rows.map((r) =>
    columns.map((c) => {
      const v = r[c.key];
      return v === null || v === undefined ? "" : v;
    }),
  );

  const ws = XLSX.utils.aoa_to_sheet([header, ...body]);

  // Auto-ish column widths based on header + sampled cell lengths.
  ws["!cols"] = columns.map((c) => {
    let max = String(c.label ?? "").length;
    for (const r of rows.slice(0, 200)) {
      const len = String(r[c.key] ?? "").length;
      if (len > max) max = len;
    }
    return { wch: Math.min(50, Math.max(10, max + 2)) };
  });

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, sheetName.slice(0, 31) || "Data");
  XLSX.writeFile(wb, filename);
}

export function stamp() {
  return new Date().toISOString().slice(0, 10);
}

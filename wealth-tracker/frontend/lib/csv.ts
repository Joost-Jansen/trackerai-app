// A table as a file that opens in Excel without doing anything to it.
//
// Semicolons and not commas, with a UTF-8 BOM in front: Dutch Excel uses the
// semicolon as list separator and the comma as decimal sign, so a "correct"
// comma CSV with dots ends up there as one column of text. The BOM is what tells
// Excel it is UTF-8 — without those three bytes "Zuid-Afrika" gets a question
// mark in it.
//
// Numbers therefore also get Dutch decimals and *no* thousands dot: Excel reads
// "1555,19" as a number you can calculate with, "1.555,19" too, but that second
// one is one ambiguity more than needed.

const BOM = "﻿";
const SEP = ";";

/** A number as Dutch Excel recognises it as a number. */
export function csvNumber(value: number, decimals = 2): string {
  return value.toFixed(decimals).replace(".", ",");
}

function cell(value: string | number): string {
  const text = String(value);
  // Quotes, separators and line ends must be quoted, and a quote inside is doubled
  // — otherwise one company name with a semicolon in it shifts the whole row.
  if (/[";\r\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

/**
 * Prepares *rows* as a download. Does nothing on the server (there is no
 * document there), which does not matter either: it hangs off a click.
 */
export function downloadCsv(filename: string, headers: string[], rows: (string | number)[][]): void {
  if (typeof document === "undefined") return;

  const text = BOM + [headers, ...rows].map((row) => row.map(cell).join(SEP)).join("\r\n") + "\r\n";

  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoking straight away could abort the download in Safari before it has
  // started; a tick later it has certainly been picked up.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * "allocation-countries-2026-08-03.csv" — a file you keep should say when it is from.
 */
export function stampedFilename(stem: string): string {
  const now = new Date();
  const date = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, "0"), String(now.getDate()).padStart(2, "0")].join("-");
  return `${stem}-${date}.csv`;
}

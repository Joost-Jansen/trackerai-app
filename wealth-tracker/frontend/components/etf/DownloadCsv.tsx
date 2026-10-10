"use client";

// The small button to the right of a card title with which you take the figures out.
//
// Small and without a border: it is a way out, not an action the card revolves
// around. But with the word CSV and not only an icon — a down arrow next to a
// chart might just as well mean "expand".
//
// The rows are only put together on the click. With fifteen hundred companies
// that is fifteen hundred lines of text you would otherwise build on every render
// for a button that is mostly not pressed.

import { DownloadIcon } from "@trackerai/ui/icons";
import { downloadCsv, stampedFilename } from "@/lib/csv";
import { tr } from "@/lib/i18n";

export default function DownloadCsv({
  stem,
  headers,
  rows,
  label = "CSV",
}: {
  /** File name without date and extension, for example "allocation-countries". */
  stem: string;
  headers: string[];
  rows: () => (string | number)[][];
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => downloadCsv(stampedFilename(stem), headers, rows())}
      title={tr("Download these figures as CSV: opens in Excel")}
      className="-my-1 inline-flex items-center gap-1 whitespace-nowrap py-1 text-xs text-ink-muted hover:text-text"
    >
      <DownloadIcon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}

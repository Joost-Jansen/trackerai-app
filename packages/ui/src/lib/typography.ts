// Typographic corrections on a string that is already formatted.
//
// Why separate and not in lib/format.ts: that file is pinned character for
// character to charts.fmt_eu in the backend
// (backend/tests/domain/test_format_parity.py really runs it through). The minus
// rule is a reading rule for the screen, and so must not go in there — a CSV or
// an API response keeps its plain hyphen.

/**
 * The real minus sign (−, U+2212) instead of the hyphen Intl delivers.
 *
 * A hyphen is narrower and sits lower than the digits next to it, so "-1.234,56"
 * is slightly off in a column; U+2212 has the same width and height as a digit
 * and so aligns in a tabular column. Meridian prescribes it, and this is the
 * place where it goes in.
 *
 * Only a hyphen in front of a digit or a currency sign: a dash in "since
 * 2019-2024" or in a fund or activity name must stay what it is.
 */
export function trueMinus(text: string): string {
  return text.replace(/-(?=[\d€$£])/g, "−");
}

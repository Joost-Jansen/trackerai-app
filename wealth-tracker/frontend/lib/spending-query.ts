/** One place for changing the Spending filters in the address bar. */
export function modifySpendingQuery(query: string, modifications: Record<string, string | string[] | null>): string {
  const p = new URLSearchParams(query);
  p.delete("via");
  for (const [key, value] of Object.entries(modifications)) {
    p.delete(key);
    if (Array.isArray(value)) value.forEach((w) => p.append(key, w));
    else if (value) p.set(key, value);
  }
  return p.toString();
}

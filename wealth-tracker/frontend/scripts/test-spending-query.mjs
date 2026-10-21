import assert from "node:assert/strict";
import { test } from "node:test";
import { modifySpendingQuery } from "../lib/spending-query.ts";

test("switching from 1M to 3M and 6M stays explicit and keeps the account filter", () => {
  let query = "period=1M&account=4";
  for (const period of ["3M", "6M", "1M"]) {
    query = modifySpendingQuery(query, { period, start: null, end: null });
    const p = new URLSearchParams(query);
    assert.equal(p.get("period"), period);
    assert.equal(p.get("account"), "4");
  }
});

test("a chosen period replaces custom dates and a temporary click-through filter", () => {
  const query = modifySpendingQuery("period=Custom&start=2026-01-01&end=2026-02-01&via=overview", {
    period: "3M",
    start: null,
    end: null,
  });
  assert.equal(query, "period=3M");
});

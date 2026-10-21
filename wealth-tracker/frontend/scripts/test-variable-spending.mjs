import assert from "node:assert/strict";
import { test } from "node:test";
import { variableSpending } from "../lib/variable-spending.ts";

const row = (id, type, amount, name, counterparty_iban = null) => ({ id, type, amount, name, counterparty_iban });

test("largest items contain no fixed costs, own transfers or receipts", () => {
  const rows = [
    row(1, "EXPENSE", 100, "Eenmalige aankoop"),
    row(2, "EXPENSE", 50, "Huur"),
    row(3, "EXPENSE", 300, "Overboeking", "nl12 abcd 1234 5678 90"),
    row(4, "INTERNAL", 400, "Overboeking"),
    row(5, "INCOME", -600, "Terugbetaling"),
    row(6, "EXPENSE", -25, "Terugboeking"),
  ];
  const off = variableSpending(rows, (name) => name === "Huur", new Set(["NL12ABCD1234567890"]));
  assert.deepEqual(
    off.map((r) => r.id),
    [1],
  );
});

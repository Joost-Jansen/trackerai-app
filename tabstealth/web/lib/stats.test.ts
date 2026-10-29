import { test } from "node:test";
import assert from "node:assert/strict";
import { duration, lastDays, weekMinutes } from "./stats.ts";

const today = new Date(2026, 9, 28);
const days = [
  { day: "2026-10-28", seconds: 600 },
  { day: "2026-10-25", seconds: 1200 },
  { day: "2026-10-18", seconds: 300 },
];

test("last days are filled with zeros, oldest first", () => {
  const d = lastDays(days, 4, today);
  assert.deepEqual(
    d.map((x) => x.day),
    ["2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28"],
  );
  assert.deepEqual(
    d.map((x) => x.minutes),
    [20, 0, 0, 10],
  );
});

test("this week against last week", () => {
  assert.deepEqual(weekMinutes(days, today), { thisWeek: 30, lastWeek: 5 });
});

test("durations", () => {
  assert.equal(duration(65 * 60), "1 h 05 min");
  assert.equal(duration(720), "12 min");
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { allTags, daysAgo, localDay, matches, sortSongs } from "./library.ts";

const song = (title: string, artist: string, extra: object = {}) => ({
  video: title, file: "", title, artist, edited: false, status: "new" as const, tags: [] as string[], favourite: false,
  practised_seconds: 0, last_practised: null as string | null, ...extra,
});
const list = [
  song("Mr. Blue Sky", "Electric Light Orchestra", { status: "learning", tags: ["capo"], favourite: true, practised_seconds: 300, last_practised: "2026-10-20", converted: "2026-10-01" }),
  song("Billie Jean", "Michael Jackson", { practised_seconds: 900, last_practised: "2026-10-27", converted: "2026-10-03", to_review: 2 }),
  song("Fake Plastic Trees", "Radiohead", { status: "mastered", tags: ["slow", "capo"], converted: "2026-10-02" }),
];

test("search looks at title, artist and tags", () => {
  const f = (query: string) => list.filter((s) => matches(s, { query, status: "all", tag: null })).map((s) => s.title);
  assert.deepEqual(f("radio"), ["Fake Plastic Trees"]);
  assert.deepEqual(f("CAPO"), ["Mr. Blue Sky", "Fake Plastic Trees"]);
});

test("status, favourites, review and tag filters", () => {
  const f = (status: any, tag: string | null = null) => list.filter((s) => matches(s, { query: "", status, tag })).map((s) => s.title);
  assert.deepEqual(f("learning"), ["Mr. Blue Sky"]);
  assert.deepEqual(f("favourite"), ["Mr. Blue Sky"]);
  assert.deepEqual(f("review"), ["Billie Jean"]);
  assert.deepEqual(f("all", "slow"), ["Fake Plastic Trees"]);
  assert.deepEqual(allTags(list), ["capo", "slow"]);
});

test("sorting", () => {
  const t = (sort: any) => sortSongs(list, sort).map((s) => s.title);
  assert.deepEqual(t("artist"), ["Mr. Blue Sky", "Billie Jean", "Fake Plastic Trees"]);
  assert.deepEqual(t("added"), ["Billie Jean", "Fake Plastic Trees", "Mr. Blue Sky"]);
  assert.deepEqual(t("practised"), ["Billie Jean", "Mr. Blue Sky", "Fake Plastic Trees"]);
  assert.deepEqual(t("most"), ["Billie Jean", "Mr. Blue Sky", "Fake Plastic Trees"]);
});

test("dates", () => {
  assert.equal(daysAgo("2026-10-25", new Date(2026, 9, 28)), 3);
  assert.equal(localDay(new Date(2026, 0, 5)), "2026-01-05");
});

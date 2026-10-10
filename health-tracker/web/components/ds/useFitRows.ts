"use client";

// How many rows of a list fit in the height its card was given: for a list that fills the end of a column (Columns),
// so the column ends level without empty space and without a half row. The list sits absolutely in a box that takes
// the height that is left (so it never makes the card taller); every row is assumed as tall as the first. Below lg
// (one column, nothing to align) every row shows. `count` is how many there are (or the most to show without fill).

import { useLayoutEffect, useRef, useState } from "react";

const WIDE = "(min-width: 1024px)";

export function useFitRows<T extends HTMLElement>(count: number, enabled = true) {
  const box = useRef<T>(null);
  const [rows, setRows] = useState(count);
  useLayoutEffect(() => {
    const el = box.current;
    if (!enabled || !el) {
      setRows(count);
      return;
    }
    const calc = () => {
      if (!window.matchMedia(WIDE).matches) return setRows(count);
      const first = el.querySelector("li") as HTMLElement | null;
      const h = first?.offsetHeight ?? 0;
      if (!h) return setRows(count);
      // never more than fit: a cut-off row looks broken (Columns gives the filler room for a few)
      setRows(Math.max(1, Math.min(count, Math.floor((el.clientHeight + 1) / h))));
    };
    calc();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(calc);
    ro.observe(el);
    window.addEventListener("resize", calc);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", calc);
    };
  }, [count, enabled]);
  return { box, rows };
}

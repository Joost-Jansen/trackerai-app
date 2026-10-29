// Logging practice time from a player that is not the tab player (a saved video): the seconds it plays, sent every
// 30 s and when it stops (POST /api/practice).

import { useEffect, useRef } from "react";
import { localDay } from "./library.ts";

export function usePracticeLog(video: string, playing: boolean, speed: () => number) {
  const seconds = useRef(0);
  useEffect(() => {
    const flush = () => {
      if (seconds.current < 1) return;
      void fetch("/api/practice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        keepalive: true,
        body: JSON.stringify({
          video,
          day: localDay(),
          seconds: Math.min(600, seconds.current),
          speed: speed(),
          source: "video",
          bars: null,
          whole_song: false,
        }),
      });
      seconds.current = 0;
    };
    if (!playing) return flush;
    const id = window.setInterval(() => {
      seconds.current += 1;
      if (seconds.current >= 30) flush();
    }, 1000);
    return () => {
      window.clearInterval(id);
      flush();
    };
  }, [video, playing, speed]);
}

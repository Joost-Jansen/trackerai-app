"use client";

// A saved video (no tab to read): watch it slower, loop a stretch (A-B), keep its status and tags, practice time
// counts, and convert it after all when it does have a tab.

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@trackerai/ui/ds/Button";
import { Select } from "@trackerai/ui/ds/Field";
import { PauseIcon, PlayIcon, RepeatIcon } from "@trackerai/ui/icons";
import SongChips from "@/components/SongChips";
import TopbarTitle from "@/components/TopbarTitle";
import { api, type Song } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { usePracticeLog } from "@/lib/practiceLog";
import { loadYouTube } from "@/lib/scripts";

const RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5];
const PLAYING = 1;
const clockTime = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function Watch({ vid }: { vid: string }) {
  const t = useT();
  const qc = useQueryClient();
  const router = useRouter();
  const songs = useQuery({ queryKey: ["songs"], queryFn: () => api.get<Song[]>("/api/songs") });
  const song = songs.data?.find((s) => s.video === vid);
  const el = useRef<HTMLDivElement>(null);
  const yt = useRef<any>(null);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [a, setA] = useState<number | null>(null);
  const [b, setB] = useState<number | null>(null);
  const [loop, setLoop] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const loopRef = useRef({ a, b, loop });
  loopRef.current = { a, b, loop };
  const rateRef = useRef(rate);
  rateRef.current = rate;
  usePracticeLog(vid, playing, useCallback(() => rateRef.current, []));

  useEffect(() => {
    let alive = true;
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const p = yt.current;
      const l = loopRef.current;
      if (!p?.getPlayerState || p.getPlayerState() !== PLAYING || !l.loop || l.a === null || l.b === null || l.b <= l.a) return;
      if (p.getCurrentTime() >= l.b) p.seekTo(l.a, true);
    };
    void loadYouTube().then((YT) => {
      if (!alive || !el.current) return;
      yt.current = new YT.Player(el.current, {
        videoId: vid,
        playerVars: { rel: 0, playsinline: 1, modestbranding: 1 },
        events: { onStateChange: (e: any) => setPlaying(e.data === PLAYING) },
      });
      raf = requestAnimationFrame(tick);
    });
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      yt.current?.destroy?.();
    };
  }, [vid]);
  useEffect(() => yt.current?.setPlaybackRate?.(rate), [rate]);

  const playPause = () => {
    const p = yt.current;
    if (!p?.getPlayerState) return;
    if (p.getPlayerState() === PLAYING) p.pauseVideo();
    else {
      const l = loopRef.current;
      if (l.loop && l.a !== null && (p.getCurrentTime() < l.a || (l.b !== null && p.getCurrentTime() >= l.b))) p.seekTo(l.a, true);
      p.playVideo();
    }
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.code !== "Space" || ["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(tag)) return;
      e.preventDefault();
      playPause();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  const now = () => Math.round((yt.current?.getCurrentTime?.() ?? 0) * 10) / 10;

  const convert = async () => {
    await api.post(`/api/songs/${vid}/convert`);
    setMessage(t.watch.converting);
  };
  const remove = async () => {
    if (!window.confirm(t.watch.removeConfirm(song?.title ?? vid))) return;
    await api.del(`/api/songs/${vid}`);
    await qc.invalidateQueries({ queryKey: ["songs"] });
    router.push("/library/");
  };

  return (
    <div className="mx-auto flex max-w-[1000px] flex-col gap-3">
      <TopbarTitle
        title={song?.title ?? "…"}
        meta={song?.artist}
        chips={song && <SongChips song={song} />}
        back="/library/"
        backLabel={t.song.back}
        actions={
          <Button variant="primary" size="sm" onClick={playPause} aria-label={playing ? t.song.pause : t.song.play} icon={playing ? <PauseIcon className="h-[15px] w-[15px]" /> : <PlayIcon className="h-[15px] w-[15px]" />} />
        }
      />
      <div className="ts-video w-full" style={{ aspectRatio: "16 / 9" }}>
        <div style={{ position: "absolute", inset: 0 }}>
          <div ref={el} />
        </div>
      </div>

      <section className="flex flex-wrap items-center gap-2 rounded border border-border bg-surface p-3 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-xs text-ink-muted">{t.song.speed}</span>
          <Select value={String(rate)} onChange={(e) => setRate(Number(e.target.value))} aria-label={t.song.speed}>
            {RATES.map((r) => (
              <option key={r} value={r}>
                {Math.round(r * 100)}%
              </option>
            ))}
          </Select>
        </label>
        <span className="mx-1 h-5 w-px bg-border" aria-hidden />
        <Button size="sm" onClick={() => setA(now())}>
          A {a !== null ? clockTime(a) : "–"}
        </Button>
        <Button size="sm" onClick={() => setB(now())}>
          B {b !== null ? clockTime(b) : "–"}
        </Button>
        <button
          type="button"
          aria-pressed={loop}
          disabled={a === null || b === null || b <= a}
          onClick={() => setLoop((v) => !v)}
          title={t.watch.loopAB}
          className={`ds-btn ds-btn--sm ds-btn--secondary !px-2 disabled:opacity-40 ${loop ? "!border-brand !text-brand" : ""}`}
        >
          <RepeatIcon className="h-[15px] w-[15px]" />
          <span className="ml-1">{t.watch.loopAB}</span>
        </button>
        {(a !== null || b !== null) && (
          <button type="button" className="text-xs text-ink-muted hover:underline" onClick={() => { setA(null); setB(null); setLoop(false); }}>
            {t.watch.clear}
          </button>
        )}
        <span className="ml-auto flex items-center gap-3">
          <button type="button" className="text-xs font-semibold text-brand hover:underline" onClick={() => void convert()}>
            {t.watch.convert}
          </button>
          <button type="button" className="text-xs text-ink-muted hover:underline" onClick={() => void remove()}>
            {t.watch.remove}
          </button>
        </span>
      </section>
      {message && <p className="text-xs text-ink-muted">{message}</p>}
    </div>
  );
}

function WatchPage() {
  const vid = useSearchParams().get("v");
  return vid ? <Watch key={vid} vid={vid} /> : null;
}

export default function Page() {
  return (
    <Suspense>
      <WatchPage />
    </Suspense>
  );
}

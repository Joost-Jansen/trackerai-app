"use client";

// A song: the original video next to its tab, in sync, with one sound source at a time, and an editor per beat.
//
//   sound = video  the YouTube player plays; the tab cursor follows its clock
//   sound = tab    alphaTab plays the Guitar Pro file (any speed, loops); the video follows, muted
//
// Both clocks meet in lib/sync.ts: the converter measured when every bar starts in the video. Clicking a beat
// seeks both and opens it in the editor; a saved edit reloads the tab where you were.

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Button } from "@trackerai/ui/ds/Button";
import { Checkbox, Select } from "@trackerai/ui/ds/Field";
import Tabs from "@trackerai/ui/ds/Tabs";
import { api, type Song } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { TOPBAR_SLOT } from "@/lib/nav";
import { ALPHATAB_BASE, loadAlphaTab, loadYouTube } from "@/lib/scripts";
import { MusicIcon, PauseIcon, PlayIcon, StopIcon, VideoIcon } from "@trackerai/ui/icons";
import { gpString, makeClock, nearestRate, type Clock, type Timing } from "@/lib/sync";

type Source = "video" | "tab";
type Selected = { bar: number; beat: number; frets: string[] }; // frets[0] = high e
const STRINGS = ["e", "B", "G", "D", "A", "E"];
const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5];
const YT_PLAYING = 1;

/** A sound source in the switch: its icon, the name for screen readers and as a tooltip. */
function SoundLabel({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <span className="inline-flex items-center gap-1.5" title={text}>
      {icon}
      <span className="sr-only">{text}</span>
    </span>
  );
}

export default function TabStudio({ vid }: { vid: string }) {
  const t = useT();
  const qc = useQueryClient();
  const songs = useQuery({ queryKey: ["songs"], queryFn: () => api.get<Song[]>("/api/songs") });
  const timing = useQuery({ queryKey: ["timing", vid], queryFn: () => api.get<Timing>(`/api/songs/${vid}/timing`) });
  const song = songs.data?.find((s) => s.video === vid);

  const sheet = useRef<HTMLDivElement>(null);
  const pinned = useRef<HTMLDivElement>(null);
  const ytEl = useRef<HTMLDivElement>(null);
  const at = useRef<any>(null);
  const yt = useRef<any>(null);
  const clock = useRef<Clock | null>(null);
  const sourceRef = useRef<Source>("video");
  const restore = useRef<{ tick: number; bar: number; beat: number } | null>(null);

  const [source, setSourceState] = useState<Source>("video");
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [loop, setLoop] = useState(false);
  const [hands, setHands] = useState(false); // full video by default: its own tab strip stays visible
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<Selected | null>(null);
  const [box, setBox] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const tabUrl = `/api/songs/${vid}/tab`;

  // ── selection ──────────────────────────────────────────────────────────────
  const beatAt = (bar: number, beat: number) => at.current?.score?.tracks[0].staves[0].bars[bar]?.voices[0].beats[beat];
  const outline = useCallback((beat: any) => {
    const b = beat && at.current?.renderer?.boundsLookup?.findBeat(beat);
    setBox(b ? { x: b.visualBounds.x, y: b.visualBounds.y, w: b.visualBounds.w, h: b.visualBounds.h } : null);
  }, []);
  const select = useCallback(
    (beat: any, keepMessage = false) => {
      const frets = ["", "", "", "", "", ""];
      for (const n of beat.notes) frets[gpString(n.string) - 1] = n.isDead ? "x" : String(n.fret);
      setSelected({ bar: beat.voice.bar.index, beat: beat.index, frets });
      if (!keepMessage) setMessage(null);
      outline(beat);
    },
    [outline],
  );

  // ── alphaTab ───────────────────────────────────────────────────────────────
  useEffect(() => {
    let alive = true;
    void loadAlphaTab().then((alphaTab) => {
      if (!alive || !sheet.current) return;
      const a = new alphaTab.AlphaTabApi(sheet.current, {
        core: { fontDirectory: `${ALPHATAB_BASE}font/` },
        display: { staveProfile: "Tab", layoutMode: "Page" },
        notation: { rhythmMode: "ShowWithBars" },
        player: {
          enablePlayer: true,
          enableCursor: true,
          enableUserInteraction: true,
          soundFont: `${ALPHATAB_BASE}soundfont/sonivox.sf2`,
          scrollMode: alphaTab.ScrollMode.Off, // ours below: alphaTab's misjudges the offset in this layout
        },
      });
      at.current = a;
      a.scoreLoaded.on((score: any) => {
        clock.current = timing.data
          ? makeClock(timing.data, score.masterBars.map((mb: any) => ({ start: mb.start, duration: mb.calculateDuration() })))
          : null;
      });
      a.renderFinished.on(() => {
        setLoaded(true);
        const r = restore.current;
        if (r) {
          restore.current = null;
          a.tickPosition = r.tick;
          const beat = beatAt(r.bar, r.beat);
          if (beat) select(beat, true); // after a save: keep "Saved" in view
        }
      });
      a.playerStateChanged.on((e: any) => {
        if (sourceRef.current !== "tab") return;
        const on = e.state === 1;
        setPlaying(on);
        if (!on) yt.current?.pauseVideo?.();
      });
      // Tab plays: keep the (muted) video at the same moment.
      a.playerPositionChanged.on((e: any) => {
        if (sourceRef.current !== "tab" || a.playerState !== 1 || !clock.current || !yt.current?.getCurrentTime) return;
        const target = clock.current.tickToTime(e.currentTick);
        if (yt.current.getPlayerState() !== YT_PLAYING) yt.current.playVideo();
        if (Math.abs(yt.current.getCurrentTime() - target) > 0.25) yt.current.seekTo(target, true);
      });
      a.beatMouseDown.on((beat: any) => {
        select(beat);
        if (sourceRef.current === "video" && clock.current && yt.current?.seekTo) {
          yt.current.seekTo(clock.current.tickToTime(beat.absolutePlaybackStart), true);
        }
      });
      a.load(`${tabUrl}?t=${Date.now()}`);
    });
    return () => {
      alive = false;
      at.current?.destroy();
      at.current = null;
    };
    // timing must be known before the tab loads (the clock is built on scoreLoaded)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vid, timing.data]);

  // ── YouTube ────────────────────────────────────────────────────────────────
  useEffect(() => {
    let alive = true;
    let raf = 0;
    let lastPush = 0;
    let lastCheck = 0;
    // Keep the bar being played in view (both sources), below the sticky top bar.
    const keepInView = (now: number) => {
      if (now - lastCheck < 250) return;
      lastCheck = now;
      const playingNow =
        (sourceRef.current === "tab" && at.current?.playerState === 1) ||
        (sourceRef.current === "video" && yt.current?.getPlayerState?.() === YT_PLAYING);
      const bar = playingNow ? sheet.current?.querySelector(".at-cursor-bar") : null;
      if (!bar) return;
      // below the top bar, or below the pinned video and controls on a narrow screen
      const pin = pinned.current;
      const top = pin && getComputedStyle(pin).position === "sticky" ? pin.getBoundingClientRect().bottom + 8 : 80;
      const r = bar.getBoundingClientRect();
      if (r.top < top || r.bottom > window.innerHeight - 24) window.scrollBy({ top: r.top - top - 12, behavior: "smooth" });
    };
    // Video plays: move the tab cursor along with its clock (about 15 times a second is smooth enough).
    const follow = (now: number) => {
      raf = requestAnimationFrame(follow);
      keepInView(now);
      const p = yt.current;
      if (sourceRef.current !== "video" || !p?.getPlayerState || p.getPlayerState() !== YT_PLAYING) return;
      if (now - lastPush < 66 || !clock.current || !at.current) return;
      lastPush = now;
      at.current.tickPosition = clock.current.timeToTick(p.getCurrentTime());
    };
    void loadYouTube().then((YT) => {
      if (!alive || !ytEl.current) return;
      yt.current = new YT.Player(ytEl.current, {
        videoId: vid,
        playerVars: { rel: 0, playsinline: 1, modestbranding: 1 },
        events: {
          onStateChange: (e: any) => {
            if (sourceRef.current === "video") setPlaying(e.data === YT_PLAYING);
          },
        },
      });
      raf = requestAnimationFrame(follow);
    });
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      yt.current?.destroy?.();
      yt.current = null;
    };
  }, [vid]);

  // ── transport ──────────────────────────────────────────────────────────────
  const setSource = (s: Source) => {
    if (s === sourceRef.current) return;
    const a = at.current;
    const p = yt.current;
    a?.pause();
    p?.pauseVideo?.();
    setPlaying(false);
    if (clock.current && a && p?.getCurrentTime) {
      if (s === "tab") a.tickPosition = clock.current.timeToTick(p.getCurrentTime());
      else p.seekTo(clock.current.tickToTime(a.tickPosition), true);
    }
    if (s === "tab") p?.mute?.();
    else p?.unMute?.();
    sourceRef.current = s;
    setSourceState(s);
  };
  const playPause = () => {
    if (sourceRef.current === "tab") at.current?.playPause();
    else if (yt.current?.getPlayerState) {
      if (yt.current.getPlayerState() === YT_PLAYING) yt.current.pauseVideo();
      else yt.current.playVideo();
    }
  };
  const stop = () => {
    at.current?.stop();
    yt.current?.pauseVideo?.();
    if (clock.current) yt.current?.seekTo?.(clock.current.tickToTime(0), true);
  };
  useEffect(() => {
    if (at.current) at.current.playbackSpeed = speed;
    yt.current?.setPlaybackRate?.(nearestRate(speed));
  }, [speed]);
  useEffect(() => {
    if (at.current) at.current.isLooping = loop;
  }, [loop]);
  // Space plays and pauses, except while typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.code !== "Space" || tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || tag === "BUTTON") return;
      e.preventDefault();
      playPause();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ── editing ────────────────────────────────────────────────────────────────
  const save = async (frets: string[]) => {
    if (!selected) return;
    if (frets.some((f) => f !== "" && f.toLowerCase() !== "x" && !(/^\d{1,2}$/.test(f) && Number(f) <= 24))) {
      setMessage(t.song.invalidFret);
      return;
    }
    setSaving(true);
    try {
      const body = Object.fromEntries(frets.map((f, i) => [String(i + 1), f === "" ? null : f.toLowerCase() === "x" ? "x" : Number(f)]));
      await api.post(`/api/songs/${vid}/beats`, { bar: selected.bar, beat: selected.beat, frets: body });
      restore.current = { tick: at.current?.tickPosition ?? 0, bar: selected.bar, beat: selected.beat };
      at.current?.load(`${tabUrl}?t=${Date.now()}`);
      setMessage(t.song.saved);
      void qc.invalidateQueries({ queryKey: ["songs"] });
    } finally {
      setSaving(false);
    }
  };
  const restoreOriginal = async () => {
    if (!window.confirm(t.song.restoreConfirm)) return;
    await api.post(`/api/songs/${vid}/restore`);
    restore.current = { tick: at.current?.tickPosition ?? 0, bar: selected?.bar ?? 0, beat: selected?.beat ?? 0 };
    at.current?.load(`${tabUrl}?t=${Date.now()}`);
    void qc.invalidateQueries({ queryKey: ["songs"] });
  };

  // In development the players are reachable from the console (window.__tabstealth), for checking the sync.
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") (window as any).__tabstealth = { at, yt, clock, sourceRef };
  }, []);

  const crop = hands ?Math.min(Math.max(timing.data?.overlay_top ?? 0.66, 0.4), 1) : 1;

  // Play, stop and the sound switch live in the sticky top bar (app/(app)/layout.tsx gives the slot), always in reach.
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  useEffect(() => setSlot(document.getElementById(TOPBAR_SLOT)), []);
  const transport = (
    <div className="flex min-w-0 items-center gap-1.5">
      <Button
        variant="primary"
        size="sm"
        onClick={playPause}
        disabled={!loaded}
        aria-label={playing ? t.song.pause : t.song.play}
        title={`${playing ? t.song.pause : t.song.play} (space)`}
        icon={playing ? <PauseIcon className="h-[15px] w-[15px]" /> : <PlayIcon className="h-[15px] w-[15px]" />}
      />
      <Button size="sm" onClick={stop} disabled={!loaded} aria-label={t.song.stop} title={t.song.stop} icon={<StopIcon className="h-[15px] w-[15px]" />} />
      <Tabs
        className="ml-1.5"
        items={[
          { id: "video", label: <SoundLabel icon={<VideoIcon className="h-[15px] w-[15px]" />} text={t.song.soundVideo} /> },
          { id: "tab", label: <SoundLabel icon={<MusicIcon className="h-[15px] w-[15px]" />} text={t.song.soundTab} /> },
        ]}
        value={source}
        onChange={(id: string) => setSource(id as Source)}
        ariaLabel={t.song.sound}
        variant="segmented"
      />
    </div>
  );

  return (
    // Wide: video and settings in a sticky column next to the tab. Narrow: one column; the left column dissolves
    // (`contents`) so the video can stick to the top while you scroll through the tab.
    <div className="flex flex-col gap-3 lg:grid lg:grid-cols-[minmax(360px,44%)_1fr] lg:gap-4">
      {slot ? createPortal(transport, slot) : null}
      <div className="contents lg:sticky lg:top-[72px] lg:flex lg:flex-col lg:gap-3 lg:self-start">
        <div>
          <Link href="/library/" className="text-xs font-semibold text-brand hover:underline">
            ← {t.song.back}
          </Link>
          <h2 className="mt-1 font-display text-xl font-light leading-tight">{song?.title ?? "…"}</h2>
          <div className="text-sm text-ink-muted">
            {[song?.artist, song?.tempo ? `♩ ${song.tempo}` : null, song?.capo ? t.library.capo(song.capo) : null, song?.swing ? t.library.swing : null]
              .filter(Boolean)
              .join(" · ")}
          </div>
        </div>

        {/* The video, whole by default; on a narrow screen it stays pinned under the top bar while you scroll the tab.
            At most about a third of the screen high, so the tab keeps room underneath. */}
        <div ref={pinned} className="sticky top-[52px] z-20 -mx-1 bg-bg px-1 pb-2 lg:static lg:m-0 lg:p-0">
          <div className="ts-video mx-auto w-full" style={{ aspectRatio: `16 / ${9 * crop}`, maxWidth: `calc(34vh * ${16 / (9 * crop)})` }}>
            <div style={{ position: "absolute", inset: 0, height: `${100 / crop}%` }}>
              <div ref={ytEl} />
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <label className="flex items-center gap-2">
            <span className="text-xs text-ink-muted">{t.song.speed}</span>
            <Select value={String(speed)} onChange={(e) => setSpeed(Number(e.target.value))} aria-label={t.song.speed}>
              {SPEEDS.map((s) => (
                <option key={s} value={s}>
                  {Math.round(s * 100)}%
                </option>
              ))}
            </Select>
          </label>
          <Checkbox checked={loop} onChange={setLoop} label={t.song.loop} />
          <Checkbox checked={hands} onChange={setHands} label={t.song.hands} />
        </div>

        <Card title={selected ? t.song.editTitle(selected.bar + 1, selected.beat + 1) : undefined}>
          {!selected ? (
            <p className="text-sm text-ink-muted">{t.song.editHint}</p>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void save(selected.frets);
              }}
            >
              <div className="grid grid-cols-6 gap-1.5">
                {STRINGS.map((name, i) => (
                  <label key={name + i} className="flex flex-col items-center gap-1">
                    <span className="font-mono text-xs text-ink-muted">{name}</span>
                    <input
                      className="ds-input w-full text-center font-mono"
                      value={selected.frets[i]}
                      maxLength={2}
                      inputMode="numeric"
                      aria-label={`${name} string`}
                      onChange={(e) => {
                        const frets = [...selected.frets];
                        frets[i] = e.target.value.trim();
                        setSelected({ ...selected, frets });
                      }}
                    />
                  </label>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button type="submit" variant="primary" size="sm" disabled={saving}>
                  {t.song.apply}
                </Button>
                <Button size="sm" disabled={saving} onClick={() => void save(["", "", "", "", "", ""])}>
                  {t.song.clear}
                </Button>
                {message && <span className="text-xs text-ink-muted">{message}</span>}
              </div>
            </form>
          )}
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-border pt-3 text-xs">
            <a className="font-semibold text-brand hover:underline" href={tabUrl} download={song?.file}>
              {t.song.downloadGp5}
            </a>
            <a className="font-semibold text-brand hover:underline" href={`/api/songs/${vid}/text`} target="_blank" rel="noreferrer">
              {t.song.downloadText}
            </a>
            {song?.edited && (
              <button type="button" className="font-semibold text-ink-muted underline-offset-4 hover:underline" onClick={() => void restoreOriginal()}>
                {t.song.restore}
              </button>
            )}
          </div>
        </Card>
      </div>

      <section className="ts-sheet relative min-h-[60vh] overflow-hidden rounded border border-border">
        {!loaded && <p className="absolute left-4 top-4 text-sm text-ink-muted">{t.song.loadingTab}</p>}
        <div className="relative">
          <div ref={sheet} />
          {box && <div className="ts-selected" style={{ left: box.x - 3, top: box.y - 3, width: box.w + 6, height: box.h + 6 }} />}
        </div>
      </section>
    </div>
  );
}

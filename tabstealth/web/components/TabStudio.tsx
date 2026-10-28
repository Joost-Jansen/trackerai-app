"use client";

// A song: the original video next to its tab, in sync, with one sound source at a time, and an editor per beat.
//
//   sound = video  the YouTube player plays; the tab cursor follows its clock
//   sound = tab    alphaTab plays the Guitar Pro file (any speed, loops); the video follows, muted
//
// Both clocks meet in lib/sync.ts: the converter measured when every bar starts in the video. Clicking a beat
// seeks both and opens it in the editor; a saved edit reloads the tab where you were.

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@trackerai/ui/ds/Button";
import { Checkbox, Select } from "@trackerai/ui/ds/Field";
import Tabs from "@trackerai/ui/ds/Tabs";
import { api, type Song } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { ALPHATAB_BASE, loadAlphaTab, loadYouTube } from "@/lib/scripts";
import { DownloadIcon, MusicIcon, NewspaperIcon, PauseIcon, PlayIcon, RefreshIcon, StopIcon, VideoIcon } from "@trackerai/ui/icons";
import { makeClock, nearestRate, type Clock, type Timing } from "@/lib/sync";
import { beatAtGpIndex, emptyNote, fromAlphaTab, fromApi, gpBeatIndex, invalid, mainBeat, toRequest, type ApiBeat, type BeatState } from "@/lib/beat";
import BeatEditor from "@/components/BeatEditor";

type Source = "video" | "tab";
// The beat being edited: its bar, its index in the Guitar Pro file (grace notes not counted), the form, and the
// section it had (only a changed section is saved).
type Selected = { bar: number; beat: number; state: BeatState; section: string };
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
  const beatAt = (bar: number, beat: number) => beatAtGpIndex(at.current?.score?.tracks[0].staves[0].bars[bar], beat);
  const outline = useCallback((beat: any) => {
    const b = beat && at.current?.renderer?.boundsLookup?.findBeat(beat);
    setBox(b ? { x: b.visualBounds.x, y: b.visualBounds.y, w: b.visualBounds.w, h: b.visualBounds.h } : null);
  }, []);
  const select = useCallback(
    (clicked: any, keepMessage = false) => {
      const beat = mainBeat(clicked); // a grace note belongs to the beat after it
      const state = fromAlphaTab(beat);
      const bar = beat.voice.bar.index;
      const index = gpBeatIndex(beat);
      setSelected({ bar, beat: index, state, section: state.section });
      if (!keepMessage) setMessage(null);
      outline(beat);
      // then the beat exactly as the file has it, unless another beat was picked meanwhile
      void api.get<ApiBeat>(`/api/songs/${vid}/beats/${bar}/${index}`).then((b) => {
        const exact = fromApi(b);
        setSelected((cur) => (cur && cur.bar === bar && cur.beat === index ? { ...cur, state: exact, section: exact.section } : cur));
      });
    },
    [outline, vid],
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
  const save = async (state: BeatState) => {
    if (!selected) return;
    if (invalid(state)) {
      setMessage(t.song.invalidFret);
      return;
    }
    setSaving(true);
    try {
      await api.post(`/api/songs/${vid}/beats`, toRequest(selected.bar, selected.beat, state));
      if (state.section.trim() !== selected.section.trim()) {
        await api.post(`/api/songs/${vid}/bars`, { bar: selected.bar, section: state.section.trim() || null });
      }
      restore.current = { tick: at.current?.tickPosition ?? 0, bar: selected.bar, beat: selected.beat };
      at.current?.load(`${tabUrl}?t=${Date.now()}`);
      setMessage(t.song.saved);
      void qc.invalidateQueries({ queryKey: ["songs"] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : t.common.error);
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

  // Play, stop and the sound switch, in the song's header (pinned with the video on a narrow screen).
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
      <div className="contents lg:sticky lg:top-[72px] lg:flex lg:flex-col lg:gap-3 lg:self-start">
        {/* The song's header and the video. On a narrow screen both stay pinned under the top bar while you scroll the
            tab; the video is at most about a third of the screen high, so the tab keeps room underneath. */}
        <div ref={pinned} className="sticky top-[52px] z-20 -mx-1 flex flex-col gap-2 bg-bg px-1 pb-2 lg:static lg:m-0 lg:gap-3 lg:p-0">
          <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-2">
            <div className="min-w-0">
              <Link href="/library/" className="text-xs font-semibold text-brand hover:underline">
                ← {t.song.back}
              </Link>
              <div className="mt-1 flex items-center gap-1">
                <h2 className="truncate font-display text-xl font-light leading-tight">{song?.title ?? "…"}</h2>
                <a className="ds-btn ds-btn--ghost ds-btn--sm !px-1.5" href={tabUrl} download={song?.file} title={t.song.downloadGp5} aria-label={t.song.downloadGp5}>
                  <DownloadIcon className="h-[15px] w-[15px]" />
                </a>
                <a className="ds-btn ds-btn--ghost ds-btn--sm !px-1.5" href={`/api/songs/${vid}/text`} target="_blank" rel="noreferrer" title={t.song.downloadText} aria-label={t.song.downloadText}>
                  <NewspaperIcon className="h-[15px] w-[15px]" />
                </a>
                {song?.edited && (
                  <button type="button" className="ds-btn ds-btn--ghost ds-btn--sm !px-1.5" onClick={() => void restoreOriginal()} title={t.song.restore} aria-label={t.song.restore}>
                    <RefreshIcon className="h-[15px] w-[15px]" />
                  </button>
                )}
              </div>
              <div className="truncate text-sm text-ink-muted">
                {[song?.artist, song?.tempo ? `♩ ${song.tempo}` : null, song?.capo ? t.library.capo(song.capo) : null, song?.swing ? t.library.swing : null]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
            </div>
            {transport}
          </div>
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

        {selected && (
          <BeatEditor
            title={t.song.editTitle(selected.bar + 1, selected.beat + 1)}
            value={selected.state}
            onChange={(update) => setSelected((cur) => (cur ? { ...cur, state: update(cur.state) } : cur))}
            onSave={() => void save(selected.state)}
            onClear={() => void save({ ...selected.state, notes: selected.state.notes.map(() => emptyNote()), strum: "" })}
            saving={saving}
            message={message}
          />
        )}
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

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
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@trackerai/ui/ds/Button";
import { Select, Switch } from "@trackerai/ui/ds/Field";
import Tabs from "@trackerai/ui/ds/Tabs";
import { api, type Job, type Song } from "@/lib/api";
import { applyView, BARS_PER_ROW, readView, saveView, type SheetView } from "@/lib/sheetView";
import { useT } from "@/lib/i18n";
import { ALPHATAB_BASE, loadAlphaTab, loadYouTube } from "@/lib/scripts";
import RowMenu from "@trackerai/ui/ds/RowMenu";
import { TOPBAR_ACTIONS, TOPBAR_TITLE } from "@/lib/nav";
import {
  CheckIcon,
  ChevronLeftIcon,
  HandIcon,
  LayoutIcon,
  RepeatIcon,
  MusicIcon,
  PauseIcon,
  PlayIcon,
  StopIcon,
  VideoIcon,
} from "@trackerai/ui/icons";
import { makeClock, nearestRate, type BarTicks, type Clock, type Timing } from "@/lib/sync";
import {
  beatAtGpIndex,
  emptyNote,
  fromAlphaTab,
  fromApi,
  gpBeatIndex,
  invalid,
  KEYS,
  mainBeat,
  nextBend,
  toRequest,
  type ApiBeat,
  type BeatState,
  type NoteState,
} from "@/lib/beat";
import BeatEditor from "@/components/BeatEditor";
import SongChips from "@/components/SongChips";
import PracticePanel, { PERCENTS } from "@/components/PracticePanel";
import ReviewPanel, { type ReviewItem } from "@/components/ReviewPanel";
import { barAt, beatAt as beatOf, DEFAULT_PRACTICE, nextSpeed, rangeTicks, type Practice } from "@/lib/practice";
import { click, countIn } from "@/lib/click";
import { localDay } from "@/lib/library";
import type { AtApi, AtBeat, YtPlayer } from "@/lib/vendor";

type Source = "video" | "tab";
// The beat being edited: its bar, its index in the Guitar Pro file (grace notes not counted), the form, and the
// section it had (only a changed section is saved).
type Selected = { bar: number; beat: number; state: BeatState; section: string; saved: BeatState };
type Spot = { bar: number; beat: number };
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
  const scroller = useRef<HTMLElement>(null);
  // Where the tab panel sticks: under the top bar, or on a narrow screen under the pinned video too.
  const [sheetTop, setSheetTop] = useState(72);
  const [barHeight, setBarHeight] = useState(52); // the sticky top bar's real height (taller on a phone)
  useEffect(() => {
    const pin = pinned.current;
    if (!pin) return;
    const measure = () => {
      const bar = Math.round(document.querySelector(".ds-topbar")?.getBoundingClientRect().height ?? 52);
      setBarHeight(bar);
      setSheetTop(getComputedStyle(pin).position === "sticky" ? bar + pin.offsetHeight + 8 : bar + 16);
    };
    const ro = new ResizeObserver(measure);
    ro.observe(pin);
    window.addEventListener("resize", measure);
    measure();
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);
  const ytEl = useRef<HTMLDivElement>(null);
  const at = useRef<AtApi | null>(null);
  const yt = useRef<YtPlayer | null>(null);
  const clock = useRef<Clock | null>(null);
  const sourceRef = useRef<Source>("video");
  // after a reload of the tab (save, undo, redo): where the cursor was and which beat to select
  const restore = useRef<{ tick: number; spot: Spot | null } | null>(null);
  const [view, setViewState] = useState<SheetView | null>(null); // read from this device once mounted

  const [source, setSourceState] = useState<Source>("video");
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  // practising (lib/practice.ts): loop range, speed trainer, count-in, metronome; the refs feed the player callbacks
  const [practice, setPractice] = useState<Practice>(DEFAULT_PRACTICE);
  const practiceRef = useRef(practice);
  practiceRef.current = practice;
  const [passes, setPasses] = useState(0);
  const speedRef = useRef(1);
  const bars = useRef<BarTicks[]>([]);
  const meter = useRef({ numerator: 4, denominator: 4, tempo: 120 });
  const [hands, setHands] = useState(false); // full video by default: its own tab strip stays visible
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<Selected | null>(null);
  const [box, setBox] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const tabUrl = `/api/songs/${vid}/tab`;

  // ── selection ──────────────────────────────────────────────────────────────
  const beatAt = (bar: number, beat: number) => beatAtGpIndex(at.current?.score?.tracks[0].staves[0].bars[bar], beat);
  const outline = useCallback((beat: AtBeat | undefined) => {
    const b = beat && at.current?.renderer?.boundsLookup?.findBeat(beat);
    setBox(b ? { x: b.visualBounds.x, y: b.visualBounds.y, w: b.visualBounds.w, h: b.visualBounds.h } : null);
  }, []);
  // keep a selected beat in view inside the tab panel (keyboard navigation can move it off screen)
  const reveal = useCallback((beat: AtBeat) => {
    const b = at.current?.renderer?.boundsLookup?.findBeat(beat);
    const panel = scroller.current;
    if (!b || !panel) return;
    const { y, h } = b.visualBounds;
    if (y < panel.scrollTop + 16 || y + h > panel.scrollTop + panel.clientHeight - 16) {
      panel.scrollTo({ top: Math.max(0, y - 80), behavior: "smooth" });
    }
  }, []);
  const select = useCallback(
    (clicked: AtBeat, keepMessage = false) => {
      const beat = mainBeat(clicked); // a grace note belongs to the beat after it
      const state = fromAlphaTab(beat);
      const bar = beat.voice.bar.index;
      const index = gpBeatIndex(beat);
      setSelected({ bar, beat: index, state, section: state.section, saved: state });
      if (!keepMessage) setMessage(null);
      outline(beat);
      reveal(beat);
      // then the beat exactly as the file has it, unless another beat was picked meanwhile
      void api.get<ApiBeat>(`/api/songs/${vid}/beats/${bar}/${index}`).then((b) => {
        const exact = fromApi(b);
        setSelected((cur) =>
          cur && cur.bar === bar && cur.beat === index ? { ...cur, state: exact, section: exact.section, saved: exact } : cur,
        );
      });
    },
    [outline, reveal, vid],
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
      const v = readView();
      applyView(a, v);
      setViewState(v);
      a.scoreLoaded.on((score) => {
        bars.current = score.masterBars.map((mb) => ({ start: mb.start, duration: mb.calculateDuration() }));
        const first = score.masterBars[0];
        meter.current = {
          numerator: first?.timeSignatureNumerator ?? 4,
          denominator: first?.timeSignatureDenominator ?? 4,
          tempo: score.tempo ?? 120,
        };
        clock.current = timing.data ? makeClock(timing.data, bars.current) : null;
        applyPractice();
      });
      a.renderFinished.on(() => {
        setLoaded(true);
        const r = restore.current;
        if (r) {
          restore.current = null;
          a.tickPosition = r.tick;
          const beat = r.spot && beatAt(r.spot.bar, r.spot.beat);
          if (beat) select(beat, true); // after a save: keep "Saved" in view
        }
      });
      a.playerStateChanged.on((e) => {
        if (sourceRef.current !== "tab") return;
        const on = e.state === 1;
        setPlaying(on);
        if (!on) yt.current?.pauseVideo?.();
      });
      // Tab plays: keep the (muted) video at the same moment. A jump back to the loop's start is one pass.
      let lastTick = 0;
      a.playerPositionChanged.on((e) => {
        // a jump you make yourself (isSeek) is not a pass
        if (sourceRef.current === "tab" && practiceRef.current.loop && !e.isSeek && e.currentTick + 960 < lastTick) onPass();
        lastTick = e.currentTick;
        if (sourceRef.current !== "tab" || a.playerState !== 1 || !clock.current || !yt.current?.getCurrentTime) return;
        const target = clock.current.tickToTime(e.currentTick);
        if (yt.current.getPlayerState() !== YT_PLAYING) yt.current.playVideo();
        if (Math.abs(yt.current.getCurrentTime() - target) > 0.25) yt.current.seekTo(target, true);
      });
      a.beatMouseDown.on((beat) => {
        select(beat);
        const p = yt.current;
        if (sourceRef.current === "video" && clock.current && p?.seekTo) {
          // a seek on a video that has not played yet starts it: a click only moves, it does not play
          const wasPlaying = p.getPlayerState() === YT_PLAYING;
          p.seekTo(clock.current.tickToTime(beat.absolutePlaybackStart), true);
          if (!wasPlaying) p.pauseVideo();
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
      // the tab scrolls inside its own panel: keep the bar within it, a little below its top edge
      const panel = scroller.current;
      if (!panel) return;
      const p = panel.getBoundingClientRect();
      const r = bar.getBoundingClientRect();
      if (r.top < p.top + 8 || r.bottom > p.bottom - 8) panel.scrollBy({ top: r.top - p.top - 24, behavior: "smooth" });
    };
    // Video plays: move the tab cursor along with its clock (about 15 times a second is smooth enough), loop the
    // range and click the metronome.
    let lastBeat = "";
    let lastWrap = 0;
    const follow = (now: number) => {
      raf = requestAnimationFrame(follow);
      keepInView(now);
      const p = yt.current;
      if (sourceRef.current !== "video" || !p?.getPlayerState || p.getPlayerState() !== YT_PLAYING) return;
      const c = clock.current;
      const pr = practiceRef.current;
      if (c && bars.current.length) {
        const time = p.getCurrentTime();
        const range = pr.loop ? rangeTicks(bars.current, pr.from, pr.to) : null;
        // just after the seek the player still reports the old time for a frame: count one pass per jump
        if (range && time >= c.tickToTime(range.endTick) - 0.03 && now - lastWrap > 300) {
          lastWrap = now;
          p.seekTo(c.tickToTime(range.startTick), true);
          onPass();
        }
        if (pr.metronome) {
          const b = beatOf(bars.current, c.timeToTick(time), (960 * 4) / meter.current.denominator);
          const key = `${b.bar}:${b.beat}`;
          if (key !== lastBeat) {
            if (lastBeat) click(b.beat === 0);
            lastBeat = key;
          }
        } else lastBeat = "";
      }
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
          onStateChange: (e: { data: number }) => {
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
  const cancelCount = useRef<(() => void) | null>(null);
  const playPause = () => {
    if (sourceRef.current === "tab") {
      at.current?.playPause(); // alphaTab does its own count-in and metronome
      return;
    }
    const p = yt.current;
    if (!p?.getPlayerState) return;
    if (p.getPlayerState() === YT_PLAYING || cancelCount.current) {
      cancelCount.current?.();
      cancelCount.current = null;
      p.pauseVideo();
      return;
    }
    // with a loop, start inside it
    const pr = practiceRef.current;
    const range = pr.loop && clock.current ? rangeTicks(bars.current, pr.from, pr.to) : null;
    if (range && clock.current) {
      const time = p.getCurrentTime();
      if (time < clock.current.tickToTime(range.startTick) - 0.05 || time >= clock.current.tickToTime(range.endTick)) {
        p.seekTo(clock.current.tickToTime(range.startTick), true);
        p.pauseVideo();
      }
    }
    if (pr.countIn) {
      const bpm = meter.current.tempo * nearestRate(speedRef.current) * (meter.current.denominator / 4);
      cancelCount.current = countIn(meter.current.numerator, bpm, () => {
        cancelCount.current = null;
        p.playVideo();
      });
    } else p.playVideo();
  };

  /** From the review queue: select the bar's first beat, move the video there and loop that bar. */
  const goToBar = (bar: number) => {
    const beat = beatAt(bar, 0);
    if (!beat) return;
    select(beat);
    setPractice((p) => ({ ...p, loop: true, from: bar + 1, to: bar + 1 }));
    const tick = bars.current[bar]?.start ?? 0;
    if (at.current) at.current.tickPosition = tick;
    const p = yt.current;
    if (clock.current && p?.seekTo) {
      const wasPlaying = p.getPlayerState() === YT_PLAYING;
      p.seekTo(clock.current.tickToTime(tick), true);
      if (!wasPlaying) p.pauseVideo();
    }
  };

  /** One pass through the loop: count it, and let the trainer speed up. */
  const onPass = () => {
    setPasses((n) => n + 1);
    const pr = practiceRef.current;
    if (pr.trainer) setSpeed((sp) => nextSpeed(sp, pr, sourceRef.current));
  };
  /** Loop range, count-in and metronome onto alphaTab (the tab as sound source). */
  const applyPractice = () => {
    const a = at.current;
    if (!a) return;
    const pr = practiceRef.current;
    const range = pr.loop ? rangeTicks(bars.current, pr.from, pr.to) : null;
    a.playbackRange = range;
    a.isLooping = !!range;
    a.countInVolume = pr.countIn ? 1 : 0;
    a.metronomeVolume = pr.metronome ? 1 : 0;
  };
  useEffect(applyPractice, [practice]);
  // the trainer starts at its own speed; a new loop or trainer counts passes from zero
  useEffect(() => {
    if (practice.trainer) setSpeed(practice.start);
    setPasses(0);
  }, [practice.trainer, practice.start, practice.loop, practice.from, practice.to]);
  const stop = () => {
    at.current?.stop();
    yt.current?.pauseVideo?.();
    if (clock.current) yt.current?.seekTo?.(clock.current.tickToTime(0), true);
  };
  useEffect(() => {
    speedRef.current = speed;
    if (at.current) at.current.playbackSpeed = speed;
    yt.current?.setPlaybackRate?.(nearestRate(speed));
  }, [speed]);

  // ── practice log ───────────────────────────────────────────────────────────
  // While something plays, count the seconds; report them every 30 s and when playback stops. A run from the first
  // to the last bar without a loop counts as playing the whole song at that speed.
  const session = useRef({ seconds: 0, startBar: -1, whole: false });
  const flush = useCallback(() => {
    const s = session.current;
    if (s.seconds < 1) return;
    const pr = practiceRef.current;
    void fetch("/api/practice", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      keepalive: true,
      body: JSON.stringify({
        video: vid,
        day: localDay(),
        seconds: Math.min(600, s.seconds),
        speed: speedRef.current,
        source: sourceRef.current,
        bars: pr.loop ? [Math.min(pr.from, pr.to), Math.max(pr.from, pr.to)] : null,
        whole_song: s.whole,
      }),
    }).then(() => qc.invalidateQueries({ queryKey: ["songs"] }));
    session.current = { seconds: 0, startBar: s.startBar, whole: false };
  }, [vid, qc]);
  useEffect(() => {
    if (!playing) {
      flush();
      session.current.startBar = -1;
      return;
    }
    const id = window.setInterval(() => {
      const s = session.current;
      s.seconds += 1;
      const bar = barAt(bars.current, at.current?.tickPosition ?? 0);
      if (s.startBar < 0) s.startBar = bar;
      if (!practiceRef.current.loop && s.startBar === 0 && bar === bars.current.length - 1) s.whole = true;
      if (s.seconds >= 30) flush();
    }, 1000);
    return () => window.clearInterval(id);
  }, [playing, flush]);
  useEffect(() => () => flush(), [flush]);
  // ── keyboard ───────────────────────────────────────────────────────────────
  // Space plays and pauses. With a beat selected: arrows move between beats and strings, digits type the fret,
  // letters toggle techniques (KEYS below), Enter saves, Escape closes. Cmd/Ctrl+Z undoes, with Shift redoes.
  const typed = useRef<{ digits: string; at: number }>({ digits: "", at: 0 });
  const [activeString, setActiveString] = useState(0);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      const typing = ["INPUT", "SELECT", "TEXTAREA"].includes(el?.tagName) || el?.isContentEditable;
      const mod = e.metaKey || e.ctrlKey;
      if (mod && !typing && (e.key.toLowerCase() === "z" || e.key.toLowerCase() === "y")) {
        e.preventDefault();
        void (e.key.toLowerCase() === "y" || e.shiftKey ? redo() : undo());
        return;
      }
      if (typing || mod || e.altKey) return;
      if (e.code === "Space" && el?.tagName !== "BUTTON") {
        e.preventDefault();
        playPause();
        return;
      }
      if (!selected) return;
      const s = activeString;
      const note = selected.state.notes[s];
      const patch = (p: Partial<NoteState>) =>
        setSelected(
          (cur) => cur && { ...cur, state: { ...cur.state, notes: cur.state.notes.map((n, i) => (i === s ? { ...n, ...p } : n)) } },
        );
      const key = e.key;
      let handled = true;
      if (key === "ArrowLeft" || key === "ArrowRight") void move(key === "ArrowLeft" ? -1 : 1);
      else if (key === "ArrowUp") setActiveString(Math.max(0, s - 1));
      else if (key === "ArrowDown") setActiveString(Math.min(5, s + 1));
      else if (/^[0-9]$/.test(key)) {
        // two digits typed quickly make one fret (12), as long as it stays on the neck
        const now = performance.now();
        const t2 = typed.current;
        const joined = now - t2.at < 800 && t2.digits.length === 1 ? t2.digits + key : key;
        const digits = Number(joined) <= 24 ? joined : key;
        typed.current = { digits, at: now };
        patch(note.fret === "" ? { fret: String(Number(digits)), letRing: true } : { fret: String(Number(digits)) });
      } else if (key === "x" || key === "X") patch(note.fret === "" ? { fret: "x" } : { fret: "x", letRing: false });
      else if (key === "Backspace" || key === "Delete") patch({ ...emptyNote() });
      else if (key === "Enter") void save(selected.state);
      else if (key === "Escape") {
        setSelected(null);
        setBox(null);
      } else if (key === "?") setShowKeys((v) => !v);
      else if (note.fret !== "" && KEYS[key]) {
        const k = KEYS[key];
        if (k === "bend") patch({ bend: nextBend(note.bend) });
        else if (k === "hammer") patch({ hammer: !note.hammer, slide: false });
        else if (k === "slide") patch({ slide: !note.slide, hammer: false });
        else patch({ [k]: !note[k] } as Partial<NoteState>);
      } else handled = false;
      if (handled) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ── editing ────────────────────────────────────────────────────────────────
  const dirty = !!selected && JSON.stringify(selected.state) !== JSON.stringify(selected.saved);
  const history = useQuery({
    queryKey: ["history", vid],
    queryFn: () => api.get<{ undo: number; redo: number }>(`/api/songs/${vid}/history`),
  });
  const [showKeys, setShowKeys] = useState(false);
  // Narrow screens: the video and the editor can fold away, so the tab gets the room (kept on this device).
  // A phone starts with the editor folded; wide screens always show both.
  const [videoOpen, setVideoOpen] = useState(true);
  const [editorOpen, setEditorOpen] = useState(true);
  const [practiceOpen, setPracticeOpen] = useState(false); // folded until you open it, at every width
  const [reviewOpen, setReviewOpen] = useState(false);
  const review = useQuery({ queryKey: ["review", vid], queryFn: () => api.get<ReviewItem[]>(`/api/songs/${vid}/review`) });
  const reviewList = review.data ?? [];
  const reviewLeft = reviewList.filter((r) => !r.checked).length;
  useEffect(() => {
    try {
      const v = localStorage.getItem("tabstealth.video");
      const e = localStorage.getItem("tabstealth.editor");
      if (v) setVideoOpen(v === "open");
      setPracticeOpen(localStorage.getItem("tabstealth.practice") === "open");
      setReviewOpen(localStorage.getItem("tabstealth.review") === "open");
      setEditorOpen(e ? e === "open" : window.innerWidth >= 640);
    } catch {
      /* private window: then we do not remember it */
    }
  }, []);
  const toggle = (key: "video" | "editor" | "practice" | "review", open: boolean, set: (v: boolean) => void) => {
    set(open);
    try {
      localStorage.setItem(`tabstealth.${key}`, open ? "open" : "closed");
    } catch {
      /* private window: then we do not remember it */
    }
  };

  /** Reload the tab after the file changed, keeping the cursor and selecting `spot` (default: the current beat). */
  const reloadTab = (spot: Spot | null = selected ? { bar: selected.bar, beat: selected.beat } : null) => {
    restore.current = { tick: at.current?.tickPosition ?? 0, spot };
    at.current?.load(`${tabUrl}?t=${Date.now()}`);
    void qc.invalidateQueries({ queryKey: ["songs"] });
    void qc.invalidateQueries({ queryKey: ["history", vid] });
  };

  /** Bars per line or compact: lay the sheet out again, keeping the cursor and the selected beat. */
  const setView = (v: SheetView) => {
    setViewState(v);
    saveView(v);
    const a = at.current;
    if (!a) return;
    applyView(a, v);
    restore.current = { tick: a.tickPosition ?? 0, spot: selected ? { bar: selected.bar, beat: selected.beat } : null };
    a.render();
  };
  const [viewOpen, setViewOpen] = useState(false);
  const viewBox = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!viewOpen) return;
    const away = (e: MouseEvent) => viewBox.current && !viewBox.current.contains(e.target as Node) && setViewOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setViewOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [viewOpen]);

  const save = async (state: BeatState, next?: Spot) => {
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
      reloadTab(next ?? { bar: selected.bar, beat: selected.beat });
      setMessage(t.song.saved);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : t.common.error);
    } finally {
      setSaving(false);
    }
  };

  /** The previous or next beat (across bars), grace notes skipped; a changed beat is saved on the way. */
  const move = async (delta: -1 | 1) => {
    if (!selected || !at.current?.score) return;
    const bars = at.current.score.tracks[0].staves[0].bars;
    let { bar, beat } = selected;
    beat += delta;
    const count = (b: number) => bars[b].voices[0].beats.filter((x) => x.graceType === 0).length;
    while (bar >= 0 && bar < bars.length && (beat < 0 || beat >= count(bar))) {
      bar += delta;
      if (bar < 0 || bar >= bars.length) return;
      beat = delta > 0 ? 0 : count(bar) - 1;
    }
    if (dirty) return save(selected.state, { bar, beat });
    const target = beatAt(bar, beat);
    if (target) select(target);
  };

  const step = async (dir: "undo" | "redo") => {
    try {
      await api.post(`/api/songs/${vid}/${dir}`);
      reloadTab();
      setMessage(null);
    } catch {
      /* nothing to undo or redo */
    }
  };
  const undo = () => step("undo");
  const redo = () => step("redo");

  const router = useRouter();
  const removeSong = async () => {
    if (!window.confirm(t.watch.removeConfirm(song?.title ?? vid))) return;
    await api.del(`/api/songs/${vid}`);
    await qc.invalidateQueries({ queryKey: ["songs"] });
    router.push("/library/");
  };
  const restoreOriginal = async () => {
    if (!window.confirm(t.song.restoreConfirm)) return;
    await api.post(`/api/songs/${vid}/restore`);
    reloadTab();
  };

  /** Read the video again with the current converter (the frame scan is cached, so it takes a minute at most). */
  const [reanalysing, setReanalysing] = useState<"running" | "done" | "failed" | null>(null);
  const reanalyse = async () => {
    const overwrite = !!song?.edited;
    if (overwrite && !window.confirm(t.song.reanalyseEdited)) return;
    setReanalysing("running");
    try {
      const job = await api.post<Job>(`/api/songs/${vid}/convert`, { overwrite_edits: overwrite });
      for (;;) {
        await new Promise((r) => setTimeout(r, 2000));
        const j = (await api.get<Job[]>("/api/jobs")).find((x) => x.id === job.id);
        if (!j || j.status === "failed") throw new Error(j?.log.at(-1) ?? "");
        if (j.status === "done") break;
      }
      await qc.invalidateQueries(); // timing, review queue, history: all of it may have changed
      reloadTab(null);
      setReanalysing("done");
    } catch {
      setReanalysing("failed");
    }
  };

  // In development the players are reachable from the console (window.__tabstealth), for checking the sync.
  useEffect(() => {
    if (process.env.NODE_ENV !== "production")
      (window as unknown as Record<string, unknown>).__tabstealth = { at, yt, clock, sourceRef, setPractice, practiceRef, speedRef };
  }, []);

  const crop = hands ? Math.min(Math.max(timing.data?.overlay_top ?? 0.66, 0.4), 1) : 1;

  // The song's files (download, text), reading it again and removing it: rare actions, in the "⋯" menu in the top bar.
  const download = (href: string, name?: string) => {
    const a = document.createElement("a");
    a.href = href;
    if (name) a.download = name;
    else a.target = "_blank";
    a.click();
  };
  const files = [
    { label: t.song.downloadGp5, run: () => download(tabUrl, song?.file) },
    { label: t.song.downloadText, run: () => download(`/api/songs/${vid}/text`) },
    { label: t.song.reanalyse, run: () => void reanalyse() },
    ...(song?.edited ? [{ label: t.song.restore, run: () => void restoreOriginal() }] : []),
    { label: t.watch.remove, run: () => void removeSong(), danger: true },
  ];
  // Play, stop, loop and the sound switch: the first controls in the row under the video.
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
      <Button
        size="sm"
        onClick={stop}
        disabled={!loaded}
        aria-label={t.song.stop}
        title={t.song.stop}
        icon={<StopIcon className="h-[15px] w-[15px]" />}
      />
      <button
        type="button"
        aria-pressed={practice.loop}
        aria-label={t.practice.loop}
        title={
          practice.loop ? t.practice.loopOn(Math.min(practice.from, practice.to), Math.max(practice.from, practice.to)) : t.practice.loop
        }
        onClick={() => setPractice((p) => ({ ...p, loop: !p.loop }))}
        className={`ds-btn ds-btn--sm !px-2 ${practice.loop ? "ds-btn--secondary !border-brand !text-brand" : "ds-btn--secondary"}`}
      >
        <RepeatIcon className="h-[15px] w-[15px]" />
      </button>
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

  // The song's name, its facts and its files go in the top bar, where the page title would be (app/(app)/layout.tsx
  // gives the slots); the transport sits at its right end.
  const [slots, setSlots] = useState<{ title: HTMLElement | null; actions: HTMLElement | null }>({ title: null, actions: null });
  useEffect(() => setSlots({ title: document.getElementById(TOPBAR_TITLE), actions: document.getElementById(TOPBAR_ACTIONS) }), []);
  const meta = [
    song?.artist,
    song?.tempo ? `♩ ${song.tempo}` : null,
    song?.capo ? t.library.capo(song.capo) : null,
    song?.swing ? t.library.swing : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const titleBar = (
    <div className="flex min-w-0 items-center gap-1">
      <Link href="/library/" aria-label={t.song.back} title={t.song.back} className="ds-btn ds-btn--ghost ds-btn--sm -ml-1 !px-1.5">
        <ChevronLeftIcon className="h-4 w-4" />
      </Link>
      <div className="min-w-0">
        <h1 className="ds-topbar__title truncate !leading-tight">{song?.title ?? "…"}</h1>
        {/* the chips stay together: when the line is too narrow they move under the facts as one group */}
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
          <span className="min-w-0 max-w-full truncate">{meta}</span>
          {song && <SongChips song={song} />}
        </div>
      </div>
    </div>
  );

  return (
    // Wide: the tab on the left, the video and settings in a sticky column on the right. Narrow: one column with the
    // video first; that column dissolves (`contents`) so the video can stick to the top above the tab.
    <div className="flex flex-col gap-3 lg:grid lg:grid-cols-[1fr_minmax(360px,42%)] lg:gap-4">
      {slots.title && createPortal(<div className="hidden min-w-0 sm:block">{titleBar}</div>, slots.title)}
      {slots.actions &&
        createPortal(
          <RowMenu label={t.song.more} items={files.map((f) => ({ label: f.label, onSelect: f.run, danger: f.danger }))} />,
          slots.actions,
        )}
      <div
        style={{ ["--bar-top" as string]: `${barHeight + 16}px` }}
        className="contents lg:sticky lg:top-[var(--bar-top)] lg:order-2 lg:flex lg:flex-col lg:gap-3 lg:self-start"
      >
        {/* The video. On a narrow screen it stays pinned under the top bar while you scroll the tab; it is at most about
            a third of the screen high, so the tab keeps room underneath. */}
        <div
          ref={pinned}
          style={{ top: barHeight }}
          className="sticky z-20 -mx-1 flex flex-col gap-2 bg-bg px-1 pb-2 lg:static lg:m-0 lg:gap-3 lg:p-0"
        >
          {/* on a phone the top bar only has room for the transport: the song's name sits above the video */}
          <div className="flex items-center gap-2 lg:hidden">
            {/* on a phone the top bar only has room for the transport: the song's name sits above the video */}
            <div className="min-w-0 flex-1">
              <div className="sm:hidden">{titleBar}</div>
            </div>
            <button
              type="button"
              className="ds-btn ds-btn--ghost ds-btn--sm flex-none !px-2 text-xs"
              aria-expanded={videoOpen}
              onClick={() => toggle("video", !videoOpen, setVideoOpen)}
            >
              <VideoIcon className="h-[15px] w-[15px]" />
              {videoOpen ? t.song.hideVideo : t.song.showVideo}
            </button>
          </div>
          {/* folded, the player keeps running at zero height: sound and sync carry on, the tab gets the room */}
          <div
            className={`ts-video mx-auto w-full ${videoOpen ? "" : "max-lg:!h-0 max-lg:!border-0"}`}
            // the fold (max-lg:h-0) only applies below the two-column layout; wide, the video always shows
            style={{ aspectRatio: `16 / ${9 * crop}`, maxWidth: `calc(34vh * ${16 / (9 * crop)})` }}
          >
            <div style={{ position: "absolute", inset: 0, height: `${100 / crop}%` }}>
              <div ref={ytEl} />
            </div>
          </div>
          {/* Everything for playing in one row under the video (pinned with it on a narrow screen): play, stop, loop, the
              sound, the speed, hands only, and the review queue and practice settings, whose panels open below. */}
          <div className="flex flex-wrap items-center gap-1.5 text-sm">
            {transport}
            <Select
              value={String(speed)}
              onChange={(e) => setSpeed(Number(e.target.value))}
              aria-label={t.song.speed}
              title={t.song.speed}
              className="!h-8 !w-auto"
            >
              {PERCENTS.map((s) => (
                <option key={s} value={s}>
                  {Math.round(s * 100)}%
                </option>
              ))}
            </Select>
            <button
              type="button"
              aria-pressed={hands}
              aria-label={t.song.hands}
              title={t.song.hands}
              onClick={() => setHands((v) => !v)}
              className={`ds-btn ds-btn--sm ds-btn--secondary !px-2 ${hands ? "!border-brand !bg-brand-tint !text-brand" : ""}`}
            >
              <HandIcon className="h-[15px] w-[15px]" />
            </button>
            <div className="ml-auto flex items-center gap-1.5">
              {reviewList.length > 0 && (
                <button
                  type="button"
                  aria-pressed={reviewOpen}
                  aria-label={t.review.title}
                  title={`${t.review.title}: ${reviewLeft ? t.review.left(reviewLeft) : t.review.allChecked}`}
                  onClick={() => toggle("review", !reviewOpen, setReviewOpen)}
                  className={`ds-btn ds-btn--sm ds-btn--secondary !gap-1 !px-2 ${reviewOpen ? "!border-brand !bg-brand-tint !text-brand" : ""}`}
                >
                  <CheckIcon className={`h-[15px] w-[15px] ${reviewOpen ? "" : reviewLeft ? "text-warn" : "text-pos"}`} />
                  {reviewLeft > 0 && <span className="text-xs tabular-nums">{reviewLeft}</span>}
                </button>
              )}
              <button
                type="button"
                aria-pressed={practiceOpen}
                aria-label={t.practice.title}
                title={t.practice.title}
                onClick={() => toggle("practice", !practiceOpen, setPracticeOpen)}
                className={`ds-btn ds-btn--sm ds-btn--secondary !px-2 ${practiceOpen ? "!border-brand !bg-brand-tint !text-brand" : practice.loop || practice.trainer ? "!text-brand" : ""}`}
              >
                <RepeatIcon className="h-[15px] w-[15px]" />
              </button>
            </div>
          </div>
          {reanalysing && (
            <p className={`text-xs ${reanalysing === "failed" ? "text-neg" : "text-ink-muted"}`}>{t.song.reanalysing[reanalysing]}</p>
          )}
        </div>

        {reviewOpen && <ReviewPanel vid={vid} onGo={goToBar} />}
        {practiceOpen && (
          <PracticePanel
            value={practice}
            onChange={(update) => setPractice((p) => update(p))}
            bars={bars.current.length}
            selectedBar={selected ? selected.bar + 1 : null}
            source={source}
            passes={passes}
          />
        )}

        {selected && (
          <BeatEditor
            title={t.song.editTitle(selected.bar + 1, selected.beat + 1)}
            value={selected.state}
            onChange={(update) => setSelected((cur) => (cur ? { ...cur, state: update(cur.state) } : cur))}
            onSave={() => void save(selected.state)}
            onClear={() => void save({ ...selected.state, notes: selected.state.notes.map(() => emptyNote()), strum: "" })}
            activeString={activeString}
            onActiveString={setActiveString}
            dirty={dirty}
            canUndo={(history.data?.undo ?? 0) > 0}
            canRedo={(history.data?.redo ?? 0) > 0}
            onUndo={() => void undo()}
            onRedo={() => void redo()}
            collapsed={!editorOpen}
            onToggleCollapsed={() => toggle("editor", !editorOpen, setEditorOpen)}
            showKeys={showKeys}
            onShowKeys={() => setShowKeys((v) => !v)}
            saving={saving}
            message={message}
          />
        )}
      </div>

      {/* The tab is a panel of its own that scrolls inside its rounded edges, under the top bar (and under the pinned
          video on a narrow screen), instead of being cut off square by them. */}
      <section
        ref={scroller}
        className="ts-sheet sticky overflow-y-auto overscroll-contain rounded border border-border lg:order-1"
        style={{ top: sheetTop, height: `calc(100dvh - ${sheetTop}px - 16px)`, minHeight: 320 }}
      >
        {!loaded && <p className="absolute left-4 top-4 text-sm text-ink-muted">{t.song.loadingTab}</p>}
        {/* how the sheet is laid out: a small button in its top corner, the choices in a popover under it */}
        {view && (
          <div className="sticky top-0 z-10 flex h-0 justify-end">
            <div ref={viewBox} className="relative p-2">
              <button
                type="button"
                aria-expanded={viewOpen}
                aria-label={t.song.layout}
                title={t.song.layout}
                onClick={() => setViewOpen((o) => !o)}
                className={`ds-btn ds-btn--sm ds-btn--secondary !px-2 shadow-sm ${viewOpen ? "!border-brand !text-brand" : ""}`}
              >
                <LayoutIcon className="h-[15px] w-[15px]" />
              </button>
              {viewOpen && (
                <div className="absolute right-2 top-12 flex w-60 flex-col gap-3 rounded-md border border-border bg-surface p-3 text-sm text-ink shadow-lg">
                  <div className="flex flex-col gap-1.5">
                    <span className="text-xs text-ink-muted">{t.song.barsPerLine}</span>
                    <Tabs
                      variant="segmented"
                      items={BARS_PER_ROW.map((n) => ({ id: String(n), label: n < 0 ? t.song.barsAuto : String(n) }))}
                      value={String(view.barsPerRow)}
                      onChange={(id: string) => setView({ ...view, barsPerRow: Number(id) })}
                      ariaLabel={t.song.barsPerLine}
                    />
                  </div>
                  <Switch checked={view.compact} onChange={(on) => setView({ ...view, compact: on })} label={t.song.compact} />
                </div>
              )}
            </div>
          </div>
        )}
        <div className="relative">
          <div ref={sheet} />
          {box && <div className="ts-selected" style={{ left: box.x - 3, top: box.y - 3, width: box.w + 6, height: box.h + 6 }} />}
        </div>
      </section>
    </div>
  );
}

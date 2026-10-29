// The parts of the two players that tabstealth uses. Both come as plain scripts from their own hosts (lib/scripts.ts),
// without types: alphaTab's model (score, bars, beats, notes) and API, and the YouTube iframe player.

export type AtNote = {
  string: number; // alphaTab counts from the low string: lib/beat.ts gpString turns it round
  fret: number;
  isDead: boolean;
  isTieDestination: boolean;
  isHammerPullOrigin: boolean;
  slideOutType: number;
  isLetRing: boolean;
  isPalmMute: boolean;
  isGhost: boolean;
  harmonicType: number;
  vibrato: number;
  bendPoints: { value: number }[] | null;
};

export type AtMasterBar = {
  start: number;
  calculateDuration(): number;
  section: { text: string } | null;
  timeSignatureNumerator: number;
  timeSignatureDenominator: number;
};
export type AtBar = { index: number; masterBar: AtMasterBar; voices: AtVoice[] };
export type AtVoice = { bar: AtBar; beats: AtBeat[] };
export type AtBeat = {
  index: number;
  voice: AtVoice;
  notes: AtNote[];
  graceType: number; // 0: not a grace beat
  brushType: number;
  brushDuration: number;
  text: string | null;
  absolutePlaybackStart: number;
};
export type AtScore = { tempo: number; masterBars: AtMasterBar[]; tracks: { staves: { bars: AtBar[] }[] }[] };

type Bounds = { x: number; y: number; w: number; h: number };
type AtEvent<T> = { on(handler: (value: T) => void): void };

export type AtApi = {
  score: AtScore | null;
  settings: { fillFromJson(json: object): void };
  renderer: { boundsLookup: { findBeat(beat: AtBeat): { visualBounds: Bounds } | null } | null } | null;
  tickPosition: number;
  playbackSpeed: number;
  playbackRange: { startTick: number; endTick: number } | null;
  isLooping: boolean;
  countInVolume: number;
  metronomeVolume: number;
  playerState: number; // 1: playing
  scoreLoaded: AtEvent<AtScore>;
  renderFinished: AtEvent<unknown>;
  playerStateChanged: AtEvent<{ state: number }>;
  playerPositionChanged: AtEvent<{ currentTick: number; isSeek: boolean }>;
  beatMouseDown: AtEvent<AtBeat>;
  load(url: string): void;
  render(): void;
  updateSettings(): void;
  playPause(): void;
  pause(): void;
  stop(): void;
  destroy(): void;
};

export type AlphaTab = {
  AlphaTabApi: new (element: HTMLElement, settings: object) => AtApi;
  ScrollMode: { Off: number };
};

export type YtPlayer = {
  playVideo(): void;
  pauseVideo(): void;
  seekTo(seconds: number, allowSeekAhead: boolean): void;
  getCurrentTime(): number;
  getPlayerState(): number;
  setPlaybackRate(rate: number): void;
  mute(): void;
  unMute(): void;
  destroy(): void;
};

export type YouTube = { Player: new (element: HTMLElement, options: object) => YtPlayer };

// Contract between the Python pipeline (fyt/models.py -> RenderProps) and the
// renderer. Keep both sides in sync when adding fields or scene types.

export type Format = "long" | "short";

export type Media = {
  src: string; // path relative to the job's public dir
  kind: "video" | "image";
  detail?: boolean | null; // a close-up on part of the picture (a second shot from the same painting)
};

export type DataPoint = { label: string; value: number };
export type TimelineEvent = { label: string; text: string };

export type SceneType =
  | "title"
  | "statement"
  | "stat"
  | "bars"
  | "list"
  | "quote"
  | "timeline"
  | "comparison"
  | "broll";

// The emotional journey (see fyt/models.py Mood): drives the colour grade and light.
export type Mood = "struggle" | "uncertainty" | "faith" | "realization" | "hope" | "strength";

export type Scene = {
  id: string;
  type: SceneType;
  start: number; // seconds
  end: number; // seconds
  heading?: string | null;
  text?: string | null;
  items?: string[] | null;
  value?: number | null;
  prefix?: string | null;
  suffix?: string | null;
  data?: DataPoint[] | null;
  events?: TimelineEvent[] | null;
  left?: string[] | null;
  right?: string[] | null;
  leftTitle?: string | null;
  rightTitle?: string | null;
  author?: string | null;
  media?: Media | null;
  shots?: Media[] | null; // more shots after `media`: the scene is cut into equal parts, one shot each
  mood?: Mood | null;
};

export type Word = { word: string; start: number; end: number };

export type Theme = {
  background: string;
  background2: string;
  accent: string;
  accent2: string;
  text: string;
  muted: string;
  font: string;
};

export type RenderProps = {
  format: Format;
  fps: number;
  title: string;
  duration: number; // seconds
  theme: Theme;
  voice: string | null;
  // levels: volume every `step` seconds (ducked under the voice, swelling at the key moments).
  music: { src: string; volume: number; levels?: number[]; step?: number } | null;
  scenes: Scene[];
  captions: Word[];
  showCaptions: boolean;
  showVisualizer: boolean;
  brand?: { name: string; tagline: string; seconds: number } | null;
  letterbox?: boolean;
};

export type QuoteCardProps = {
  text: string;
  reference: string;
  channel: string;
  theme: Theme;
  background: Media | null;
};

export type ThumbnailProps = {
  format: Format;
  title: string;
  kicker: string;
  theme: Theme;
  background: Media | null;
  layout?: "side" | "center"; // text on the left over a side fade (default), or centred
};

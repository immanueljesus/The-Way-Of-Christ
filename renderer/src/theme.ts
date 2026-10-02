import type { QuoteCardProps, RenderProps, Theme, ThumbnailProps } from "./types";

// Warm candlelight on deep umber: calm, cinematic, readable. Keep in sync with fyt/config.py Theme.
export const defaultTheme: Theme = {
  background: "#120d09",
  background2: "#3a2616",
  accent: "#e8b86d",
  accent2: "#7fa7c4",
  text: "#fbf6ee",
  muted: "#cdbca3",
  font: "Georgia, 'DejaVu Serif', 'Times New Roman', serif",
};

export const dims = (format: RenderProps["format"]) =>
  format === "short" ? { width: 1080, height: 1920 } : { width: 1920, height: 1080 };

// Base unit so layouts scale between 16:9 and 9:16.
export const unit = (format: RenderProps["format"]) => (format === "short" ? 1.35 : 1);

export const sampleProps: RenderProps = {
  format: "long",
  fps: 30,
  title: "When You Feel Forgotten",
  duration: 24,
  theme: defaultTheme,
  voice: null,
  music: null,
  showCaptions: true,
  showVisualizer: true,
  scenes: [
    { id: "s1", type: "title", start: 0, end: 4, heading: "When You Feel Forgotten", text: "The pit was not the end of Joseph's story" },
    { id: "s2", type: "timeline", start: 4, end: 10, heading: "Joseph's road", events: [
      { label: "The pit", text: "Betrayed by his brothers" }, { label: "Egypt", text: "Sold as a slave" },
      { label: "Prison", text: "Forgotten for two years" }, { label: "The palace", text: "Second only to Pharaoh" },
    ] },
    { id: "s3", type: "comparison", start: 10, end: 15, heading: "What Joseph saw / What God was doing", leftTitle: "What he saw", left: ["A pit", "A prison"], rightTitle: "What God was doing", right: ["Preserving a family", "Saving many lives"] },
    { id: "s4", type: "list", start: 15, end: 19, heading: "This week", items: ["Name the hurt to God", "Do today's work faithfully", "Refuse bitterness"] },
    { id: "s5", type: "quote", start: 19, end: 24, text: "You meant evil against me, but God meant it for good.", author: "Genesis 50:20" },
  ],
  captions: [],
};

export const sampleThumbnail: ThumbnailProps = {
  format: "long",
  title: "Not Forgotten",
  kicker: "WHEN YOU FEEL...",
  theme: defaultTheme,
  background: null,
};

export const sampleQuoteCard: QuoteCardProps = {
  text: "Come to me, all you who labour and are heavily burdened, and I will give you rest.",
  reference: "Matthew 11:28",
  channel: "Your Channel",
  theme: defaultTheme,
  background: null,
};

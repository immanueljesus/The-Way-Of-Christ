import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { Format, Scene, Theme, Word } from "../types";

// Group words into short phrases so only a few are on screen at once.
const chunk = (words: Word[], maxWords: number, maxGap = 0.6): Word[][] => {
  const out: Word[][] = [];
  let cur: Word[] = [];
  for (const w of words) {
    const prev = cur[cur.length - 1];
    const breakHere =
      cur.length >= maxWords || (prev && w.start - prev.end > maxGap) || (prev && /[.!?…—,]$/.test(prev.word));
    if (breakHere && cur.length) {
      out.push(cur);
      cur = [];
    }
    cur.push(w);
  }
  if (cur.length) out.push(cur);
  return out;
};

// Quiet, film-like subtitles: each phrase fades in, and words brighten softly as they are spoken.
// Hidden while a scene already shows its words on screen (Scripture, a key line, the title),
// so the viewer reads one thing at a time.
const TEXT_SCENES = new Set(["quote", "statement", "title"]);

export const Captions: React.FC<{ words: Word[]; theme: Theme; format: Format; letterbox?: boolean; scenes?: Scene[] }> = ({
  words,
  theme,
  format,
  letterbox = false,
  scenes = [],
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const t = frame / fps;
  const short = format === "short";
  const groups = React.useMemo(() => chunk(words, short ? 4 : 8), [words, short]);
  const group = groups.find((g) => t >= g[0].start - 0.1 && t <= g[g.length - 1].end + 0.4);
  if (!group) return null;
  const mid = (group[0].start + group[group.length - 1].end) / 2;
  const scene = scenes.find((s) => mid >= s.start && mid < s.end);
  if (scene && TEXT_SCENES.has(scene.type)) return null;

  const start = group[0].start - 0.1;
  const end = group[group.length - 1].end + 0.4;
  const o = Math.min(
    interpolate(t, [start, start + 0.25], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
    interpolate(t, [end - 0.25, end], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
  );
  const bar = letterbox ? Math.max(0, (height - width / 2.39) / 2) : 0;
  return (
    <div
      style={{
        position: "absolute",
        left: width * 0.1,
        right: width * 0.1,
        top: short ? height * 0.66 : undefined,
        bottom: short ? undefined : letterbox ? bar * 0.28 : height * 0.09,
        textAlign: "center",
        fontFamily: theme.font,
        fontWeight: 500,
        fontSize: short ? 66 : letterbox ? 42 : 48,
        lineHeight: 1.25,
        color: theme.text,
        opacity: o,
        textShadow: "0 3px 18px rgba(0,0,0,0.95), 0 0 3px rgba(0,0,0,0.9)",
      }}
    >
      {/* A soft pool of shadow behind the words keeps them readable over bright pictures. */}
      <div
        style={{
          position: "absolute",
          inset: short ? "-40px -60px" : "-24px -80px",
          background: "radial-gradient(ellipse at center, rgba(0,0,0,0.5) 0%, rgba(0,0,0,0.25) 45%, transparent 72%)",
          zIndex: -1,
        }}
      />
      {group.map((w, i) => {
        const said = t >= w.start - 0.05;
        return (
          <span key={i} style={{ opacity: said ? 1 : 0.55, marginRight: "0.26em", display: "inline-block" }}>
            {w.word}
          </span>
        );
      })}
    </div>
  );
};

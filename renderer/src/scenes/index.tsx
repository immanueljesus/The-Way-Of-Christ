import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { Format, Media, Mood, Scene, Theme } from "../types";
import { unit } from "../theme";

type SceneProps = { scene: Scene; theme: Theme; format: Format };

// ---------- shared helpers ----------

const useEnter = (delayFrames = 0) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: frame - delayFrames, fps, config: { damping: 16, mass: 0.7 } });
};

// Frames each scene overlaps the next: the next one dissolves in over it (see Video.tsx).
export const CROSSFADE = 24;

// A slow dissolve in (the scene before stays underneath), a slow push in, and a fade to dark
// at the very end of the video. `hook` (a Short's opening): no fade from black, the picture is
// there from the first frame and punches in, so the first second already grabs.
export const SceneFrame: React.FC<{ children: React.ReactNode; first?: boolean; last?: boolean; hook?: boolean }> = ({
  children,
  first = false,
  last = false,
  hook = false,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const fadeIn = hook
    ? 1
    : first
      ? interpolate(frame, [0, 30], [0, 1], { extrapolateRight: "clamp" })
      : interpolate(frame, [0, CROSSFADE], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = last
    ? interpolate(frame, [durationInFrames - 30, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 1;
  const punch = hook ? interpolate(frame, [0, 18], [0.14, 0], { easing: Easing.out(Easing.cubic), extrapolateRight: "clamp" }) : 0;
  const zoom = interpolate(frame, [0, durationInFrames], [1, 1.05]) + punch;
  return (
    <AbsoluteFill style={{ opacity: Math.min(fadeIn, fadeOut), transform: `scale(${zoom})` }}>{children}</AbsoluteFill>
  );
};

// Colour grade per stage of the journey: cold and dark in the struggle, warming to golden light.
const GRADE: Record<Mood, { filter: string; tint: string; tintOpacity: number; light: number; dim: number }> = {
  struggle: { filter: "saturate(0.45) brightness(0.62) contrast(1.12)", tint: "#1b2a3a", tintOpacity: 0.35, light: 0, dim: 0.5 },
  uncertainty: { filter: "saturate(0.6) brightness(0.72) contrast(1.05)", tint: "#2a3340", tintOpacity: 0.25, light: 0, dim: 0.45 },
  faith: { filter: "saturate(0.85) brightness(0.8) sepia(0.12)", tint: "#3a2616", tintOpacity: 0.18, light: 0.25, dim: 0.4 },
  realization: { filter: "saturate(1) brightness(0.9) contrast(1.05)", tint: "#e8b86d", tintOpacity: 0.08, light: 0.6, dim: 0.35 },
  hope: { filter: "saturate(1.1) brightness(0.98) sepia(0.18)", tint: "#e8b86d", tintOpacity: 0.12, light: 0.75, dim: 0.28 },
  strength: { filter: "saturate(1.15) brightness(1) contrast(1.08)", tint: "#e8b86d", tintOpacity: 0.1, light: 0.9, dim: 0.28 },
};
const NEUTRAL = { filter: "saturate(0.9) brightness(0.8)", tint: "#000000", tintOpacity: 0, light: 0, dim: 0.45 };

// Soft light breaking in from the top of the frame, slowly breathing.
const LightRays: React.FC<{ strength: number; color: string }> = ({ strength, color }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  if (strength <= 0) return null;
  const grow = interpolate(frame, [0, Math.min(90, durationInFrames)], [0.4, 1], { extrapolateRight: "clamp" });
  const drift = Math.sin(frame / 50) * 4;
  return (
    <AbsoluteFill style={{ mixBlendMode: "screen", opacity: strength * grow, pointerEvents: "none" }}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(ellipse 60% 55% at ${62 + drift}% -8%, ${color}aa 0%, ${color}33 40%, transparent 70%)`,
        }}
      />
      <AbsoluteFill
        style={{
          background: `conic-gradient(from ${170 + drift}deg at ${62 + drift}% -10%, transparent 0deg, ${color}22 8deg, transparent 16deg, ${color}18 24deg, transparent 34deg, ${color}14 44deg, transparent 56deg)`,
        }}
      />
    </AbsoluteFill>
  );
};

const Stage: React.FC<{ format: Format; children: React.ReactNode; justify?: string }> = ({
  format,
  children,
  justify = "center",
}) => (
  <AbsoluteFill
    style={{
      padding: format === "short" ? "220px 80px 560px" : "90px 160px 170px",
      display: "flex",
      flexDirection: "column",
      justifyContent: justify,
      alignItems: "center",
      textAlign: "center",
      gap: 36,
    }}
  >
    {children}
  </AbsoluteFill>
);

const Heading: React.FC<{ text?: string | null; theme: Theme; format: Format; size?: number; delay?: number }> = ({
  text,
  theme,
  format,
  size = 64,
  delay = 0,
}) => {
  const p = useEnter(delay);
  if (!text) return null;
  return (
    <div
      style={{
        fontFamily: theme.font,
        fontWeight: 800,
        fontSize: size * unit(format),
        color: theme.text,
        lineHeight: 1.1,
        opacity: p,
        transform: `translateY(${(1 - p) * 40}px)`,
      }}
    >
      {text}
    </div>
  );
};

const Sub: React.FC<{ text?: string | null; theme: Theme; format: Format; delay?: number }> = ({
  text,
  theme,
  format,
  delay = 8,
}) => {
  const p = useEnter(delay);
  if (!text) return null;
  return (
    <div
      style={{
        fontFamily: theme.font,
        fontWeight: 500,
        fontSize: 38 * unit(format),
        color: theme.muted,
        maxWidth: 1400,
        opacity: p,
        transform: `translateY(${(1 - p) * 30}px)`,
      }}
    >
      {text}
    </div>
  );
};

const formatNumber = (n: number) =>
  Math.abs(n) >= 1000 ? Math.round(n).toLocaleString("en-US") : n % 1 === 0 ? String(n) : n.toFixed(1);

// ---------- scene types ----------

// A slow, cinematic title: the words surface out of the dark, a thin line of light beneath.
const TitleScene: React.FC<SceneProps> = ({ scene, theme, format }) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [6, 50], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const spread = interpolate(frame, [6, 90], [0.4, 0.12], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const line = interpolate(frame, [30, 80], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <Stage format={format}>
      <div
        style={{
          fontFamily: theme.font,
          fontWeight: 500,
          fontSize: 96 * unit(format),
          lineHeight: 1.1,
          letterSpacing: `${spread}em`,
          textTransform: "uppercase",
          color: theme.text,
          opacity: o,
          textShadow: `0 0 50px ${theme.accent}44, 0 6px 30px rgba(0,0,0,0.8)`,
        }}
      >
        {scene.heading}
      </div>
      <div style={{ width: 360 * line * unit(format), height: 2, background: theme.accent, opacity: 0.9 }} />
      <Sub text={scene.text} theme={theme} format={format} delay={40} />
    </Stage>
  );
};

// A key line surfacing slowly, word by word, across the scene.
const StatementScene: React.FC<SceneProps> = ({ scene, theme, format }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const words = (scene.text ?? "").split(" ");
  const revealEnd = Math.max(10, durationInFrames * 0.6);
  return (
    <Stage format={format}>
      <Heading text={scene.heading} theme={theme} format={format} size={40} />
      <div
        style={{
          fontFamily: theme.font,
          fontWeight: 500,
          fontSize: (words.length > 14 ? 60 : 76) * unit(format),
          lineHeight: 1.3,
          maxWidth: 1500,
          textShadow: "0 4px 30px rgba(0,0,0,0.85)",
        }}
      >
        {words.map((w, i) => {
          const at = (i / words.length) * revealEnd;
          const o = interpolate(frame, [at, at + 18], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          const lift = interpolate(frame, [at, at + 18], [8, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          return (
            <span
              key={i}
              style={{ display: "inline-block", opacity: o, color: theme.text, marginRight: "0.25em", transform: `translateY(${lift}px)` }}
            >
              {w}
            </span>
          );
        })}
      </div>
    </Stage>
  );
};

const StatScene: React.FC<SceneProps> = ({ scene, theme, format }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const target = scene.value ?? 0;
  const progress = interpolate(frame, [5, Math.min(durationInFrames * 0.55, 60)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const pulse = spring({ frame: frame - 60, fps: 30, config: { damping: 8 } });
  return (
    <Stage format={format}>
      <Heading text={scene.heading} theme={theme} format={format} size={52} />
      <div
        style={{
          fontFamily: theme.font,
          fontWeight: 900,
          fontSize: 210 * unit(format),
          color: theme.accent,
          lineHeight: 1,
          transform: `scale(${1 + 0.05 * pulse})`,
          textShadow: `0 0 60px ${theme.accent}55`,
        }}
      >
        {scene.prefix ?? ""}
        {formatNumber(target * progress)}
        {scene.suffix ?? ""}
      </div>
      <Sub text={scene.text} theme={theme} format={format} delay={20} />
    </Stage>
  );
};

const BarsScene: React.FC<SceneProps> = ({ scene, theme, format }) => {
  const frame = useCurrentFrame();
  const data = scene.data ?? [];
  const max = Math.max(...data.map((d) => d.value), 1);
  const short = format === "short";
  const chartH = short ? 820 : 520;
  return (
    <Stage format={format}>
      <Heading text={scene.heading} theme={theme} format={format} size={56} />
      <div style={{ display: "flex", alignItems: "flex-end", gap: short ? 28 : 44, height: chartH + 90 }}>
        {data.map((d, i) => {
          const g = interpolate(frame, [8 + i * 6, 32 + i * 6], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.out(Easing.back(1.4)),
          });
          const h = Math.max(4, (d.value / max) * chartH * g);
          const top = i === data.length - 1 || d.value === max;
          return (
            <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
              <div style={{ fontFamily: theme.font, fontWeight: 800, fontSize: 34 * unit(format), color: theme.text, opacity: g }}>
                {formatNumber(d.value * Math.min(g, 1))}
              </div>
              <div
                style={{
                  width: short ? 150 : Math.min(180, 1200 / Math.max(data.length, 1)),
                  height: h,
                  borderRadius: "16px 16px 4px 4px",
                  background: top ? theme.accent : `linear-gradient(${theme.accent2}, ${theme.background2})`,
                }}
              />
              <div style={{ fontFamily: theme.font, fontWeight: 600, fontSize: 30 * unit(format), color: theme.muted }}>
                {d.label}
              </div>
            </div>
          );
        })}
      </div>
      <Sub text={scene.text} theme={theme} format={format} delay={30} />
    </Stage>
  );
};

const ListScene: React.FC<SceneProps> = ({ scene, theme, format }) => {
  const { durationInFrames } = useVideoConfig();
  const items = scene.items ?? [];
  const step = Math.min(24, (durationInFrames * 0.6) / Math.max(items.length, 1));
  return (
    <Stage format={format}>
      <Heading text={scene.heading} theme={theme} format={format} size={64} />
      <div style={{ display: "flex", flexDirection: "column", gap: 26, alignItems: "stretch", minWidth: format === "short" ? 820 : 1100 }}>
        {items.map((item, i) => (
          <ListItem key={i} i={i} delay={10 + i * step} text={item} theme={theme} format={format} />
        ))}
      </div>
    </Stage>
  );
};

const ListItem: React.FC<{ i: number; delay: number; text: string; theme: Theme; format: Format }> = ({
  i,
  delay,
  text,
  theme,
  format,
}) => {
  const p = useEnter(delay);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 28,
        padding: "22px 34px",
        borderRadius: 22,
        background: "rgba(255,255,255,0.07)",
        border: `2px solid ${theme.accent}33`,
        opacity: p,
        transform: `translateX(${(1 - p) * -120}px)`,
        textAlign: "left",
      }}
    >
      <div
        style={{
          flex: "0 0 auto",
          width: 64 * unit(format),
          height: 64 * unit(format),
          borderRadius: "50%",
          background: theme.accent,
          color: theme.background,
          fontFamily: theme.font,
          fontWeight: 900,
          fontSize: 34 * unit(format),
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {i + 1}
      </div>
      <div style={{ fontFamily: theme.font, fontWeight: 700, fontSize: 46 * unit(format), color: theme.text }}>{text}</div>
    </div>
  );
};

const QuoteScene: React.FC<SceneProps> = ({ scene, theme, format }) => {
  const p = useEnter();
  return (
    <Stage format={format}>
      <div style={{ fontFamily: "Georgia, serif", fontSize: 220 * unit(format), color: theme.accent, lineHeight: 0.6, opacity: p }}>
        “
      </div>
      <div
        style={{
          fontFamily: "Georgia, serif",
          fontStyle: "italic",
          fontSize: 64 * unit(format),
          color: theme.text,
          maxWidth: 1400,
          lineHeight: 1.25,
          opacity: p,
          transform: `scale(${0.94 + 0.06 * p})`,
        }}
      >
        {scene.text}
      </div>
      {scene.author ? <Sub text={`— ${scene.author}`} theme={theme} format={format} delay={18} /> : null}
    </Stage>
  );
};

const TimelineScene: React.FC<SceneProps> = ({ scene, theme, format }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const events = scene.events ?? [];
  const short = format === "short";
  const drawn = interpolate(frame, [5, durationInFrames * 0.7], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <Stage format={format}>
      <Heading text={scene.heading} theme={theme} format={format} size={56} />
      <div
        style={{
          position: "relative",
          display: "flex",
          flexDirection: short ? "column" : "row",
          gap: short ? 40 : 30,
          width: short ? 860 : 1600,
          justifyContent: "space-between",
        }}
      >
        <div
          style={{
            position: "absolute",
            background: theme.accent,
            borderRadius: 4,
            ...(short
              ? { left: 30, top: 0, width: 6, height: `${drawn * 100}%` }
              : { top: 30, left: 0, height: 6, width: `${drawn * 100}%` }),
          }}
        />
        {events.map((e, i) => {
          const at = (i / Math.max(events.length, 1)) * durationInFrames * 0.7;
          const p = spring({ frame: frame - at, fps: 30, config: { damping: 14 } });
          return (
            <div
              key={i}
              style={{
                flex: 1,
                display: "flex",
                flexDirection: short ? "row" : "column",
                alignItems: short ? "flex-start" : "center",
                gap: 20,
                opacity: p,
                transform: `translateY(${(1 - p) * 30}px)`,
                textAlign: short ? "left" : "center",
              }}
            >
              <div style={{ width: 66, height: 66, flex: "0 0 auto", borderRadius: "50%", background: theme.background, border: `6px solid ${theme.accent}` }} />
              <div>
                <div style={{ fontFamily: theme.font, fontWeight: 900, fontSize: 44 * unit(format), color: theme.accent }}>{e.label}</div>
                <div style={{ fontFamily: theme.font, fontWeight: 500, fontSize: 30 * unit(format), color: theme.text }}>{e.text}</div>
              </div>
            </div>
          );
        })}
      </div>
    </Stage>
  );
};

const ComparisonScene: React.FC<SceneProps> = ({ scene, theme, format }) => {
  const short = format === "short";
  const column = (title: string | null | undefined, items: string[], color: string, delay: number) => (
    <ComparisonColumn title={title} items={items} color={color} delay={delay} theme={theme} format={format} />
  );
  return (
    <Stage format={format}>
      <Heading text={scene.heading} theme={theme} format={format} size={56} />
      <div style={{ display: "flex", flexDirection: short ? "column" : "row", gap: 40, width: short ? 900 : 1500 }}>
        {column(scene.leftTitle, scene.left ?? [], theme.accent2, 6)}
        {column(scene.rightTitle, scene.right ?? [], theme.accent, 16)}
      </div>
    </Stage>
  );
};

const ComparisonColumn: React.FC<{
  title?: string | null;
  items: string[];
  color: string;
  delay: number;
  theme: Theme;
  format: Format;
}> = ({ title, items, color, delay, theme, format }) => {
  const p = useEnter(delay);
  return (
    <div
      style={{
        flex: 1,
        padding: 40,
        borderRadius: 28,
        background: "rgba(255,255,255,0.06)",
        borderTop: `10px solid ${color}`,
        opacity: p,
        transform: `translateY(${(1 - p) * 60}px)`,
        textAlign: "left",
      }}
    >
      <div style={{ fontFamily: theme.font, fontWeight: 900, fontSize: 48 * unit(format), color, marginBottom: 18 }}>{title}</div>
      {items.map((it, i) => (
        <div key={i} style={{ fontFamily: theme.font, fontWeight: 600, fontSize: 36 * unit(format), color: theme.text, margin: "12px 0" }}>
          • {it}
        </div>
      ))}
    </div>
  );
};

// Frames a shot dissolves in over the one before it inside a scene: a quick cut, softer than a hard one.
const CUT = 8;

// One picture with a slow Ken Burns move along `axis` (dir flips the drift). A detail shot is a
// close-up on the upper part of the picture, where the faces in a painting usually are.
const Shot: React.FC<{ media: Media; filter: string; axis: "X" | "Y"; dir: number; fadeIn?: boolean }> = ({
  media,
  filter,
  axis,
  dir,
  fadeIn = false,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const o = fadeIn ? interpolate(frame, [0, CUT], [0, 1], { extrapolateRight: "clamp" }) : 1;
  const zoom = media.detail
    ? interpolate(frame, [0, durationInFrames], [1.5, 1.62])
    : interpolate(frame, [0, durationInFrames], [1.04, 1.14]);
  const pan = interpolate(frame, [0, durationInFrames], [-1.5 * dir, 1.5 * dir]);
  const style = { width: "100%", height: "100%", objectFit: "cover" as const };
  return (
    <AbsoluteFill
      style={{
        opacity: o,
        transform: `scale(${zoom}) translate${axis}(${pan}%)`,
        transformOrigin: media.detail ? "50% 32%" : "50% 50%",
        filter,
      }}
    >
      {media.kind === "video" ? <OffthreadVideo src={staticFile(media.src)} muted style={style} /> : <Img src={staticFile(media.src)} style={style} />}
    </AbsoluteFill>
  );
};

// The scene's picture: its one shot, or its shots cut in turn, each an equal part of the scene
// (Shorts change picture every few seconds, see fyt/pipeline.scene_shots), drifting in turn one way and the other.
const Shots: React.FC<{ scene: Scene; filter: string; axis: "X" | "Y"; dir: number }> = ({ scene, filter, axis, dir }) => {
  const { fps, durationInFrames } = useVideoConfig();
  const all = [scene.media, ...(scene.shots ?? [])].filter((m): m is Media => !!m);
  if (all.length <= 1) return all.length ? <Shot media={all[0]} filter={filter} axis={axis} dir={dir} /> : null;
  const part = Math.max(CUT + 1, Math.round(((scene.end - scene.start) * fps) / all.length));
  return (
    <AbsoluteFill>
      {all.map((m, k) => {
        const from = k * part;
        const len = k === all.length - 1 ? durationInFrames - from : part + CUT;
        return (
          <Sequence key={k} from={from} durationInFrames={Math.max(1, len)} name={`shot ${k + 1}`}>
            <Shot media={m} filter={filter} axis={axis} dir={k % 2 ? -dir : dir} fadeIn={k > 0} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

// Stock footage / image with a slow Ken Burns move and a lower-third label. The opening scene of a
// Short shows its heading as the hook: big and upright from the first frame.
const BrollScene: React.FC<SceneProps> = ({ scene, theme, format }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const hook = format === "short" && scene.start === 0;
  const o = hook ? 1 : interpolate(frame, [20, 60], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const pop = hook ? spring({ frame, fps, config: { damping: 14, mass: 0.6 } }) : 1;
  const label = scene.heading;
  const grade = scene.mood ? GRADE[scene.mood] : NEUTRAL;
  return (
    <AbsoluteFill>
      <Shots scene={scene} filter={grade.filter} axis="X" dir={1} />
      <AbsoluteFill style={{ background: grade.tint, opacity: grade.tintOpacity, mixBlendMode: "soft-light" }} />
      <LightRays strength={grade.light} color={theme.accent} />
      <AbsoluteFill
        style={{ background: `radial-gradient(ellipse at center, transparent 45%, ${theme.background}e6 100%), linear-gradient(transparent 55%, ${theme.background}b0)` }}
      />
      {label ? (
        <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: format === "short" ? "0 80px" : "0 200px" }}>
          <div
            style={{
              fontFamily: theme.font,
              fontStyle: hook ? "normal" : "italic",
              fontWeight: hook ? 800 : 500,
              fontSize: (hook ? 84 : 64) * unit(format),
              lineHeight: hook ? 1.15 : 1.3,
              textAlign: "center",
              color: theme.text,
              opacity: o,
              transform: `scale(${1.25 - 0.25 * pop})`,
              textShadow: "0 4px 30px rgba(0,0,0,0.9)",
            }}
          >
            {label}
          </div>
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};

const registry: Record<Scene["type"], React.FC<SceneProps>> = {
  title: TitleScene,
  statement: StatementScene,
  stat: StatScene,
  bars: BarsScene,
  list: ListScene,
  quote: QuoteScene,
  timeline: TimelineScene,
  comparison: ComparisonScene,
  broll: BrollScene,
};

// A photo or clip behind a template scene: slow Ken Burns move, darkened so text stays readable.
const Backdrop: React.FC<{ scene: Scene; theme: Theme; mood?: Mood | null }> = ({ scene, theme, mood }) => {
  const grade = mood ? GRADE[mood] : NEUTRAL;
  return (
    <AbsoluteFill>
      <Shots scene={scene} filter={grade.filter} axis="Y" dir={-1} />
      <AbsoluteFill style={{ background: grade.tint, opacity: grade.tintOpacity, mixBlendMode: "soft-light" }} />
      <LightRays strength={grade.light * 0.8} color={theme.accent} />
      {/* Darker than a picture alone so the words on top stay readable, but the image still shows. */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(ellipse at center, ${theme.background}${Math.round(grade.dim * 255).toString(16).padStart(2, "0")} 0%, ${theme.background}ee 100%)`,
        }}
      />
    </AbsoluteFill>
  );
};

export const SceneView: React.FC<SceneProps> = (props) => {
  // Fall back to a kinetic statement for broll without media or unknown types.
  const type = props.scene.type === "broll" && !props.scene.media ? "statement" : props.scene.type;
  const Component = registry[type] ?? StatementScene;
  const scene = type === "statement" && !props.scene.text ? { ...props.scene, text: props.scene.heading } : props.scene;
  const media = props.scene.media;
  if (media && type !== "broll") {
    return (
      <AbsoluteFill>
        <Backdrop scene={props.scene} theme={props.theme} mood={props.scene.mood} />
        <Component {...props} scene={scene} />
      </AbsoluteFill>
    );
  }
  return <Component {...props} scene={scene} />;
};

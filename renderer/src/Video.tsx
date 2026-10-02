import React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Background } from "./components/Background";
import { Captions } from "./components/Captions";
import { Visualizer, energyOf, useVoiceSpectrum } from "./components/Visualizer";
import { CROSSFADE, SceneFrame, SceneView } from "./scenes";
import type { RenderProps, Theme, Word } from "./types";

const ReactiveLayer: React.FC<{ props: RenderProps; voice: string }> = ({ props, voice }) => {
  const spectrum = useVoiceSpectrum(voice);
  return (
    <>
      <Background theme={props.theme} energy={energyOf(spectrum)} />
      {props.showVisualizer && spectrum ? <Visualizer spectrum={spectrum} theme={props.theme} /> : null}
    </>
  );
};

// Music volume. With `levels` (computed by the pipeline from the scenes' moods and the voice) the
// music follows the emotional journey; otherwise it simply ducks while someone is speaking.
const musicVolume = (music: NonNullable<RenderProps["music"]>, words: Word[], fps: number, total: number) => {
  const levels = music.levels ?? [];
  const step = music.step ?? 0.25;
  if (levels.length) {
    return (f: number) => {
      const x = f / fps / step;
      const i = Math.min(levels.length - 1, Math.floor(x));
      const j = Math.min(levels.length - 1, i + 1);
      return levels[i] + (levels[j] - levels[i]) * (x - i);
    };
  }
  return (f: number) => {
    const t = f / fps;
    const speaking = words.some((w) => t >= w.start - 0.3 && t <= w.end + 0.3);
    const fade = interpolate(f, [0, fps, total - fps * 2, total], [0, 1, 1, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    return (speaking || words.length === 0 ? music.volume : music.volume * 2.2) * fade;
  };
};

// Cinematic 2.39:1 bars on 16:9 video.
const Letterbox: React.FC = () => {
  const { width, height } = useVideoConfig();
  const bar = Math.max(0, (height - width / 2.39) / 2);
  return (
    <>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: bar, background: "#000" }} />
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: bar, background: "#000" }} />
    </>
  );
};

// The channel's name and a closing line, over the last seconds of the video.
const ClosingCard: React.FC<{ name: string; tagline: string; seconds: number; theme: Theme; short: boolean }> = ({
  name,
  tagline,
  seconds,
  theme,
  short,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const total = seconds * fps;
  const o = interpolate(frame, [0, fps * 1.2], [0, 1], { extrapolateRight: "clamp" });
  const line = interpolate(frame, [fps * 0.3, fps * 1.8], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const tag = interpolate(frame, [fps * 1.0, fps * 2.2], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const out = interpolate(frame, [total - fps * 0.6, total], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ opacity: out }}>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse at center, ${theme.background}99 0%, ${theme.background}f2 75%)`, opacity: o }} />
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", gap: short ? 36 : 28, textAlign: "center" }}>
        <div
          style={{
            fontFamily: theme.font,
            fontSize: short ? 78 : 64,
            letterSpacing: short ? 10 : 14,
            color: theme.text,
            opacity: o,
            textShadow: `0 0 40px ${theme.accent}55`,
          }}
        >
          {name.toUpperCase()}
        </div>
        <div style={{ width: (short ? 360 : 420) * line, height: 2, background: theme.accent }} />
        {tagline ? (
          <div style={{ fontFamily: theme.font, fontStyle: "italic", fontSize: short ? 52 : 40, color: theme.muted, opacity: tag }}>
            {tagline}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const Video: React.FC<RenderProps> = (props) => {
  const { fps, durationInFrames } = useVideoConfig();
  const n = props.scenes.length;
  return (
    <AbsoluteFill style={{ backgroundColor: props.theme.background }}>
      {props.voice ? <ReactiveLayer props={props} voice={props.voice} /> : <Background theme={props.theme} />}

      {props.scenes.map((scene, i) => {
        const from = Math.round(scene.start * fps);
        // Each scene runs on under the next one, which dissolves in over it: a true crossfade.
        const overlap = i < n - 1 ? CROSSFADE : 0;
        const len = Math.max(1, Math.round(scene.end * fps) - from + overlap);
        return (
          <Sequence key={scene.id} from={from} durationInFrames={len} name={`${scene.type}:${scene.id}`}>
            <SceneFrame first={i === 0} last={i === n - 1}>
              <SceneView scene={scene} theme={props.theme} format={props.format} />
            </SceneFrame>
          </Sequence>
        );
      })}

      {props.letterbox ? <Letterbox /> : null}

      {props.showCaptions && props.captions.length ? (
        <Captions words={props.captions} theme={props.theme} format={props.format} letterbox={!!props.letterbox} scenes={props.scenes} />
      ) : null}

      {props.brand ? (
        <Sequence from={Math.max(0, durationInFrames - Math.round(props.brand.seconds * fps))} name="closing card">
          <ClosingCard {...props.brand} theme={props.theme} short={props.format === "short"} />
        </Sequence>
      ) : null}

      {props.voice ? <Audio src={staticFile(props.voice)} /> : null}
      {props.music ? (
        <Audio src={staticFile(props.music.src)} loop volume={musicVolume(props.music, props.captions, fps, durationInFrames)} />
      ) : null}
    </AbsoluteFill>
  );
};

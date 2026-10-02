import React from "react";
import { staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { useAudioData, visualizeAudio } from "@remotion/media-utils";
import type { Theme } from "../types";

// visualizeAudio needs a power-of-two sample count; we draw the lower bins,
// where speech energy lives, mirrored around the centre.
const SAMPLES = 64;
const BINS = 24;

// Reads the voice track and exposes a per-frame spectrum. Rendered only when
// a voice file exists, because useAudioData needs a real source.
export const useVoiceSpectrum = (src: string): number[] | null => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const audioData = useAudioData(staticFile(src));
  if (!audioData) return null;
  return visualizeAudio({ fps, frame, audioData, numberOfSamples: SAMPLES, optimizeFor: "speed" });
};

export const energyOf = (spectrum: number[] | null) =>
  spectrum ? Math.min(1, (spectrum.slice(0, 12).reduce((a, b) => a + Math.sqrt(b), 0) / 12) * 2.5) : 0;

export const Visualizer: React.FC<{ spectrum: number[]; theme: Theme }> = ({ spectrum, theme }) => {
  const { width, height } = useVideoConfig();
  const barW = (width * 0.5) / (BINS * 2);
  const half = spectrum.slice(0, BINS);
  const bars = [...half.slice().reverse(), ...half];
  return (
    <div
      style={{
        position: "absolute",
        bottom: height * 0.035,
        left: width * 0.25,
        width: width * 0.5,
        height: height * 0.06,
        display: "flex",
        alignItems: "flex-end",
        gap: barW * 0.35,
        opacity: 0.7,
      }}
    >
      {bars.map((v, i) => (
        <div
          key={i}
          style={{
            flex: 1,
            height: `${Math.min(100, 8 + Math.sqrt(v) * 220)}%`,
            borderRadius: barW,
            background: `linear-gradient(${theme.accent}, ${theme.accent2})`,
          }}
        />
      ))}
    </div>
  );
};

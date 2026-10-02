import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { Theme } from "../types";

// Slow-drifting gradient blobs; `energy` (0..1) from the audio makes them pulse.
export const Background: React.FC<{ theme: Theme; energy?: number }> = ({ theme, energy = 0 }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const t = frame / 30;
  const blobs = [
    { color: theme.background2, x: 0.25, y: 0.3, r: 0.55, speed: 0.13 },
    { color: theme.accent2, x: 0.75, y: 0.7, r: 0.35, speed: 0.09 },
    { color: theme.accent, x: 0.6, y: 0.2, r: 0.22, speed: 0.17 },
  ];
  const size = Math.max(width, height);
  return (
    <AbsoluteFill style={{ backgroundColor: theme.background, overflow: "hidden" }}>
      {blobs.map((b, i) => {
        const cx = (b.x + 0.08 * Math.sin(t * b.speed * 6 + i)) * width;
        const cy = (b.y + 0.08 * Math.cos(t * b.speed * 5 + i * 2)) * height;
        const r = b.r * size * 1.5 * (1 + 0.12 * energy); // gradient fades out, so draw it larger
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: cx - r / 2,
              top: cy - r / 2,
              width: r,
              height: r,
              // A radial gradient looks like a blurred circle but costs far less to
              // render than a CSS blur filter, which dominated render time on CPU runners.
              background: `radial-gradient(circle, ${b.color} 0%, ${b.color}00 70%)`,
              opacity: i === 0 ? 0.55 : 0.18 + 0.1 * energy,
            }}
          />
        );
      })}
      <AbsoluteFill
        style={{
          backgroundImage: `radial-gradient(transparent 55%, ${theme.background} 100%)`,
          opacity: interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" }),
        }}
      />
    </AbsoluteFill>
  );
};

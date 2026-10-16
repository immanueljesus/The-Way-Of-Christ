import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { Background } from "./components/Background";
import type { ThumbnailProps } from "./types";

// Big, high-contrast text over an optional image: readable at phone size.
// layout "center" (a variant for YouTube's thumbnail Test & compare) centres the text over a soft vignette.
export const Thumbnail: React.FC<ThumbnailProps> = ({ title, kicker, theme, background, format, layout }) => {
  const short = format === "short";
  const center = layout === "center" && !short;
  return (
    <AbsoluteFill>
      <Background theme={theme} energy={0.6} />
      {background ? (
        <AbsoluteFill>
          <Img src={staticFile(background.src)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          <AbsoluteFill
            style={{
              background: short
                ? `linear-gradient(transparent 30%, ${theme.background}f0 75%)`
                : center
                  ? `radial-gradient(ellipse at center, ${theme.background}cc 0%, ${theme.background}88 55%, ${theme.background}e6 100%)`
                  : `linear-gradient(90deg, ${theme.background}f5 0%, ${theme.background}bb 55%, transparent 100%)`,
            }}
          />
        </AbsoluteFill>
      ) : null}
      <AbsoluteFill
        style={{
          padding: short ? "0 70px 260px" : "0 90px",
          justifyContent: short ? "flex-end" : "center",
          alignItems: center ? "center" : undefined,
          textAlign: center ? "center" : undefined,
          gap: 26,
          maxWidth: short || center ? undefined : 1250,
        }}
      >
        <div
          style={{
            alignSelf: center ? "center" : "flex-start",
            padding: "12px 26px",
            borderRadius: 12,
            background: theme.accent,
            color: theme.background,
            fontFamily: theme.font,
            fontWeight: 900,
            fontSize: short ? 56 : 48,
            letterSpacing: 2,
          }}
        >
          {kicker}
        </div>
        <div
          style={{
            fontFamily: theme.font,
            fontWeight: 900,
            fontSize: short ? 124 : center ? 128 : 118,
            lineHeight: 1.0,
            color: theme.text,
            textTransform: "uppercase",
            textShadow: "0 8px 30px rgba(0,0,0,0.8)",
            WebkitTextStroke: "2px rgba(0,0,0,0.35)",
          }}
        >
          {title}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

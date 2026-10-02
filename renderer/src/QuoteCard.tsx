import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { Background } from "./components/Background";
import type { QuoteCardProps } from "./types";

// Square card for the Community tab: Scripture (or a line from the video) over the video's artwork.
export const QuoteCard: React.FC<QuoteCardProps> = ({ text, reference, channel, theme, background }) => {
  const long = text.length > 120;
  return (
    <AbsoluteFill>
      <Background theme={theme} energy={0.3} />
      {background ? (
        <AbsoluteFill>
          <Img src={staticFile(background.src)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          <AbsoluteFill style={{ background: `${theme.background}d0` }} />
        </AbsoluteFill>
      ) : null}
      <AbsoluteFill style={{ padding: "120px 110px", justifyContent: "center", alignItems: "center", textAlign: "center", gap: 40 }}>
        <div style={{ fontFamily: "Georgia, 'DejaVu Serif', serif", fontSize: 200, lineHeight: 0.5, color: theme.accent }}>“</div>
        <div
          style={{
            fontFamily: "Georgia, 'DejaVu Serif', serif",
            fontStyle: "italic",
            fontSize: long ? 56 : 70,
            lineHeight: 1.3,
            color: theme.text,
            textShadow: "0 4px 24px rgba(0,0,0,0.6)",
          }}
        >
          {text}
        </div>
        {reference ? (
          <div style={{ fontFamily: theme.font, fontWeight: 700, fontSize: 40, letterSpacing: 3, color: theme.accent }}>
            {reference.toUpperCase()}
          </div>
        ) : null}
      </AbsoluteFill>
      {channel ? (
        <div
          style={{
            position: "absolute",
            bottom: 56,
            width: "100%",
            textAlign: "center",
            fontFamily: theme.font,
            fontSize: 28,
            letterSpacing: 4,
            color: theme.muted,
          }}
        >
          {channel.toUpperCase()}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

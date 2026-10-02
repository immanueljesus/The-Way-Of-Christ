import React from "react";
import { Composition, Still } from "remotion";
import { QuoteCard } from "./QuoteCard";
import { Thumbnail } from "./Thumbnail";
import { Video } from "./Video";
import { dims, sampleProps, sampleQuoteCard, sampleThumbnail } from "./theme";
import type { RenderProps, ThumbnailProps } from "./types";

export const Root: React.FC = () => (
  <>
    <Composition
      id="Video"
      component={Video}
      fps={30}
      width={1920}
      height={1080}
      durationInFrames={30}
      defaultProps={sampleProps}
      calculateMetadata={({ props }: { props: RenderProps }) => ({
        fps: props.fps,
        durationInFrames: Math.max(1, Math.ceil(props.duration * props.fps)),
        ...dims(props.format),
      })}
    />
    <Still
      id="Thumbnail"
      component={Thumbnail}
      width={1280}
      height={720}
      defaultProps={sampleThumbnail}
      calculateMetadata={({ props }: { props: ThumbnailProps }) =>
        props.format === "short" ? { width: 1080, height: 1920 } : { width: 1280, height: 720 }
      }
    />
    <Still id="QuoteCard" component={QuoteCard} width={1080} height={1080} defaultProps={sampleQuoteCard} />
  </>
);

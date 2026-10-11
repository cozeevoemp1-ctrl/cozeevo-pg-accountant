import React from "react";
import { Video } from "@remotion/media";
import { staticFile } from "remotion";

// Machined phone: outer shell + inner screen (concentric radii). Screen plays a recorded clip.
export const Phone: React.FC<{
  src: string;
  width: number;
  aspect: number; // clip height / width
  trimBefore?: number; // frames into the clip
  shell?: string;
  style?: React.CSSProperties;
}> = ({ src, width, aspect, trimBefore = 0, shell = "#0E0E12", style }) => {
  const pad = Math.round(width * 0.035);
  const r = Math.round(width * 0.15);
  return (
    <div
      style={{
        width: width + pad * 2,
        padding: pad,
        borderRadius: r,
        background: shell,
        boxShadow: "0 0 0 1.5px rgba(255,255,255,0.08) inset, 0 40px 80px -20px rgba(0,0,0,0.35), 0 12px 24px -8px rgba(0,0,0,0.25)",
        ...style,
      }}
    >
      <div style={{ width, height: width * aspect, borderRadius: r - pad, overflow: "hidden", background: "#fff" }}>
        <Video src={staticFile(src)} trimBefore={trimBefore} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
    </div>
  );
};

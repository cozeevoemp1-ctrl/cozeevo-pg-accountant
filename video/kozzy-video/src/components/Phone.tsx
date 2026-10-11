import React from "react";

// Machined phone: outer shell + inner screen (concentric radii). Screen content is passed as children.
export const Phone: React.FC<{
  width: number;
  aspect: number; // screen height / width
  shell?: string;
  style?: React.CSSProperties;
  children: React.ReactNode;
}> = ({ width, aspect, shell = "#1A1A22", style, children }) => {
  const pad = Math.round(width * 0.035);
  const r = Math.round(width * 0.15);
  return (
    <div
      style={{
        width: width + pad * 2,
        padding: pad,
        borderRadius: r,
        background: shell,
        boxShadow: "inset 0 0 0 1.5px rgba(255,255,255,0.10), 0 40px 90px -20px rgba(0,0,0,0.6)",
        ...style,
      }}
    >
      <div style={{ position: "relative", width, height: width * aspect, borderRadius: r - pad, overflow: "hidden", background: "#fff" }}>
        {children}
      </div>
    </div>
  );
};

export const fill: React.CSSProperties = { width: "100%", height: "100%", objectFit: "cover" };

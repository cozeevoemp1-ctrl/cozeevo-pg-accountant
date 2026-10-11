import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { FONTS } from "../fonts";
import { Phone } from "../components/Phone";

export type Look = "signal" | "midnight" | "paper";
export type Shot = "hook" | "demo";

const PINK = "#EF1F9C";
const BLUE = "#00AEED";
const WA = { src: "wa_phone.mp4", aspect: 1688 / 780 };
const ease = Easing.bezier(0.16, 1, 0.3, 1);
const rise = (f: number, at: number) => ({
  opacity: interpolate(f, [at, at + 14], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease }),
  translate: interpolate(f, [at, at + 14], ["0px 40px", "0px 0px"], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease }),
});

const Grain: React.FC<{ opacity: number }> = ({ opacity }) => (
  <AbsoluteFill style={{ opacity, mixBlendMode: "multiply", pointerEvents: "none" }}>
    <svg width="100%" height="100%">
      <filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch" /></filter>
      <rect width="100%" height="100%" filter="url(#n)" />
    </svg>
  </AbsoluteFill>
);

const Eyebrow: React.FC<{ children: React.ReactNode; color: string; border: string }> = ({ children, color, border }) => (
  <div style={{ display: "inline-block", fontFamily: FONTS.ui, fontSize: 22, fontWeight: 600, letterSpacing: "0.22em",
    textTransform: "uppercase", color, border: `1.5px solid ${border}`, borderRadius: 999, padding: "10px 22px" }}>{children}</div>
);

// ---------------- SIGNAL: bold flat color fields, giant condensed type, geometric shapes ----------------
const SignalHook: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: PINK, overflow: "hidden" }}>
      <div style={{ position: "absolute", right: -140, top: -120, width: 620, height: 620, background: BLUE, rotate: "45deg", borderRadius: 40 }} />
      <div style={{ position: "absolute", right: 300, bottom: 110, width: 120, height: 120, border: "10px solid #fff", rotate: "45deg" }} />
      <div style={{ position: "absolute", left: 140, top: 150 }}>
        <div style={rise(f, 0)}><Eyebrow color="#fff" border="rgba(255,255,255,0.6)">Every day at the front desk</Eyebrow></div>
        <div style={{ ...rise(f, 6), fontFamily: FONTS.display, fontWeight: 900, fontVariationSettings: "'wdth' 75, 'opsz' 40", fontSize: 300, lineHeight: 0.86,
          color: "#fff", letterSpacing: "-0.02em", marginTop: 40, textTransform: "uppercase" }}>Who's<br />paid?</div>
        <div style={{ ...rise(f, 14), fontFamily: FONTS.display, fontWeight: 700, fontVariationSettings: "'wdth' 85", fontSize: 56, color: "#1A0612",
          marginTop: 36, textTransform: "uppercase", letterSpacing: "0.01em" }}>Which beds are free? · Who's moving out?</div>
      </div>
    </AbsoluteFill>
  );
};
const SignalDemo: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: BLUE, overflow: "hidden" }}>
      <div style={{ position: "absolute", left: -200, bottom: -260, width: 760, height: 760, borderRadius: "50%", background: PINK }} />
      <div style={{ position: "absolute", left: 140, top: 250, width: 900 }}>
        <div style={rise(f, 0)}><Eyebrow color="#fff" border="rgba(255,255,255,0.6)">Real bot · test data</Eyebrow></div>
        <div style={{ ...rise(f, 6), fontFamily: FONTS.display, fontWeight: 900, fontVariationSettings: "'wdth' 75, 'opsz' 40", fontSize: 150, lineHeight: 0.9,
          color: "#fff", marginTop: 36, textTransform: "uppercase" }}>Staff just<br />message it.</div>
        <div style={{ ...rise(f, 14), fontFamily: FONTS.ui, fontWeight: 500, fontSize: 44, color: "#04293A", marginTop: 34 }}>
          A check-in, done in a WhatsApp chat.</div>
      </div>
      <Phone src={WA.src} aspect={WA.aspect} width={380} trimBefore={9.6 * 30}
        style={{ position: "absolute", right: 200, top: 90, rotate: "5deg" }} />
    </AbsoluteFill>
  );
};

// ---------------- MIDNIGHT: near-black, soft brand glows, crisp Geist, product-launch ----------------
const Glow: React.FC<{ x: number; y: number; size: number; color: string; o: number }> = ({ x, y, size, color, o }) => (
  <div style={{ position: "absolute", left: x - size / 2, top: y - size / 2, width: size, height: size, borderRadius: "50%",
    background: `radial-gradient(circle, ${color} 0%, transparent 65%)`, opacity: o }} />
);
const MidnightHook: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: "#07070B", overflow: "hidden" }}>
      <Glow x={1500} y={260} size={1100} color={PINK} o={0.35} />
      <Glow x={300} y={980} size={900} color={BLUE} o={0.25} />
      <div style={{ position: "absolute", left: 160, top: 200 }}>
        <div style={rise(f, 0)}><Eyebrow color="rgba(255,255,255,0.7)" border="rgba(255,255,255,0.18)">Running a co-living property</Eyebrow></div>
        <div style={{ ...rise(f, 6), fontFamily: FONTS.ui, fontWeight: 700, fontSize: 200, lineHeight: 0.95, color: "#fff",
          letterSpacing: "-0.045em", marginTop: 44 }}>Who's paid?</div>
        {["Which beds are free?", "Who's moving out?"].map((q, i) => (
          <div key={q} style={{ ...rise(f, 12 + i * 5), fontFamily: FONTS.ui, fontWeight: 600, fontSize: 96, lineHeight: 1.05,
            color: i === 0 ? "rgba(255,255,255,0.42)" : "rgba(255,255,255,0.2)", letterSpacing: "-0.04em" }}>{q}</div>
        ))}
      </div>
    </AbsoluteFill>
  );
};
const MidnightDemo: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: "#07070B", overflow: "hidden" }}>
      <Glow x={1330} y={540} size={1000} color={PINK} o={0.45} />
      <div style={{ position: "absolute", left: 160, top: 300, width: 760 }}>
        <div style={rise(f, 0)}><Eyebrow color="rgba(255,255,255,0.7)" border="rgba(255,255,255,0.18)">Real bot · test data</Eyebrow></div>
        <div style={{ ...rise(f, 6), fontFamily: FONTS.ui, fontWeight: 700, fontSize: 120, lineHeight: 1, color: "#fff",
          letterSpacing: "-0.045em", marginTop: 40 }}>Staff just <span style={{ color: PINK }}>message it.</span></div>
        <div style={{ ...rise(f, 14), fontFamily: FONTS.ui, fontWeight: 400, fontSize: 42, color: "rgba(255,255,255,0.6)", marginTop: 30 }}>
          A check-in, done in a WhatsApp chat.</div>
      </div>
      <Phone src={WA.src} aspect={WA.aspect} width={400} trimBefore={9.6 * 30} shell="#1A1A22"
        style={{ position: "absolute", right: 210, top: 50 }} />
    </AbsoluteFill>
  );
};

// ---------------- PAPER: warm editorial, serif headlines, ink + one pink accent ----------------
const PaperHook: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: "#F3EEE5", overflow: "hidden" }}>
      <Grain opacity={0.08} />
      <div style={{ position: "absolute", left: 160, top: 170 }}>
        <div style={{ ...rise(f, 0), fontFamily: FONTS.ui, fontSize: 24, fontWeight: 500, letterSpacing: "0.24em", textTransform: "uppercase", color: "#7A7266" }}>
          The front desk, every day</div>
        <div style={{ ...rise(f, 6), fontFamily: FONTS.serif, fontSize: 280, lineHeight: 0.9, color: "#17140F", marginTop: 30, letterSpacing: "-0.02em" }}>
          Who’s <i style={{ color: PINK }}>paid?</i></div>
        <div style={{ ...rise(f, 14), display: "flex", gap: 48, marginTop: 56, fontFamily: FONTS.serif, fontSize: 78, color: "#17140F" }}>
          <span>Which beds are free?</span><span style={{ color: "#A39A8C" }}>Who’s leaving?</span></div>
      </div>
      <div style={{ position: "absolute", left: 160, right: 160, bottom: 120, height: 2, background: "#17140F", opacity: 0.85 }} />
    </AbsoluteFill>
  );
};
const PaperDemo: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: "#F3EEE5", overflow: "hidden" }}>
      <Grain opacity={0.08} />
      <div style={{ position: "absolute", right: 0, top: 0, bottom: 0, width: 760, background: "#E9E1D3" }} />
      <div style={{ position: "absolute", left: 160, top: 300, width: 820 }}>
        <div style={{ ...rise(f, 0), fontFamily: FONTS.ui, fontSize: 24, fontWeight: 500, letterSpacing: "0.24em", textTransform: "uppercase", color: "#7A7266" }}>
          Real bot · test data</div>
        <div style={{ ...rise(f, 6), fontFamily: FONTS.serif, fontSize: 150, lineHeight: 0.95, color: "#17140F", marginTop: 26 }}>
          Staff just <i style={{ color: PINK }}>message</i> it.</div>
        <div style={{ ...rise(f, 14), fontFamily: FONTS.ui, fontWeight: 400, fontSize: 42, color: "#5A5348", marginTop: 34 }}>
          A check-in, done in a WhatsApp chat.</div>
      </div>
      <Phone src={WA.src} aspect={WA.aspect} width={400} trimBefore={9.6 * 30} shell="#17140F"
        style={{ position: "absolute", right: 180, top: 50 }} />
    </AbsoluteFill>
  );
};

const MAP: Record<Look, Record<Shot, React.FC>> = {
  signal: { hook: SignalHook, demo: SignalDemo },
  midnight: { hook: MidnightHook, demo: MidnightDemo },
  paper: { hook: PaperHook, demo: PaperDemo },
};

export const StyleFrame: React.FC<{ look: Look; shot: Shot }> = ({ look, shot }) => {
  const C = MAP[look][shot];
  return <C />;
};

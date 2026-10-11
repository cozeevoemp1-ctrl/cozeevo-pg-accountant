import React from "react";
import { PhoneDemo } from "../components/PhoneDemo";
import { M } from "../ui";

// Real recordings — app: the PWA on sandbox data; WhatsApp: the real bot on sandbox data.
// Step `at` values are seconds into each clip (ffmpeg scene detection on the take).
const APP = 1864 / 860;
const WA = 1688 / 780;

export const AppCollect: React.FC = () => (
  <PhoneDemo clip="app_collect.mp4" clipSeconds={14.27} aspect={APP} phoneSide="left" glow={M.blue}
    eyebrow="Front end 1 · The app"
    title={<>Collect <span style={{ color: M.blue }}>rent.</span></>}
    steps={[
      { at: 1.2, label: "Open who still owes" },
      { at: 2.7, label: "Find the tenant" },
      { at: 4.0, label: "Enter cash or UPI" },
      { at: 7.7, label: "Recorded" },
      { at: 10.3, label: "Totals update instantly" },
    ]} />
);

export const AppVacant: React.FC = () => (
  <PhoneDemo clip="app_vacant.mp4" clipSeconds={7.07} aspect={APP} phoneSide="left" glow={M.blue}
    eyebrow="Front end 1 · The app"
    title={<>Check <span style={{ color: M.blue }}>free beds.</span></>}
    sub="Every free bed by room, filtered for male or female roommates." />
);

export const WaQuick: React.FC = () => (
  <PhoneDemo clip="wa_quick.mp4" clipSeconds={16.37} aspect={WA}
    eyebrow="Front end 2 · WhatsApp"
    title={<>For quick stuff, <span style={{ color: M.pink }}>just ask.</span></>}
    steps={[
      { at: 0.4, label: "“Any male beds available?”" },
      { at: 4.6, label: "“Beds free in HULK floor 2?”" },
      { at: 8.6, label: "“Vinay paid 20000 UPI”" },
      { at: 13.4, label: "Confirmed and saved" },
    ]} />
);

export const SameRecord: React.FC = () => (
  <PhoneDemo clip="app_recent.mp4" clipSeconds={4.0} aspect={APP} phoneSide="left" glow={M.pink}
    eyebrow="One record" titleSize={84}
    title={<>Logged on WhatsApp.<br /><span style={{ color: M.pink }}>Already in the app.</span></>}
    spot={{ from: 3.0, top: "61.5%", height: "6.8%" }} />
);

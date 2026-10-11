import React from "react";
import { ProductShot } from "../components/ProductShot";
import { M } from "../ui";

// Real recordings on test data. Pin `at` = seconds into the clip (ffmpeg scene detection).
export const App: React.FC = () => (
  <ProductShot n="01" name="Web app" line="For managers: rent, beds and every tenant in one place."
    clip="app_collect.mp4" clipFrom={0.8} clipTo={12.0} aspect={1864 / 860} color={M.blue}
    pins={[
      { at: 4.0, y: 0.3, label: "Record a rent payment" },
      { at: 10.3, y: 0.12, label: "Totals update instantly" },
    ]} />
);

// Three everyday questions to the real bot (test data). Payments stay in the app in production.
export const Bot: React.FC = () => (
  <ProductShot n="02" name="WhatsApp assistant" line="For staff on the go: just ask in plain words."
    clip="wa_three.mp4" clipFrom={0.3} clipTo={11.6} aspect={1688 / 780} color={M.pink}
    pins={[
      { at: 2.7, y: 0.25, label: "Free rooms, instantly" },
      { at: 6.1, y: 0.7, label: "Repair ticket logged" },
      { at: 9.4, y: 0.84, label: "Who lives where" },
    ]} />
);

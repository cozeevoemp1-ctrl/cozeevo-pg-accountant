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

// WhatsApp take trimmed before the payment message: production keeps payments in the app.
export const Bot: React.FC = () => (
  <ProductShot n="02" name="WhatsApp assistant" line="For staff on the go: ask in plain words."
    clip="wa_quick.mp4" clipFrom={0.3} clipTo={8.5} aspect={1688 / 780} color={M.pink}
    pins={[
      { at: 0.9, y: 0.965, label: "Staff type a question" },
      { at: 2.7, y: 0.25, label: "Instant answer from live data" },
      { at: 5.6, y: 0.47, label: "Ask the next one" },
    ]} />
);

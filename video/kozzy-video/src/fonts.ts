import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

// The app's own typefaces (embedded in mockups/kozzy.html) + one editorial serif.
export const FONTS = {
  display: "DM Sans", // variable: weight 100-1000, width 75-125% (condensed via fontStretch)
  ui: "Geist",
  serif: "Instrument Serif",
};

export const fontsReady = Promise.all([
  loadFont({ family: "DM Sans", url: staticFile("DMSans.ttf"), weight: "100 900" }),
  loadFont({ family: "Geist", url: staticFile("Geist.ttf"), weight: "100 900" }),
  loadFont({ family: "Instrument Serif", url: staticFile("InstrumentSerif.ttf"), weight: "400" }),
]);

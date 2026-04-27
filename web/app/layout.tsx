import { DM_Sans } from "next/font/google";
import type { Metadata, Viewport } from "next";
import { AuthProvider } from "@/components/auth/auth-provider";
import "./globals.css";

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-dm-sans",
  weight: ["400", "500", "600", "700", "800"],
});

export const metadata: Metadata = {
  title: "Kozzy · Cozeevo Help Desk",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Kozzy",
  },
};

export const viewport: Viewport = {
  themeColor: "#EF1F9C",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={dmSans.variable}>
      <body className="bg-bg text-ink font-sans min-h-screen" suppressHydrationWarning>
          <AuthProvider>{children}</AuthProvider>
        </body>
    </html>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

const PULL_THRESHOLD = 72; // px of visual pull needed to trigger
const MAX_VISUAL = 110;    // max rubber-band translation

export function PullToRefresh({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [dist, setDist] = useState(0);       // visual pull distance (damped)
  const [refreshing, setRefreshing] = useState(false);

  const startY = useRef(0);
  const active = useRef(false);
  const distRef = useRef(0); // shadow of dist for use inside event closures

  useEffect(() => {
    function onTouchStart(e: TouchEvent) {
      // Only activate pull when page is already scrolled to very top
      if (window.scrollY > 2) return;
      startY.current = e.touches[0].clientY;
      active.current = true;
    }

    function onTouchMove(e: TouchEvent) {
      if (!active.current) return;
      const raw = e.touches[0].clientY - startY.current;
      if (raw <= 0) {
        active.current = false;
        distRef.current = 0;
        setDist(0);
        return;
      }
      // rubber-band: sqrt-based damping feels natural
      const damped = Math.min(Math.sqrt(raw) * 5, MAX_VISUAL);
      distRef.current = damped;
      setDist(damped);
      // prevent native overscroll while pulling
      if (raw > 4) e.preventDefault();
    }

    function onTouchEnd() {
      if (!active.current) return;
      active.current = false;
      const d = distRef.current;
      distRef.current = 0;
      setDist(0);
      if (d >= PULL_THRESHOLD) {
        setRefreshing(true);
        router.refresh();
        setTimeout(() => setRefreshing(false), 1400);
      }
    }

    document.addEventListener("touchstart", onTouchStart, { passive: true });
    document.addEventListener("touchmove", onTouchMove, { passive: false });
    document.addEventListener("touchend", onTouchEnd, { passive: true });

    return () => {
      document.removeEventListener("touchstart", onTouchStart);
      document.removeEventListener("touchmove", onTouchMove);
      document.removeEventListener("touchend", onTouchEnd);
    };
  }, [router]);

  // indicator visibility: show while pulling or while data is reloading
  const visible = dist > 0 || refreshing;
  const translateY = refreshing ? 20 : Math.max(dist - 14, 0);
  const opacity = refreshing ? 1 : Math.min(dist / 40, 1);
  // spinner arc: tracks pull angle before trigger, then spins continuously
  const arcDeg = refreshing ? undefined : Math.min((dist / PULL_THRESHOLD) * 270, 270);

  return (
    <>
      {/* Pull indicator — fixed at top, pointer-events none */}
      <div
        aria-hidden
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          zIndex: 9999,
          display: "flex",
          justifyContent: "center",
          transform: `translateY(${translateY}px)`,
          opacity: visible ? opacity : 0,
          transition: refreshing ? "transform 0.22s ease, opacity 0.18s ease" : "none",
          pointerEvents: "none",
        }}
      >
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: "50%",
            background: "#FFFFFF",
            boxShadow: "0 2px 10px rgba(0,0,0,0.14)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <div
            style={{
              width: 20,
              height: 20,
              borderRadius: "50%",
              border: "2.5px solid #EF1F9C",
              borderTopColor: "transparent",
              animation: refreshing ? "kozzy-spin 0.72s linear infinite" : "none",
              transform: refreshing ? undefined : `rotate(${arcDeg}deg)`,
              transition: refreshing ? undefined : "transform 0.06s linear",
            }}
          />
        </div>
      </div>

      {children}
    </>
  );
}

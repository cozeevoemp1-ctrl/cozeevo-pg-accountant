"use client";

import { clsx } from "clsx";
import type { ReactNode } from "react";

export interface TabBarItem {
  key: string;
  label: string;
  icon: ReactNode;
  /** When true, renders as the centre mic-style action button */
  isCta?: boolean;
  href?: string;
  onClick?: () => void;
}

interface TabBarProps {
  items: TabBarItem[];
  activeKey?: string;
}

export function TabBar({ items, activeKey }: TabBarProps) {
  return (
    <nav className="fixed bottom-0 inset-x-0 bg-surface border-t border-[#E2DEDD] flex items-center justify-around h-16 px-2 z-50 safe-area-inset-bottom">
      {items.map((item) => {
        const isActive = item.key === activeKey;
        if (item.isCta) {
          return (
            <button
              key={item.key}
              onClick={item.onClick}
              aria-label={item.label}
              className="flex items-center justify-center w-14 h-14 -mt-5 rounded-full bg-brand-pink text-white shadow-lg active:scale-95 transition-transform"
            >
              {item.icon}
            </button>
          );
        }
        return (
          <button
            key={item.key}
            onClick={item.onClick}
            className={clsx(
              "flex flex-col items-center gap-0.5 flex-1 py-1 text-[10px] font-medium transition-colors",
              isActive ? "text-brand-pink" : "text-ink-muted",
            )}
          >
            <span className="text-xl">{item.icon}</span>
            {item.label}
          </button>
        );
      })}
    </nav>
  );
}

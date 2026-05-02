"use client";

import { clsx } from "clsx";
import type { ReactNode } from "react";

export interface TabBarItem {
  key: string;
  label: string;
  icon: ReactNode;
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
    <div className="fixed bottom-0 inset-x-0 z-50 flex justify-center pb-5 px-6 pointer-events-none">
      <nav className="pointer-events-auto flex items-center gap-1 bg-[#1C1C1E] rounded-full px-3 py-2.5 shadow-2xl">
        {items.map((item) => {
          const isActive = item.key === activeKey;
          if (item.isCta) {
            return (
              <button
                key={item.key}
                onClick={item.onClick}
                aria-label={item.label}
                className="flex items-center justify-center w-14 h-14 mx-1 rounded-full bg-brand-pink text-white shadow-lg active:scale-95 transition-transform"
              >
                {item.icon}
              </button>
            );
          }
          return (
            <button
              key={item.key}
              onClick={item.onClick}
              aria-label={item.label}
              className={clsx(
                "flex items-center justify-center w-12 h-12 rounded-full transition-all duration-200",
                isActive ? "bg-[#00AEED] text-white" : "text-[#8E8E93]",
              )}
            >
              {item.icon}
            </button>
          );
        })}
      </nav>
    </div>
  );
}

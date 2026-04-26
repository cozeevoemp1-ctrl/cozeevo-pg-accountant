"use client";

interface MicButtonProps {
  onClick: () => void;
  active?: boolean;
}

export function MicButton({ onClick, active = false }: MicButtonProps) {
  return (
    <button
      onClick={onClick}
      aria-label="Voice"
      className={`flex items-center justify-center w-14 h-14 -mt-5 rounded-full shadow-lg active:scale-95 transition-all ${
        active
          ? "bg-brand-pink ring-4 ring-brand-pink/30 animate-pulse"
          : "bg-brand-pink"
      } text-white`}
    >
      <MicIcon />
    </button>
  );
}

function MicIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="9" y="2" width="6" height="12" rx="3" fill="currentColor" />
      <path
        d="M5 10a7 7 0 0 0 14 0"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <line x1="12" y1="17" x2="12" y2="21" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="8" y1="21" x2="16" y2="21" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

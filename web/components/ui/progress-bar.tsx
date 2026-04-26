import { clsx } from "clsx";

interface ProgressBarProps {
  value: number; // 0–100
  className?: string;
  color?: string; // tailwind bg class, default brand-pink
}

export function ProgressBar({
  value,
  className,
  color = "bg-brand-pink",
}: ProgressBarProps) {
  const clamped = Math.min(100, Math.max(0, value));
  return (
    <div
      className={clsx("w-full rounded-full bg-[#EDE8E3] overflow-hidden", className)}
      style={{ height: 6 }}
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={clsx("h-full rounded-full transition-all duration-300", color)}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

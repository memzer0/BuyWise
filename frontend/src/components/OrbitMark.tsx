import { useId } from "react";

/** BuyWise mark: one white price tag on a cobalt tile, with a sun-yellow tag hole. Two shapes, no detail to lose
 *  at 16 px – reads the same as a favicon, in the header and at hero size. */
export function LogoMark({ size = 32, className = "" }: { size?: number; className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg viewBox="0 0 48 48" width={size} height={size} className={className} aria-hidden>
      <defs>
        <linearGradient id={`bw-tile-${id}`} x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#2f63f0" />
          <stop offset="1" stopColor="#1546d9" />
        </linearGradient>
      </defs>
      <rect width="48" height="48" rx="14" fill={`url(#bw-tile-${id})`} />
      <path d="M24.6 11.5h9.9a2 2 0 0 1 2 2v9.9a2 2 0 0 1-.6 1.4L24.8 35.9a2 2 0 0 1-2.8 0l-9.9-9.9a2 2 0 0 1 0-2.8l11.1-11.1a2 2 0 0 1 1.4-.6z" fill="#ffffff" />
      <circle cx="30.4" cy="17.6" r="2.9" fill="#f9b318" />
    </svg>
  );
}

/** Kept for existing imports. */
export const OrbitMark = ({ size = 32, className = "" }: { size?: number; className?: string; spin?: boolean }) =>
  <LogoMark size={size} className={className} />;

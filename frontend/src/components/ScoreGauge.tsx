/** Semicircle gauge (0–100) with red → amber → green bands and a needle. */
export function ScoreGauge({ score, size = 150 }: { score: number | null; size?: number }) {
  const r = 52;
  const cx = 70;
  const cy = 66;
  const arc = (from: number, to: number) => {
    const a0 = Math.PI * (1 - from / 100);
    const a1 = Math.PI * (1 - to / 100);
    const x0 = cx + r * Math.cos(a0);
    const y0 = cy - r * Math.sin(a0);
    const x1 = cx + r * Math.cos(a1);
    const y1 = cy - r * Math.sin(a1);
    return `M ${x0} ${y0} A ${r} ${r} 0 0 1 ${x1} ${y1}`;
  };
  const bands: [number, number, string][] = [
    [0, 30, "#d64553"], [31, 50, "#f9b318"], [51, 70, "#8aa4f0"], [71, 85, "#2e9e62"], [86, 100, "#1546d9"],
  ];
  const v = score === null ? null : Math.max(0, Math.min(100, score));
  const angle = v === null ? null : Math.PI * (1 - v / 100);
  return (
    <svg viewBox="0 0 140 84" width={size} role="img" aria-label={v === null ? "Score not available" : `BuyWise score ${v} out of 100`}>
      {bands.map(([a, b, c]) => (
        <path key={a} d={arc(a, b)} stroke={c} strokeWidth={13} fill="none" strokeLinecap="butt" />
      ))}
      {angle !== null && (
        <>
          <line x1={cx} y1={cy} x2={cx + (r - 8) * Math.cos(angle)} y2={cy - (r - 8) * Math.sin(angle)}
            stroke="#14172b" strokeWidth={3} strokeLinecap="round" />
          <circle cx={cx} cy={cy} r={5} fill="#f9b318" stroke="#14172b" strokeWidth={2.5} />
        </>
      )}
      <text x={cx - r} y={cy + 15} fontSize="8" textAnchor="middle" fill="#545a70">0</text>
      <text x={cx + r} y={cy + 15} fontSize="8" textAnchor="middle" fill="#545a70">100</text>
    </svg>
  );
}

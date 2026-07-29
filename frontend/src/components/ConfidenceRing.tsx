function colorFor(value: number): string {
  if (value >= 0.85) return "#1f9d6c";
  if (value >= 0.6) return "#e4711c";
  return "#d9432c";
}

export function ConfidenceRing({
  value,
  size = 40,
  stroke = 4,
  showLabel = true,
}: {
  value: number;
  size?: number;
  stroke?: number;
  showLabel?: boolean;
}) {
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - value);
  const color = colorFor(value);

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#e6e9eb" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 0.5s ease" }}
        />
      </svg>
      {showLabel && (
        <span className="absolute text-[10px] font-bold tabular-nums text-ink-700" style={{ fontSize: size * 0.26 }}>
          {Math.round(value * 100)}
        </span>
      )}
    </div>
  );
}

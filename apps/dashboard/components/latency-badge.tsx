export function LatencyBadge({ ms, label }: { ms: number | null | undefined; label: string }) {
  if (ms == null) return null;
  const color =
    ms < 300  ? "text-green-600 dark:text-green-400" :
    ms < 700  ? "text-yellow-600 dark:text-yellow-400" :
                "text-red-600 dark:text-red-400";
  return (
    <span className={`font-mono text-xs ${color}`}>
      {label} {ms}ms
    </span>
  );
}

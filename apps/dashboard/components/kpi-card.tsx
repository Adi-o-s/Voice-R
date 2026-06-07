export function KpiCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-6">
      <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-3 font-mono text-3xl font-medium tracking-tight">{value}</p>
      {sub && <p className="mt-1 font-mono text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

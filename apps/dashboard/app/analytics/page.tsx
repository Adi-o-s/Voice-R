export const dynamic = "force-dynamic";
import { createServerClient } from "@/lib/supabase";
import { KpiCard } from "@/components/kpi-card";

export default async function AnalyticsPage() {
  const sb = createServerClient();

  const [callsRes, bookingsRes, emergenciesRes, latencyRes] = await Promise.all([
    sb.from("calls").select("id", { count: "exact", head: true })
      .gte("started_at", new Date(Date.now() - 86400000).toISOString()),

    sb.from("calls").select("id", { count: "exact", head: true })
      .eq("outcome", "booked")
      .gte("started_at", new Date(Date.now() - 86400000).toISOString()),

    sb.from("calls").select("id", { count: "exact", head: true })
      .eq("outcome", "emergency")
      .gte("started_at", new Date(Date.now() - 86400000).toISOString()),

    sb.from("transcripts").select("llm_latency_ms")
      .not("llm_latency_ms", "is", null)
      .gte("started_at", new Date(Date.now() - 86400000).toISOString()),
  ]);

  const llmValues = (latencyRes.data ?? [])
    .map((r) => r.llm_latency_ms as number)
    .filter(Boolean);
  // p50 (median), not mean — the label promises p50, and a few cold-start /
  // LLM-failover turns (4–10s) skew the mean badly while barely moving the median.
  const llmP50 = (() => {
    if (!llmValues.length) return null;
    const s = [...llmValues].sort((a, b) => a - b);
    const m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2);
  })();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Analytics</h1>
        <p className="mt-1 text-sm text-muted-foreground">Last 24 hours.</p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <KpiCard
          label="Calls today"
          value={callsRes.count ?? 0}
        />
        <KpiCard
          label="Bookings today"
          value={bookingsRes.count ?? 0}
          sub={`${callsRes.count ? Math.round(((bookingsRes.count ?? 0) / callsRes.count) * 100) : 0}% conversion`}
        />
        <KpiCard
          label="Emergencies"
          value={emergenciesRes.count ?? 0}
        />
        <KpiCard
          label="LLM latency (p50)"
          value={llmP50 != null ? `${llmP50}ms` : "—"}
          sub="target: <500ms"
        />
      </div>
    </div>
  );
}

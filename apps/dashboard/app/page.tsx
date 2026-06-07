"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { OutcomeBadge } from "@/components/outcome-badge";
import type { Call } from "@/lib/types";

function fmt(iso: string) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function duration(call: Call) {
  const end = call.ended_at ? new Date(call.ended_at) : new Date();
  const s = Math.floor((end.getTime() - new Date(call.started_at).getTime()) / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

export default function HomePage() {
  const [calls, setCalls] = useState<Call[]>([]);

  useEffect(() => {
    const sb = createClient();

    sb.from("calls")
      .select("*")
      .order("started_at", { ascending: false })
      .limit(50)
      .then(({ data }) => { if (data) setCalls(data as Call[]); });

    const sub = sb
      .channel("calls-live")
      .on("postgres_changes", { event: "*", schema: "public", table: "calls" }, (payload) => {
        setCalls((prev) => {
          if (payload.eventType === "INSERT") return [payload.new as Call, ...prev];
          if (payload.eventType === "UPDATE") {
            return prev.map((c) => c.id === (payload.new as Call).id ? payload.new as Call : c);
          }
          return prev;
        });
      })
      .subscribe();

    return () => { sb.removeChannel(sub); };
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Live calls</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Updates in real time via Supabase Realtime.
        </p>
      </div>

      {calls.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-muted/40 p-12 text-center">
          <p className="text-sm text-muted-foreground">
            No calls yet. Dial +1 (620) 634-8082 to start.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/40">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Caller</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Started</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Duration</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Status</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">LLM p50</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {calls.map((call) => (
                <tr key={call.id} className="transition-colors hover:bg-muted/30">
                  <td className="px-4 py-3">
                    <Link href={`/calls/${call.id}`} className="font-mono hover:underline">
                      ···{call.caller_phone_last4 ?? call.caller_phone.slice(-4)}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{fmt(call.started_at)}</td>
                  <td className="px-4 py-3 font-mono text-muted-foreground">{duration(call)}</td>
                  <td className="px-4 py-3"><OutcomeBadge outcome={call.outcome} /></td>
                  <td className="px-4 py-3 font-mono text-muted-foreground">
                    {call.latency_metrics?.llm_ms_p50 != null
                      ? `${call.latency_metrics.llm_ms_p50}ms`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

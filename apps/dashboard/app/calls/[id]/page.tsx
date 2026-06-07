"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { OutcomeBadge } from "@/components/outcome-badge";
import { TranscriptTurn } from "@/components/transcript-turn";
import type { Call, Transcript } from "@/lib/types";

export default function CallPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [call, setCall] = useState<Call | null>(null);
  const [turns, setTurns] = useState<Transcript[]>([]);

  useEffect(() => {
    const sb = createClient();

    sb.from("calls").select("*").eq("id", id).single()
      .then(({ data }) => { if (data) setCall(data as Call); });

    sb.from("transcripts").select("*").eq("call_id", id).order("turn_index")
      .then(({ data }) => { if (data) setTurns(data as Transcript[]); });

    const sub = sb
      .channel(`call-${id}`)
      .on("postgres_changes",
        { event: "INSERT", schema: "public", table: "transcripts", filter: `call_id=eq.${id}` },
        (payload) => {
          setTurns((prev) => [...prev, payload.new as Transcript]);
        }
      )
      .on("postgres_changes",
        { event: "UPDATE", schema: "public", table: "calls", filter: `id=eq.${id}` },
        (payload) => { setCall(payload.new as Call); }
      )
      .subscribe();

    return () => { sb.removeChannel(sub); };
  }, [id]);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">← Calls</Link>
        {call && (
          <>
            <span className="font-mono text-sm">{call.caller_phone}</span>
            <OutcomeBadge outcome={call.outcome} />
          </>
        )}
      </div>

      {call && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            { label: "STT p50", ms: call.latency_metrics?.stt_ms_p50 },
            { label: "LLM p50", ms: call.latency_metrics?.llm_ms_p50 },
            { label: "TTS p50", ms: call.latency_metrics?.tts_ms_p50 },
          ].map(({ label, ms }) => (
            <div key={label} className="rounded-lg border border-border p-4">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className={`mt-1 text-xl font-semibold font-mono ${
                ms == null ? "text-muted-foreground" :
                ms < 300 ? "text-green-600 dark:text-green-400" :
                ms < 700 ? "text-yellow-600 dark:text-yellow-400" :
                "text-red-600 dark:text-red-400"
              }`}>
                {ms != null ? `${ms}ms` : "—"}
              </p>
            </div>
          ))}
          <div className="rounded-lg border border-border p-4">
            <p className="text-xs text-muted-foreground">Turns</p>
            <p className="mt-1 text-xl font-semibold">{turns.length}</p>
          </div>
        </div>
      )}

      <div className="space-y-4">
        {turns.length === 0 ? (
          <p className="text-sm text-muted-foreground">No transcript yet.</p>
        ) : (
          turns.map((turn) => <TranscriptTurn key={turn.id} turn={turn} />)
        )}
      </div>
    </div>
  );
}

import { Transcript } from "@/lib/types";
import { LatencyBadge } from "./latency-badge";

export function TranscriptTurn({ turn }: { turn: Transcript }) {
  const isUser = turn.role === "user";
  return (
    <div className={`flex gap-3 ${isUser ? "" : "flex-row-reverse"}`}>
      <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold
        ${isUser
          ? "bg-muted text-muted-foreground"
          : "bg-primary text-primary-foreground"}`}>
        {isUser ? "U" : "M"}
      </div>
      <div className={`max-w-[75%] space-y-1 ${isUser ? "" : "items-end"}`}>
        <div className={`rounded-2xl px-4 py-2.5 text-sm
          ${isUser
            ? "rounded-tl-sm bg-muted text-foreground"
            : "rounded-tr-sm border border-border bg-card text-foreground"}`}>
          {turn.text}
        </div>
        <div className={`flex gap-3 px-1 ${isUser ? "" : "flex-row-reverse"}`}>
          {isUser
            ? <LatencyBadge ms={turn.stt_latency_ms} label="STT" />
            : <>
                <LatencyBadge ms={turn.llm_latency_ms} label="LLM" />
                <LatencyBadge ms={turn.tts_latency_ms} label="TTS" />
              </>
          }
        </div>
      </div>
    </div>
  );
}

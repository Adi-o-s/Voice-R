export type CallOutcome =
  | "in_progress"
  | "booked"
  | "emergency"
  | "info_only"
  | "dropped"
  | "completed"
  | "infra_error";

export type TranscriptRole = "user" | "assistant" | "tool" | "system";
export type AppointmentStatus = "pending" | "confirmed" | "cancelled" | "completed";

export interface Call {
  id: string;
  twilio_call_sid: string;
  caller_phone: string;
  caller_phone_last4: string;
  started_at: string;
  ended_at: string | null;
  outcome: CallOutcome;
  latency_metrics: {
    stt_ms_p50?: number | null;
    llm_ms_p50?: number | null;
    tts_ms_p50?: number | null;
  } | null;
  created_at: string;
}

export interface Transcript {
  id: string;
  call_id: string;
  turn_index: number;
  role: TranscriptRole;
  text: string;
  tool_name: string | null;
  started_at: string;
  ended_at: string;
  stt_latency_ms: number | null;
  llm_latency_ms: number | null;
  tts_latency_ms: number | null;
}

export interface Appointment {
  id: string;
  call_id: string;
  customer_name: string;
  customer_phone: string;
  customer_address: string;
  scheduled_at: string;
  status: AppointmentStatus;
  confirmation_code: string;
  notes: string | null;
  created_at: string;
  services?: { name: string };
}

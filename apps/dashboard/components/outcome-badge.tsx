import { CallOutcome } from "@/lib/types";

// Color carries meaning, not decoration: green = active, emerald = won the booking,
// red = emergency, slate = neutral/info, amber = dropped. No violet (the AI-startup tell).
const styles: Record<CallOutcome, string> = {
  in_progress: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
  completed:   "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  booked:      "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400",
  emergency:   "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
  info_only:   "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  dropped:     "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400",
  infra_error: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
};

const labels: Record<CallOutcome, string> = {
  in_progress: "Live",
  completed:   "Completed",
  booked:      "Booked",
  emergency:   "Emergency",
  info_only:   "Info only",
  dropped:     "Dropped",
  infra_error: "Error",
};

export function OutcomeBadge({ outcome }: { outcome: CallOutcome }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[outcome]}`}>
      {outcome === "in_progress" && (
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
        </span>
      )}
      {labels[outcome]}
    </span>
  );
}

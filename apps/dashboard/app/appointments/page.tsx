export const dynamic = "force-dynamic";
import { createServerClient } from "@/lib/supabase";
import type { Appointment } from "@/lib/types";

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString([], {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

const statusStyles: Record<string, string> = {
  confirmed:  "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
  pending:    "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400",
  cancelled:  "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
  completed:  "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400",
};

export default async function AppointmentsPage() {
  const sb = createServerClient();
  const { data } = await sb
    .from("appointments")
    .select("*, services(name)")
    .order("scheduled_at", { ascending: false })
    .limit(100);

  const appointments = (data ?? []) as Appointment[];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Bookings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          All appointments booked via the voice agent.
        </p>
      </div>

      {appointments.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-muted/40 p-12 text-center">
          <p className="text-sm text-muted-foreground">No bookings yet.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/50">
              <tr className="[&>th]:px-4 [&>th]:py-3 [&>th]:text-left [&>th]:text-[11px] [&>th]:font-bold [&>th]:uppercase [&>th]:tracking-wider [&>th]:text-muted-foreground">
                <th>Customer</th>
                <th>Service</th>
                <th>Scheduled</th>
                <th>Code</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {appointments.map((a) => (
                <tr key={a.id} className="hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-3">
                    <p className="font-medium">{a.customer_name}</p>
                    <p className="text-xs text-muted-foreground">{a.customer_address}</p>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {a.services?.name ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{fmtDate(a.scheduled_at)}</td>
                  <td className="px-4 py-3 font-mono text-xs">{a.confirmation_code}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${statusStyles[a.status] ?? ""}`}>
                      {a.status}
                    </span>
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

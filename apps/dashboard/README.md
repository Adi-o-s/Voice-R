# dashboard

Next.js 15 App Router. Live transcripts, bookings, analytics. See the [project root README](../../README.md).

## Run

```bash
# From project root:
make dash          # pnpm dev on :3000
```

Or directly:

```bash
corepack enable pnpm   # one-time
pnpm install
pnpm dev
```

Set the following in `.env.local` (in this directory):

```
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
```

## Routes (planned)

| Route | Purpose |
|---|---|
| `/` | Live calls grid (Supabase Realtime) |
| `/calls/[id]` | Call detail: per-turn transcript with latency badges |
| `/appointments` | Bookings table |
| `/analytics` | KPI cards |

## Deploy

```bash
pnpm dlx vercel link
pnpm dlx vercel --prod
```

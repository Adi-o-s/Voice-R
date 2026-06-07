import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Voice AI Receptionist — Live Dashboard",
  description: "Real-time transcripts, bookings, and per-turn latency for Acme Plumbing.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body className="min-h-screen antialiased">
        <header className="border-b border-border">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
            <div className="flex items-center gap-3">
              <span className="text-lg font-semibold tracking-tight">
                Voice AI Receptionist
              </span>
              <span className="rounded-md bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground">
                acme-plumbing
              </span>
            </div>
            <nav className="flex gap-6 text-sm text-muted-foreground">
              <Link href="/" className="hover:text-foreground">Live</Link>
              <Link href="/appointments" className="hover:text-foreground">Bookings</Link>
              <Link href="/analytics" className="hover:text-foreground">Analytics</Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}

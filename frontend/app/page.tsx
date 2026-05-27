"use client";

import { useEffect, useRef, useState } from "react";

type Role = "user" | "assistant";
type Message = { role: Role; content: string };
type ChatResponse = {
  reply: string;
  session_id: string;
  stats: { cost_usd: number; n_calls: number };
  booking_state: Record<string, unknown> | null;
};

const SUGGESTIONS = [
  "What time is check-in at Vibe Sydney?",
  "Book me 2 nights in Sydney near the beach from 2026-07-10 for 2 people under $400/night, with a gym.",
  "Is there parking at Adina Bondi?",
  "Find a family room in Auckland for 3 nights in August.",
];

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionId] = useState(() => `s-${Math.random().toString(36).slice(2, 10)}`);
  const [lastCost, setLastCost] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    const next: Message[] = [...messages, { role: "user", content: trimmed }];
    setMessages(next);
    setInput("");
    setBusy(true);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ messages: next, session_id: sessionId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: ChatResponse = await res.json();
      setMessages([...next, { role: "assistant", content: data.reply }]);
      setLastCost(data.stats.cost_usd);
    } catch (err) {
      setMessages([
        ...next,
        { role: "assistant", content: `Sorry — something went wrong (${(err as Error).message}).` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex h-screen max-w-2xl flex-col p-4">
      <header className="mb-3 border-b border-stone-200 pb-3">
        <h1 className="text-lg font-medium">TFE Guest Concierge</h1>
        <p className="text-xs text-stone-500">
          Demo on synthetic data. Booking back-end is mocked — no real reservations are made.
        </p>
      </header>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto pr-1">
        {messages.length === 0 && (
          <div className="space-y-2">
            <p className="text-sm text-stone-500">Try one of these:</p>
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="block w-full rounded-md border border-stone-200 bg-white p-3 text-left text-sm hover:border-stone-400"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`rounded-lg p-3 text-sm leading-relaxed ${
              m.role === "user"
                ? "ml-12 bg-stone-900 text-white"
                : "mr-12 bg-white text-stone-900 ring-1 ring-stone-200"
            }`}
          >
            {m.content}
          </div>
        ))}
        {busy && <div className="mr-12 rounded-lg bg-white p-3 text-sm text-stone-400 ring-1 ring-stone-200">…</div>}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="mt-3 flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={busy}
          placeholder="Ask about a property, or start a booking…"
          className="flex-1 rounded-md border border-stone-300 bg-white px-3 py-2 text-sm focus:border-stone-500 focus:outline-none disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded-md bg-stone-900 px-4 py-2 text-sm text-white hover:bg-stone-700 disabled:opacity-50"
        >
          Send
        </button>
      </form>

      <footer className="mt-2 flex justify-between text-xs text-stone-400">
        <span>session: {sessionId}</span>
        {lastCost !== null && <span>last turn: ${lastCost.toFixed(4)}</span>}
      </footer>
    </main>
  );
}

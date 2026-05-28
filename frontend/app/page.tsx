"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Role = "user" | "assistant";

type Offer = {
  id: string;
  name: string;
  discount_pct: number;
  min_nights: number;
};

type HotelOption = {
  property_id: string;
  name: string;
  city: string;
  neighbourhood?: string;
  price_per_night?: number;
  amenities?: string[];
  rating?: number;
  check_in?: string;
  check_out?: string;
  guests?: number;
  offers?: Offer[];
};

type BookingResult = {
  booking_id: string;
  property_id: string;
  check_in: string;
  check_out: string;
  guests: number;
  status: string;
  total_aud: number;
};

type ResponseMetadata = {
  mentioned_properties: string[];
  available_options: HotelOption[];
  booking_result: BookingResult | null;
};

type Message = {
  role: Role;
  content: string;
  metadata?: ResponseMetadata;
};

// ---------------------------------------------------------------------------
// ICS calendar file generator
// ---------------------------------------------------------------------------

function generateICS(booking: BookingResult, hotelName: string): string {
  const fmt = (d: string) => d.replace(/-/g, "");
  return [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//TFE Hotels//Guest Concierge Demo//EN",
    "BEGIN:VEVENT",
    `DTSTART;VALUE=DATE:${fmt(booking.check_in)}`,
    `DTEND;VALUE=DATE:${fmt(booking.check_out)}`,
    `SUMMARY:TFE Hotels — ${hotelName}`,
    `DESCRIPTION:Booking ${booking.booking_id} · ${booking.guests} guest${booking.guests !== 1 ? "s" : ""}`,
    `UID:${booking.booking_id}@tfe-concierge-demo`,
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n");
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function TypingDots() {
  return (
    <div className="flex items-center gap-1.5 py-1 px-0.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-2 h-2 rounded-full bg-navy/40 dot-bounce"
          style={{ animationDelay: `${i * 0.2}s` }}
        />
      ))}
    </div>
  );
}

function CardHeader({ name, city }: { name: string; city: string }) {
  // Brand-based gradient
  const brand = name.toLowerCase();
  const gradient = brand.includes("vibe")
    ? "from-teal-700 to-teal-900"
    : brand.includes("adina")
    ? "from-purple-700 to-purple-900"
    : "from-navy to-navy-light";

  return (
    <div className={`h-28 bg-gradient-to-br ${gradient} flex flex-col justify-end p-3`}>
      <p className="text-xs font-medium text-gold-light uppercase tracking-wide">{city}</p>
      <h3 className="font-serif text-base font-semibold leading-tight text-white">{name}</h3>
    </div>
  );
}

function PropertyCard({
  option,
  index,
  onSelect,
}: {
  option: HotelOption;
  index: number;
  onSelect: (n: number) => void;
}) {
  const bestOffer = option.offers?.[0];
  const topAmenities = (option.amenities ?? []).slice(0, 3);
  const basePrice = option.price_per_night;
  const discountedPrice =
    bestOffer && basePrice ? basePrice * (1 - bestOffer.discount_pct / 100) : basePrice;

  return (
    <div className="w-64 flex-shrink-0 rounded-xl border border-stone-200 bg-white shadow-sm overflow-hidden">
      <CardHeader name={option.name} city={option.city} />
      <div className="p-4 space-y-3">
        {option.neighbourhood && (
          <p className="text-xs text-stone-500 -mt-1">{option.neighbourhood}</p>
        )}
        {topAmenities.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {topAmenities.map((a) => (
              <span
                key={a}
                className="rounded-full bg-stone-100 px-2 py-0.5 text-xs text-stone-600"
              >
                {a}
              </span>
            ))}
          </div>
        )}
        {discountedPrice !== undefined && (
          <div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-base font-semibold text-navy">
                AUD {Math.round(discountedPrice)}
              </span>
              <span className="text-xs text-stone-400">/night</span>
              {bestOffer && basePrice && (
                <span className="text-xs line-through text-stone-400">
                  {Math.round(basePrice)}
                </span>
              )}
            </div>
            {bestOffer && (
              <p className="text-xs text-gold font-medium mt-0.5">
                {bestOffer.name} — {bestOffer.discount_pct}% off
              </p>
            )}
          </div>
        )}
        <button
          onClick={() => onSelect(index)}
          className="w-full rounded-lg bg-navy py-2 text-sm font-medium text-white hover:bg-navy-light transition-colors"
        >
          Select Option {index}
        </button>
      </div>
    </div>
  );
}

function OptionsGrid({
  options,
  onSelect,
}: {
  options: HotelOption[];
  onSelect: (n: number) => void;
}) {
  if (options.length === 0) return null;
  return (
    <div className="mt-3 -mx-1">
      <div className="flex gap-3 overflow-x-auto pb-2 px-1 scroll-smooth">
        {options.map((opt, i) => (
          <PropertyCard key={opt.property_id} option={opt} index={i + 1} onSelect={onSelect} />
        ))}
      </div>
    </div>
  );
}

function BookingConfirmation({
  result,
  options,
}: {
  result: BookingResult;
  options: HotelOption[];
}) {
  const hotel = options.find((o) => o.property_id === result.property_id);
  const hotelName = hotel?.name ?? result.property_id;
  const nights = Math.round(
    (new Date(result.check_out).getTime() - new Date(result.check_in).getTime()) /
      (1000 * 60 * 60 * 24)
  );

  function downloadICS() {
    const ics = generateICS(result, hotelName);
    const blob = new Blob([ics], { type: "text/calendar" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${result.booking_id}.ics`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mt-3 rounded-xl border border-gold/50 bg-gold/5 p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="h-2 w-2 rounded-full bg-gold" />
        <span className="text-xs font-semibold uppercase tracking-wide text-gold">
          Booking Confirmed
        </span>
      </div>
      <p className="font-serif text-base font-semibold text-navy mb-1">{hotelName}</p>
      <p className="text-xs text-stone-500 mb-3">
        {result.check_in} → {result.check_out} &middot; {nights} night{nights !== 1 ? "s" : ""}{" "}
        &middot; {result.guests} guest{result.guests !== 1 ? "s" : ""}
      </p>
      <div className="flex items-end justify-between border-t border-gold/20 pt-3">
        <div>
          <p className="text-xs text-stone-400">Reference</p>
          <p className="font-mono text-sm font-semibold text-navy">{result.booking_id}</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-stone-400">Total (AUD)</p>
          <p className="text-base font-semibold text-navy">{result.total_aud.toFixed(2)}</p>
        </div>
      </div>
      <button
        onClick={downloadICS}
        className="mt-3 w-full rounded-lg border border-gold/50 py-1.5 text-xs font-medium text-gold hover:bg-gold/10 transition-colors"
      >
        Add to Calendar (.ics)
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Suggestions shown on empty state
// ---------------------------------------------------------------------------

const SUGGESTIONS = [
  "What time is check-in at Vibe Sydney?",
  "Beach hotel in Sydney for 2 nights from July 10, 2026 — under $350/night, gym please.",
  "Is there parking at Adina Bondi Beach?",
  "Book me a family room in Auckland for 3 nights next August.",
];

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [sessionId] = useState(() => `s-${Math.random().toString(36).slice(2, 10)}`);
  // Options from the latest assistant turn (for selection)
  const [latestOptions, setLatestOptions] = useState<HotelOption[]>([]);

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, streamingText, busy]);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || busy) return;

      const history: Message[] = [...messages, { role: "user", content: trimmed }];
      setMessages(history);
      setInput("");
      setBusy(true);
      setStreamingText("");

      let accumulated = "";
      let metadata: ResponseMetadata | null = null;

      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            messages: history.map((m) => ({ role: m.role, content: m.content })),
            session_id: sessionId,
            available_options: latestOptions,
          }),
        });

        if (!res.ok || !res.body) {
          throw new Error(`HTTP ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6);
            if (raw === "[DONE]") break;
            try {
              const event = JSON.parse(raw) as {
                type: "token" | "metadata" | "error";
                text?: string;
                payload?: ResponseMetadata;
                message?: string;
              };
              if (event.type === "token" && event.text) {
                accumulated += event.text;
                setStreamingText(accumulated);
              } else if (event.type === "metadata" && event.payload) {
                metadata = event.payload;
              } else if (event.type === "error") {
                accumulated = event.message ?? "Something went wrong.";
                setStreamingText(accumulated);
              }
            } catch {
              // ignore malformed SSE lines
            }
          }
        }
      } catch (err) {
        accumulated = `Sorry — something went wrong (${(err as Error).message}).`;
      }

      const reply: Message = {
        role: "assistant",
        content: accumulated || "Sorry, I didn't get a response. Please try again.",
        metadata: metadata ?? undefined,
      };
      setMessages((prev) => [...prev, reply]);
      setStreamingText("");
      setBusy(false);

      if (metadata?.available_options?.length) {
        setLatestOptions(metadata.available_options);
      } else if (metadata?.booking_result) {
        setLatestOptions([]);
      }
    },
    [busy, messages, sessionId]
  );

  function selectOption(n: number) {
    send(`Option ${n}`);
  }

  return (
    <main className="mx-auto flex h-screen max-w-2xl flex-col">
      {/* Header */}
      <header className="bg-navy px-5 py-4 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-full bg-gold flex items-center justify-center">
            <span className="text-navy text-xs font-bold">TFE</span>
          </div>
          <div>
            <h1 className="font-serif text-base font-semibold text-white leading-tight">
              Guest Concierge
            </h1>
            <p className="text-xs text-gold-light/70">TFE Hotels — Demo</p>
          </div>
        </div>
      </header>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && !busy && (
          <div className="space-y-2 pt-2">
            <p className="text-xs text-stone-500 font-medium uppercase tracking-wide">
              Try asking&hellip;
            </p>
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="block w-full rounded-xl border border-stone-200 bg-white px-4 py-3 text-left text-sm text-stone-700 hover:border-navy/40 hover:bg-navy/5 transition-colors shadow-sm"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i}>
            {m.role === "user" ? (
              <div className="flex justify-end">
                <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-navy px-4 py-2.5 text-sm text-white leading-relaxed">
                  {m.content}
                </div>
              </div>
            ) : (
              <div className="flex justify-start">
                <div className="max-w-[85%]">
                  <div className="rounded-2xl rounded-bl-sm bg-white px-4 py-2.5 text-sm text-stone-800 leading-relaxed shadow-sm ring-1 ring-stone-100">
                    {m.content}
                  </div>
                  {m.metadata?.available_options && m.metadata.available_options.length > 0 && (
                    <OptionsGrid options={m.metadata.available_options} onSelect={selectOption} />
                  )}
                  {m.metadata?.booking_result && (
                    <BookingConfirmation
                      result={m.metadata.booking_result}
                      options={latestOptions}
                    />
                  )}
                </div>
              </div>
            )}
          </div>
        ))}

        {/* Streaming / typing state */}
        {busy && (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-2xl rounded-bl-sm bg-white px-4 py-2.5 text-sm text-stone-800 leading-relaxed shadow-sm ring-1 ring-stone-100">
              {streamingText || <TypingDots />}
            </div>
          </div>
        )}
      </div>

      {/* Disclosure */}
      <p className="px-4 py-1 text-center text-xs text-stone-400 flex-shrink-0">
        Demo on synthetic data &middot; bookings are mocked, no real reservations are made
      </p>

      {/* Input */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="px-4 pb-4 pt-2 flex-shrink-0"
      >
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy}
            placeholder="Ask about a property or start a booking&hellip;"
            className="flex-1 rounded-xl border border-stone-300 bg-white px-4 py-2.5 text-sm focus:border-navy focus:outline-none focus:ring-1 focus:ring-navy/30 disabled:opacity-50 shadow-sm"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-xl bg-navy px-5 py-2.5 text-sm font-medium text-white hover:bg-navy-light transition-colors disabled:opacity-40 shadow-sm"
          >
            Send
          </button>
        </div>
      </form>
    </main>
  );
}

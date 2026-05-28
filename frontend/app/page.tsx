"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

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
  image_url?: string;
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
// Helpers
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

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-AU", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function nightsCount(checkIn: string, checkOut: string) {
  return Math.round(
    (new Date(checkOut).getTime() - new Date(checkIn).getTime()) / 86_400_000
  );
}

// Amenity → emoji icon mapping
const AMENITY_ICONS: Record<string, string> = {
  pool: "🏊",
  gym: "🏋",
  spa: "💆",
  wifi: "📶",
  parking: "🅿️",
  restaurant: "🍽️",
  bar: "🍸",
  "pet-friendly": "🐾",
  pets: "🐾",
  beach: "🏖️",
  concierge: "🛎️",
  laundry: "👕",
  "room service": "🛎️",
  "air conditioning": "❄️",
  "rooftop terrace": "🌇",
  terrace: "🌇",
};

function amenityIcon(amenity: string) {
  const key = Object.keys(AMENITY_ICONS).find((k) =>
    amenity.toLowerCase().includes(k)
  );
  return key ? AMENITY_ICONS[key] : "✓";
}

function StarRating({ rating }: { rating: number }) {
  const full = Math.floor(rating);
  const half = rating - full >= 0.5;
  return (
    <span className="flex items-center gap-0.5 text-gold text-sm">
      {Array.from({ length: 5 }).map((_, i) => (
        <span key={i}>
          {i < full ? "★" : i === full && half ? "½" : "☆"}
        </span>
      ))}
    </span>
  );
}

function ScoreBadge({ score }: { score: number }) {
  const label = score >= 9 ? "Exceptional" : score >= 8 ? "Excellent" : score >= 7 ? "Very Good" : "Good";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="rounded bg-navy px-1.5 py-0.5 text-xs font-bold text-white">
        {score.toFixed(1)}
      </span>
      <span className="text-xs text-stone-500">{label}</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// PropertyCard — Booking.com style
// ---------------------------------------------------------------------------

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
  const basePrice = option.price_per_night;
  const discountedPrice =
    bestOffer && basePrice ? basePrice * (1 - bestOffer.discount_pct / 100) : basePrice;
  const savings = bestOffer && basePrice ? basePrice - (discountedPrice ?? basePrice) : 0;
  const topAmenities = (option.amenities ?? []).slice(0, 5);
  const rating = option.rating ?? 4.0;
  const reviewScore = Math.min(10, rating * 2);

  const brand = option.name.toLowerCase();
  const gradientClass = brand.includes("vibe")
    ? "from-teal-500 to-teal-800"
    : brand.includes("adina")
    ? "from-purple-500 to-purple-900"
    : "from-navy to-navy-light";

  const hasDateInfo = option.check_in && option.check_out;

  return (
    <div className="w-72 flex-shrink-0 rounded-2xl overflow-hidden border border-stone-200 bg-white shadow-md hover:shadow-lg transition-shadow">
      {/* Image / header */}
      <div className={`relative h-40 bg-gradient-to-br ${gradientClass}`}>
        {option.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={option.image_url}
            alt={option.name}
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center opacity-10">
            <svg viewBox="0 0 64 64" fill="white" className="w-24 h-24">
              <rect x="8" y="20" width="48" height="36" rx="2" />
              <rect x="16" y="4" width="32" height="16" rx="2" />
              <rect x="24" y="36" width="16" height="20" rx="1" />
              {[16, 28, 40].map((x) => (
                <rect key={x} x={x} y="26" width="8" height="8" rx="1" />
              ))}
            </svg>
          </div>
        )}
        {bestOffer && (
          <div className="absolute top-3 left-3">
            <span className="rounded-full bg-gold px-2.5 py-1 text-xs font-semibold text-navy shadow">
              -{bestOffer.discount_pct}% {bestOffer.name}
            </span>
          </div>
        )}
        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent p-3">
          <h3 className="font-serif text-base font-bold text-white leading-tight">
            {option.name}
          </h3>
        </div>
      </div>

      {/* Body */}
      <div className="p-4 space-y-3">
        {/* Rating + score */}
        <div className="flex items-center justify-between">
          <StarRating rating={rating} />
          <ScoreBadge score={reviewScore} />
        </div>

        {/* Location */}
        <div className="flex items-start gap-1.5 text-xs text-stone-500">
          <span className="mt-0.5">📍</span>
          <span>{[option.neighbourhood, option.city].filter(Boolean).join(", ")}</span>
        </div>

        {/* Stay info */}
        {hasDateInfo && (
          <div className="rounded-lg bg-stone-50 border border-stone-100 px-3 py-2 text-xs text-stone-600 flex items-center gap-2">
            <span>🗓️</span>
            <span>
              {formatDate(option.check_in!)} → {formatDate(option.check_out!)}
              {" · "}
              {nightsCount(option.check_in!, option.check_out!)} nights
              {option.guests ? ` · ${option.guests} guest${option.guests !== 1 ? "s" : ""}` : ""}
            </span>
          </div>
        )}

        {/* Amenities */}
        {topAmenities.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {topAmenities.map((a) => (
              <span
                key={a}
                className="flex items-center gap-1 rounded-full bg-stone-100 px-2 py-0.5 text-xs text-stone-600"
              >
                <span>{amenityIcon(a)}</span>
                <span>{a}</span>
              </span>
            ))}
          </div>
        )}

        {/* Price */}
        {discountedPrice !== undefined && (
          <div className="border-t border-stone-100 pt-3">
            <div className="flex items-end justify-between">
              <div>
                {bestOffer && basePrice && (
                  <p className="text-xs line-through text-stone-400">
                    AUD {Math.round(basePrice)}/night
                  </p>
                )}
                <p className="text-xl font-bold text-navy leading-tight">
                  AUD {Math.round(discountedPrice)}
                  <span className="text-xs font-normal text-stone-500">/night</span>
                </p>
                {savings > 0 && (
                  <p className="text-xs text-emerald-600 font-medium">
                    You save AUD {Math.round(savings)}
                  </p>
                )}
              </div>
              <button
                onClick={() => onSelect(index)}
                className="rounded-xl bg-gold px-4 py-2.5 text-sm font-semibold text-navy hover:bg-gold-light transition-colors shadow-sm"
              >
                Select
              </button>
            </div>
            <p className="text-xs text-stone-400 mt-1">Includes taxes &amp; fees · Mocked demo</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// OptionsGrid
// ---------------------------------------------------------------------------

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
      <div className="flex gap-3 overflow-x-auto pb-3 px-1 scroll-smooth snap-x">
        {options.map((opt, i) => (
          <div key={opt.property_id} className="snap-start">
            <PropertyCard option={opt} index={i + 1} onSelect={onSelect} />
          </div>
        ))}
      </div>
      {options.length > 1 && (
        <p className="text-xs text-stone-400 text-center mt-1">
          ← Scroll to see all {options.length} options →
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// BookingConfirmation
// ---------------------------------------------------------------------------

function BookingConfirmation({
  result,
  options,
}: {
  result: BookingResult;
  options: HotelOption[];
}) {
  const hotel = options.find((o) => o.property_id === result.property_id);
  const hotelName = hotel?.name ?? result.property_id;
  const nights = nightsCount(result.check_in, result.check_out);

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
    <div className="mt-3 rounded-2xl border border-gold/40 bg-gradient-to-br from-gold/5 to-navy/5 overflow-hidden shadow-sm">
      {/* Header */}
      <div className="bg-navy px-4 py-3 flex items-center gap-2">
        <span className="text-gold text-lg">✓</span>
        <span className="text-sm font-semibold text-white">Booking Confirmed</span>
        <span className="ml-auto font-mono text-xs text-gold/80">{result.booking_id}</span>
      </div>

      {/* Body */}
      <div className="p-4 space-y-3">
        <p className="font-serif text-lg font-bold text-navy">{hotelName}</p>

        <div className="grid grid-cols-2 gap-2 text-sm">
          <div className="rounded-lg bg-white border border-stone-100 p-2.5">
            <p className="text-xs text-stone-400 mb-0.5">Check-in</p>
            <p className="font-semibold text-navy">{formatDate(result.check_in)}</p>
          </div>
          <div className="rounded-lg bg-white border border-stone-100 p-2.5">
            <p className="text-xs text-stone-400 mb-0.5">Check-out</p>
            <p className="font-semibold text-navy">{formatDate(result.check_out)}</p>
          </div>
        </div>

        <div className="flex items-center justify-between text-sm">
          <span className="text-stone-500">
            {nights} night{nights !== 1 ? "s" : ""} · {result.guests} guest{result.guests !== 1 ? "s" : ""}
          </span>
          <div className="text-right">
            <p className="text-xs text-stone-400">Total</p>
            <p className="text-lg font-bold text-navy">AUD {result.total_aud.toFixed(2)}</p>
          </div>
        </div>

        <button
          onClick={downloadICS}
          className="w-full rounded-xl border border-gold/50 py-2 text-sm font-medium text-gold hover:bg-gold/10 transition-colors flex items-center justify-center gap-2"
        >
          <span>📅</span> Add to Calendar (.ics)
        </button>

        <p className="text-center text-xs text-stone-400">
          A confirmation would be sent to your email (mocked demo)
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TypingDots
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

// ---------------------------------------------------------------------------
// Markdown renderer for assistant messages
// ---------------------------------------------------------------------------

function AssistantText({ content }: { content: string }) {
  return (
    <ReactMarkdown
      components={{
        p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
        strong: ({ children }) => <strong className="font-semibold text-navy">{children}</strong>,
        em: ({ children }) => <em className="text-stone-600">{children}</em>,
        ul: ({ children }) => <ul className="mt-1 mb-2 space-y-0.5 list-none">{children}</ul>,
        ol: ({ children }) => <ol className="mt-1 mb-2 space-y-0.5 list-decimal list-inside">{children}</ol>,
        li: ({ children }) => (
          <li className="flex items-start gap-1.5 text-sm">
            <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-gold" />
            <span>{children}</span>
          </li>
        ),
        h3: ({ children }) => <h3 className="font-serif font-semibold text-navy mb-1">{children}</h3>,
        code: ({ children }) => (
          <code className="rounded bg-stone-100 px-1 py-0.5 text-xs font-mono">{children}</code>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

// ---------------------------------------------------------------------------
// Suggestions
// ---------------------------------------------------------------------------

const SUGGESTIONS = [
  "What time is check-in at Vibe Sydney?",
  "Beach hotel in Sydney for 2 nights from 10 July 2026 — under $350/night with a gym.",
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

        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

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
            } catch { /* ignore malformed lines */ }
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
    [busy, messages, sessionId, latestOptions]
  );

  function selectOption(n: number) {
    send(`Option ${n}`);
  }

  return (
    <main className="mx-auto flex h-screen max-w-2xl flex-col">
      {/* Header */}
      <header className="bg-navy px-5 py-4 flex-shrink-0 shadow-md">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-full bg-gold flex items-center justify-center shadow">
            <span className="text-navy text-xs font-bold tracking-tight">TFE</span>
          </div>
          <div>
            <h1 className="font-serif text-base font-semibold text-white leading-tight">
              Guest Concierge
            </h1>
            <p className="text-xs text-gold-light/70">TFE Hotels · AI Demo</p>
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
                <div className="max-w-[90%] w-full">
                  <div className="rounded-2xl rounded-bl-sm bg-white px-4 py-3 text-sm text-stone-800 shadow-sm ring-1 ring-stone-100">
                    <AssistantText content={m.content} />
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

        {busy && (
          <div className="flex justify-start">
            <div className="max-w-[90%] rounded-2xl rounded-bl-sm bg-white px-4 py-3 text-sm text-stone-800 shadow-sm ring-1 ring-stone-100">
              {streamingText ? <AssistantText content={streamingText} /> : <TypingDots />}
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
        onSubmit={(e) => { e.preventDefault(); send(input); }}
        className="px-4 pb-4 pt-2 flex-shrink-0"
      >
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy}
            placeholder="Ask about a property or start a booking…"
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

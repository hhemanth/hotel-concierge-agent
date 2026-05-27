import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "TFE Guest Concierge",
  description: "Hotel concierge AI demo — synthetic data, mocked booking back-end.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

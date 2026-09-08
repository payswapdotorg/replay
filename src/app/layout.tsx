import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Replay Console",
  description: "Remote browser control console — live click / drag / typing replay",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}

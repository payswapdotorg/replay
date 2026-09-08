import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Replay — Live Browser Control Console",
  description:
    "Drive a real headless-display Chrome from a web page: live screenshot replay, click/type/scroll/drag forwarding, tab management, and an operator-to-agent message thread. Built with Next.js, CDP, Xvfb.",
  keywords: [
    "browser replay",
    "CDP",
    "Chrome DevTools Protocol",
    "Xvfb",
    "remote browser",
    "operator console",
    "Next.js",
  ],
  authors: [{ name: "payswap" }],
  icons: {
    icon: "/logo.svg",
  },
  openGraph: {
    title: "Replay — Live Browser Control Console",
    description: "Live browser replay and control from a single web page",
    url: "https://github.com/payswapdotorg/replay",
    siteName: "Replay",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "Replay — Live Browser Control Console",
    description: "Live browser replay and control from a single web page",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-background text-foreground`}
      >
        {children}
        <Toaster />
      </body>
    </html>
  );
}

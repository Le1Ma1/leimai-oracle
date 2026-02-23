import type { Metadata } from "next";

import "@/app/globals.css";

export const metadata: Metadata = {
  title: "Project Panopticon",
  description: "Crypto in-sample optimization library for global programmatic SEO.",
  icons: {
    icon: [
      { url: "/logo.png", sizes: "32x32", type: "image/png" },
      { url: "/logo.png", sizes: "192x192", type: "image/png" }
    ],
    apple: [{ url: "/logo.png", sizes: "180x180", type: "image/png" }]
  }
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LEIMAI ORACLE | Quant Monitor",
  description: "Dual-persona governance dashboard for Phase 1 meta-label baseline."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

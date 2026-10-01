import type { Metadata } from "next";
import { Suspense } from "react";
import localFont from "next/font/local";
import { WorkspaceProvider } from "@/components/workspace/workspace-state";
import { brand } from "@/lib/brand";
import "./globals.css";
import "./engineering.css";

const plexSans = localFont({
  src: "./fonts/ibm-plex-sans-variable.ttf",
  display: "swap",
  weight: "100 700",
  variable: "--font-plex-sans",
});

const manrope = localFont({
  src: "./fonts/manrope-variable.ttf",
  display: "swap",
  weight: "200 800",
  variable: "--font-manrope",
});

export const metadata: Metadata = {
  title: brand.title,
  description: brand.description,
  icons: { icon: brand.logo, apple: brand.logo },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" className={`${plexSans.variable} ${manrope.variable}`}>
      <body>
        <Suspense fallback={<p role="status">Загрузка…</p>}><WorkspaceProvider>{children}</WorkspaceProvider></Suspense>
      </body>
    </html>
  );
}

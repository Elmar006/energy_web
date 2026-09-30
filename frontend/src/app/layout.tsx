import type { Metadata } from "next";
import { Suspense } from "react";
import localFont from "next/font/local";
import { WorkspaceProvider } from "@/components/workspace/workspace-state";
import "./globals.css";
import "./engineering.css";

const onest = localFont({
  src: "../../public/onest-variable.ttf",
  display: "swap",
  weight: "100 900",
  variable: "--font-onest",
});

export const metadata: Metadata = {
  title: "EV Infrastructure — планирование зарядной инфраструктуры",
  description:
    "Сценарное планирование зарядной инфраструктуры с ограничениями электросети",
  icons: { icon: "/icon.svg" },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" className={onest.variable}>
      <body>
        <Suspense fallback={<p role="status">Открываем рабочее пространство…</p>}><WorkspaceProvider>{children}</WorkspaceProvider></Suspense>
      </body>
    </html>
  );
}

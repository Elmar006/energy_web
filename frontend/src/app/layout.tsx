import type { Metadata } from "next";
import localFont from "next/font/local";
import { WorkspaceProvider } from "@/components/workspace/workspace-state";
import "./globals.css";

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
        <WorkspaceProvider>{children}</WorkspaceProvider>
      </body>
    </html>
  );
}

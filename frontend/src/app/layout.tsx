import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "EV Infrastructure — планирование зарядной инфраструктуры",
  description: "Сценарное планирование зарядной инфраструктуры с ограничениями электросети",
  icons: { icon: "/brand-logo.png" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ru"><body>{children}</body></html>;
}

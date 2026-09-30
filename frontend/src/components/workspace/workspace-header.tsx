"use client";

import Image from "next/image";
import Link from "next/link";
import { LogOut, PanelsTopLeft, Database, Route, Network } from "lucide-react";

type View = "plan" | "data" | "mobility" | "models";

const navigation = [
  { id: "plan", href: "/plan", label: "Планирование", shortLabel: "План", icon: PanelsTopLeft },
  { id: "data", href: "/data/scenario", label: "Данные и версии", shortLabel: "Данные", icon: Database },
  { id: "mobility", href: "/mobility", label: "Маршруты", shortLabel: "Поездки", icon: Route },
  { id: "models", href: "/models/corridor", label: "Отдельные модели", shortLabel: "Модели", icon: Network },
];

export default function WorkspaceHeader({
  view,
  scenarioId,
  onLogout,
}: {
  view: View;
  scenarioId?: string;
  onLogout: () => Promise<void>;
}) {
  const query = scenarioId ? `?scenario=${scenarioId}` : "";

  return (
    <aside className="workspace-rail">
      <a className="skip-link" href="#workspace-main">К содержимому</a>
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark small">
            <Image src="/icon.svg" width={34} height={34} alt="" />
          </span>
          <strong>EV Infrastructure</strong>
        </div>
      </header>
      <p className="rail-label">Рабочее пространство</p>
      <nav className="app-nav" aria-label="Разделы рабочего пространства">
        {navigation.map(({ id, href, label, shortLabel, icon: Icon }) => (
          <Link
            key={id}
            href={href + query}
            className={view === id ? "active" : ""}
            aria-current={view === id ? "page" : undefined}
            aria-label={label}
          >
            <Icon size={18} aria-hidden="true" /><span className="nav-label-desktop" aria-hidden="true">{label}</span><span className="nav-label-mobile" aria-hidden="true">{shortLabel}</span>
          </Link>
        ))}
      </nav>
      <div className="rail-foot"><span>EV Infrastructure</span><p>Планирование зарядной сети</p></div>
      <div className="rail-account"><span><span className="account-monogram" aria-hidden="true">EV</span><span>Рабочая сессия<small>Общий доступ</small></span></span><button type="button" className="logout-button" onClick={() => void onLogout()} title="Выйти" aria-label="Выйти из рабочего пространства"><LogOut size={16} aria-hidden="true" /></button></div>
    </aside>
  );
}

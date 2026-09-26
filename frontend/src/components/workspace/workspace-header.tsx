"use client";

import Image from "next/image";
import Link from "next/link";
import { LogOut } from "lucide-react";

type View = "plan" | "data" | "mobility" | "models";

const navigation: { id: View; href: string; label: string }[] = [
  { id: "plan", href: "/plan", label: "Планирование" },
  { id: "data", href: "/data/scenario", label: "Данные и версии" },
  { id: "mobility", href: "/mobility", label: "Маршруты" },
  { id: "models", href: "/models/corridor", label: "Отдельные модели" },
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
    <>
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark small">
            <Image src="/icon.svg" width={34} height={34} alt="" />
          </span>
          <strong>EV Infrastructure</strong>
          <span className="brand-divider" />
          <span className="brand-caption">Планирование инфраструктуры</span>
        </div>
        <div className="header-status">
          <span className="status-pulse" aria-hidden="true" />
          <span className="header-status-label">Демо-доступ</span>
          <button
            type="button"
            className="logout-button"
            onClick={() => void onLogout()}
            aria-label="Выйти из рабочего пространства"
            title="Выйти"
          >
            <LogOut size={16} />
          </button>
        </div>
      </header>
      <nav className="app-nav" aria-label="Разделы рабочего пространства">
        {navigation.map(({ id, href, label }) => (
          <Link
            key={id}
            href={href + query}
            className={view === id ? "active" : ""}
            aria-current={view === id ? "page" : undefined}
          >
            {label}
          </Link>
        ))}
      </nav>
    </>
  );
}

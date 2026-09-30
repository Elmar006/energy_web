"use client";

import { useState } from "react";
import { Search, MapPin } from "lucide-react";
import type { PlanningSpec } from "@/lib/planning";
import type { Optimization, Explanation } from "./result-model";

const provenanceLabels: Record<string, string> = { observed: "Наблюдение", derived: "Расчёт", assumed: "Допущение" };

export default function Territory({ spec, plan, explanations, scenario, selectedSite, onSelect }: {
  spec: PlanningSpec; plan?: Optimization; explanations?: Explanation[]; scenario: string;
  selectedSite?: string; onSelect?: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [localSite, setLocalSite] = useState("");
  const id = selectedSite ?? localSite;
  const site = spec.sites.find(s => s.id === id);
  const selected = plan?.selected.find(s => s.site_id === id);
  const explanation = explanations?.find(s => s.site_id === id);
  const lost = explanation?.lost_served_kwh?.[scenario];
  const rows = spec.sites.filter(s => `${s.name} ${s.id}`.toLocaleLowerCase("ru").includes(query.toLocaleLowerCase("ru")));
  const raw = site as (typeof site & { grid_node_id?: string; max_connection_kw?: number });
  return <div className="territory-workspace">
    <div><div className="table-toolbar"><h3>Реестр площадок <span>{spec.sites.length}</span></h3><label className="search-field"><Search size={15} aria-hidden="true" /><input aria-label="Поиск площадки" placeholder="Найти площадку" value={query} onChange={e => setQuery(e.target.value)} /></label></div>
      <div className="data-table-scroll" tabIndex={0} role="region" aria-label="Площадки территории"><table className="data-table"><thead><tr><th scope="col">Площадка</th><th scope="col">Решение</th><th scope="col">Ввод</th><th scope="col">Данные</th></tr></thead><tbody>
        {rows.map(s => { const decision = plan?.selected.find(x => x.site_id === s.id); return <tr key={s.id} className={s.id === id ? "selected-row" : ""}><th scope="row"><button type="button" className="table-link" aria-pressed={s.id === id} onClick={() => { setLocalSite(s.id); onSelect?.(s.id); }}>{s.name}</button></th><td>{decision ? decision.option_id.toUpperCase() : plan ? "Не выбрана" : "Кандидат"}</td><td>{decision?.year ?? "—"}</td><td>{provenanceLabels[s.provenance?.kind ?? ""] ?? "Не указано"}</td></tr>; })}
      </tbody></table>{!rows.length && <p className="empty-table">Площадки не найдены. Измените запрос.</p>}</div>
    </div>
    <aside className="site-inspector" aria-label="Свойства площадки" aria-live="polite">
      {site ? <><span className="context-kicker">Свойства объекта</span><h3>{site.name}</h3><dl><div><dt>Решение</dt><dd>{selected ? `${selected.option_id.toUpperCase()} · ${selected.year}` : plan ? "Не включена в план" : "Кандидат"}</dd></div><div><dt>Координаты</dt><dd>{site.latitude.toFixed(5)}, {site.longitude.toFixed(5)}</dd></div><div><dt>Узел подключения</dt><dd>{raw?.grid_node_id ?? "Не указан"}</dd></div><div><dt>Происхождение</dt><dd>{provenanceLabels[site.provenance?.kind ?? ""] ?? "Не указано"}</dd></div></dl><p>{site.provenance?.source || "Источник не указан"}</p>{explanation && <div className="inspector-explanation"><strong>Почему выбрана</strong><p>{explanation.status === "fixed" ? "Площадка закреплена во входных условиях." : lost === undefined ? "Недостаточно данных для объяснения." : lost >= 0.5 ? `Исключение уменьшает обслуживание на ${new Intl.NumberFormat("ru").format(Math.round(lost))} кВт·ч.` : "При пересчёте без объекта спрос может обслуживаться другими площадками. Выбор также зависит от стоимости и других ограничений."}</p></div>}</> : <div className="inspector-empty"><MapPin size={22} aria-hidden="true" /><h3>Выберите площадку</h3><p>Откройте строку таблицы или объект на карте, чтобы увидеть решение и источник данных.</p></div>}
    </aside>
  </div>;
}

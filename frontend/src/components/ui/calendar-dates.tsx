"use client";

import { useState } from "react";
import { Plus, X } from "lucide-react";

export default function CalendarDates({ dates, onChange }: { dates: string[]; onChange: (dates: string[]) => void }) {
  const [next, setNext] = useState("");
  const sorted = [...new Set(dates)].sort();
  const gaps = sorted.some((date, index) => index > 0 && Date.parse(date + "T00:00:00Z") - Date.parse(sorted[index - 1] + "T00:00:00Z") !== 86400000);
  return <fieldset className="calendar-dates"><legend>Даты расчёта</legend><div className="calendar-add"><label className="wb-field"><span>Добавить дату</span><input type="date" value={next} onChange={event => setNext(event.target.value)} /></label><button type="button" className="secondary-button compact-button" disabled={!next || sorted.includes(next) || sorted.length >= 14} onClick={() => { onChange([...sorted, next].sort()); setNext(""); }}><Plus size={15} aria-hidden="true" />Добавить</button></div>
    <div className="date-chips">{sorted.map(date => <span key={date}>{date}<button type="button" className="icon-button" aria-label={`Убрать дату ${date}`} onClick={() => onChange(sorted.filter(value => value !== date))}><X size={13} /></button></span>)}</div>
    <p className="wb-help">{sorted.length ? `Выбрано дней: ${sorted.length} из 14.` : "Выберите от 1 до 14 последовательных дней."}{gaps ? " Между датами есть пропуски — добавьте недостающие дни." : ""}</p>
  </fieldset>;
}

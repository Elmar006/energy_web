"use client";

import { Plus, Trash2, Undo2 } from "lucide-react";
import { useState } from "react";

export type Column = { key: string; label: string; type?: "number" | "boolean"; optional?: boolean; min?: number; max?: number; step?: number; options?: string[] };
export type RecordRow = Record<string, unknown>;

export default function ObjectTable({ label, columns, rows, onChange }: { label: string; columns: Column[]; rows: RecordRow[]; onChange: (rows: RecordRow[]) => void }) {
  const [removed, setRemoved] = useState<{ row: RecordRow; index: number } | null>(null);
  function update(index: number, column: Column, value: unknown) {
    onChange(rows.map((row, i) => { if (i !== index) return row; const next = { ...row }; if (value === undefined) delete next[column.key]; else next[column.key] = value; return next; }));
  }
  return <section className="object-table"><div className="table-toolbar"><h3>{label} <span>{rows.length}</span></h3><button type="button" className="secondary-button compact-button" onClick={() => onChange([...rows, Object.fromEntries(columns.filter(c => c.type === "boolean").map(c => [c.key, true]))])}><Plus size={15} aria-hidden="true" />Добавить строку</button></div>
    {!rows.length ? <p className="empty-table">Нет записей. Добавьте строку и заполните параметры.</p> : <div className="data-table-scroll" tabIndex={0} role="region" aria-label={label}><table className="data-table editable-table"><thead><tr>{columns.map(c => <th scope="col" key={c.key}>{c.label}{c.optional ? " · необяз." : ""}</th>)}<th scope="col"><span className="sr-only">Действия</span></th></tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{columns.map(c => <td key={c.key}>{c.type === "boolean" ? <input type="checkbox" aria-label={`${c.label}, строка ${i + 1}`} checked={row[c.key] === undefined ? true : Boolean(row[c.key])} onChange={e => update(i, c, e.target.checked)} /> : c.options ? <select aria-label={`${c.label}, строка ${i + 1}`} value={String(row[c.key] ?? "")} onChange={e => update(i, c, e.target.value)}><option value="">Выберите</option>{c.options.map(value => <option key={value}>{value}</option>)}</select> : <input aria-label={`${c.label}, строка ${i + 1}`} type={c.type ?? "text"} step={c.step ?? "any"} min={c.min} max={c.max} value={String(row[c.key] ?? "")} onChange={e => update(i, c, e.target.value === "" ? undefined : c.type === "number" ? e.target.valueAsNumber : e.target.value)} />}</td>)}<td><button type="button" className="icon-button" aria-label={`Удалить строку ${i + 1} из ${label}`} onClick={() => { setRemoved({ row, index: i }); onChange(rows.filter((_, j) => i !== j)); }}><Trash2 size={15} /></button></td></tr>)}</tbody></table></div>}
    {removed && <div className="undo-row" role="status">Строка удалена из черновика.<button type="button" className="text-button" onClick={() => { const next = [...rows]; next.splice(Math.min(removed.index, next.length), 0, removed.row); onChange(next); setRemoved(null); }}><Undo2 size={14} aria-hidden="true" />Восстановить</button></div>}
  </section>;
}

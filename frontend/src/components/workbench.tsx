"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Download, Info, RefreshCw } from "lucide-react";
import type { PlanningSpec } from "@/lib/planning";
import ScenarioFields from "@/components/scenario-fields";
import { DatedFields, MobilityFields } from "@/components/demand-fields";
import ModelFields from "@/components/model-fields";

type Scenario = { id: string; name: string; spec: PlanningSpec; sha256?: string };
type Dataset = { id: string; name: string; source: string; kind: string; checksum: string; format: string; role?: string };
type Props = { view: "data" | "mobility" | "models"; spec: PlanningSpec; scenario: Scenario | null; onSaved: (scenario: Scenario) => void };
type Obj = Record<string, unknown>;
const pretty = (value: unknown) => JSON.stringify(value, null, 2);
const roles = [["demand_zones", "Зоны спроса"], ["candidate_sites", "Площадки"], ["grid_nodes", "Узлы сети"], ["travel_edges", "Дорожные связи"]] as const;

async function api(path: string, init?: RequestInit) {
  const response = await fetch("/api/workbench/" + path, { ...init, cache: "no-store" });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : body?.error || "HTTP " + response.status);
  return body;
}
function JsonEditor({ label, value, setValue, rows = 12 }: { label: string; value: string; setValue: (text: string) => void; rows?: number }) {
  return <label className="wb-field"><span>{label}</span><textarea rows={rows} spellCheck={false} value={value} onChange={(event) => setValue(event.target.value)} /></label>;
}

export default function Workbench({ view, spec, scenario, onSaved }: Props) {
  const [section, setSection] = useState<"editor" | "csv" | "geo" | "dated">("editor");
  const [name, setName] = useState("Новый сценарий");
  const [source, setSource] = useState("");
  const [datasetName, setDatasetName] = useState("");
  const [kind, setKind] = useState("assumed");
  const [license, setLicense] = useState("");
  const [timeZone, setTimeZone] = useState("Europe/Moscow");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [coverage, setCoverage] = useState(false);
  const [csvType, setCsvType] = useState<"sessions" | "grid-headroom">("sessions");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [geoFile, setGeoFile] = useState<File | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [versions, setVersions] = useState<Record<string, string>>({});
  const [specJson, setSpecJson] = useState(pretty(spec));
  const [optionsJson, setOptionsJson] = useState(pretty((spec as unknown as Obj).options || []));
  const [parametersJson, setParametersJson] = useState(pretty(spec.parameters));
  const [scenariosJson, setScenariosJson] = useState(pretty(spec.scenarios));
  const [mobilityJson, setMobilityJson] = useState(pretty({ schema_version: "mobility-v1", time_zone: "Europe/Moscow", covered_dates: [], replace_zone_ids: [], source: "", source_kind: "assumed", vehicles: [] }));
  const [datedJson, setDatedJson] = useState(pretty({ schema_version: "demand-dataset-v1", service_calendar: {}, charging_requests: [] }));
  const [model, setModel] = useState<"corridors/check" | "fleets/schedule">("corridors/check");
  const [modelJson, setModelJson] = useState("{}");
  const [preview, setPreview] = useState<Obj | null>(null);
  const [previewPayload, setPreviewPayload] = useState<Obj | null>(null);
  const [modelResult, setModelResult] = useState<unknown>(null);
  const [accessToken, setAccessToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => { if (view === "data" && section === "geo") void reloadDatasets(); }, [view, section]);

  async function reloadDatasets() {
    try { setDatasets(await api("datasets")); } catch (caught) { setError(caught instanceof Error ? caught.message : "Список недоступен"); }
  }
  async function perform(action: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); } catch (caught) { setPreview(null); setPreviewPayload(null); setError(caught instanceof Error ? caught.message : "Операция не выполнена"); }
    finally { setBusy(false); }
  }
  async function saveScenario(input: unknown) {
    const response = await fetch("/api/scenarios", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, spec: input }) });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "Сценарий не сохранён");
    onSaved(body); setMessage("Сохранён новый неизменяемый сценарий: " + body.name);
  }
  const jsonHeaders = { "Content-Type": "application/json" };
  const builder = () => ({
    name, input_id: "input-" + Date.now(), time_zone: timeZone,
    dataset_versions: versions, options: JSON.parse(optionsJson), parameters: JSON.parse(parametersJson), scenarios: JSON.parse(scenariosJson),
  });
  const metadata = <div className="wb-fields">
    <label className="wb-field"><span>Имя нового сценария</span><input value={name} onChange={(event) => setName(event.target.value)} maxLength={120} /></label>
    <label className="wb-field"><span>Название набора</span><input value={datasetName} onChange={(event) => setDatasetName(event.target.value)} /></label>
    <label className="wb-field"><span>Источник и основание</span><input value={source} onChange={(event) => setSource(event.target.value)} /></label>
    <label className="wb-field"><span>Происхождение</span><select value={kind} onChange={(event) => setKind(event.target.value)}><option value="assumed">Сценарное допущение</option><option value="derived">Вычислено</option><option value="observed">Заявлено как наблюдение</option></select></label>
    <label className="wb-field"><span>Условия использования</span><input value={license} onChange={(event) => setLicense(event.target.value)} /></label>
  </div>;

  return <section className="workbench">
    <div className="wb-heading"><div><p className="eyebrow">РАБОЧИЕ ИНСТРУМЕНТЫ</p><h2>{view === "data" ? "Источники и сценарии" : view === "mobility" ? "Потенциальный спрос из маршрутов" : "Отдельные модели"}</h2></div><span>Версионированные входы · проверяемые результаты</span></div>
    {view === "data" && <>
      <div className="wb-tabs" role="tablist" aria-label="Способ подготовки данных">{([["editor", "Сценарий"], ["csv", "CSV сессий и сети"], ["geo", "Геоданные"], ["dated", "Датированный спрос"]] as const).map(([id, label]) => <button key={id} role="tab" aria-selected={section === id} className={section === id ? "active" : ""} onClick={() => { setSection(id); setPreview(null); setPreviewPayload(null); }}>{label}</button>)}</div>
      {section === "editor" && <div className="wb-body"><p className="wb-note"><Info size={17} /> Полный PlanningInput. Отредактируйте значения и происхождение; сервер проверит контракт и создаст новый неизменяемый снимок.</p><label className="wb-field"><span>Имя новой версии</span><input value={name} onChange={(event) => setName(event.target.value)} /></label><ScenarioFields value={specJson} onChange={setSpecJson} /><details className="wb-advanced"><summary>Полный JSON · оборудование, цены и дополнительные ограничения</summary><JsonEditor label="PlanningInput JSON · кВт, кВт·ч, минуты, ₽" value={specJson} setValue={setSpecJson} rows={22} /></details><div className="wb-actions"><button className="primary-button" disabled={busy || !name.trim()} onClick={() => void perform(() => saveScenario(JSON.parse(specJson)))}>Сохранить версию <ArrowRight size={17} /></button><button className="secondary-button" onClick={() => setSpecJson(pretty(spec))}>Вернуть выбранный вход</button></div></div>}
      {section === "csv" && <div className="wb-body"><p className="wb-note"><Info size={17} /> CSV применяется к выбранному сохранённому сценарию и создаёт новый. Метка «наблюдалось» задаётся поставщиком.</p><div className="wb-segment"><button className={csvType === "sessions" ? "active" : ""} onClick={() => setCsvType("sessions")}>Выполненные зарядки</button><button className={csvType === "grid-headroom" ? "active" : ""} onClick={() => setCsvType("grid-headroom")}>Резерв сети</button></div><p className="wb-help">Родитель: <strong>{scenario?.name || "сначала сохраните сценарий"}</strong>. {csvType === "sessions" ? "Зоны: " + spec.zones.map((item) => item.id).join(", ") + ". CSV: session_id,zone_id,started_at,ended_at,energy_kwh. История не раскрывает скрытый спрос." : "Узлы: " + spec.grid_nodes.map((item) => item.id).join(", ") + ". CSV: grid_node_id,hour,headroom_kw; все часы 0–23."}</p>{metadata}<div className="wb-fields"><label className="wb-field"><span>Часовой пояс IANA</span><input value={timeZone} onChange={(event) => setTimeZone(event.target.value)} /></label><label className="wb-field"><span>{csvType === "sessions" ? "Начало периода" : "Дата профиля"}</span><input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>{csvType === "sessions" && <label className="wb-field"><span>Конец периода</span><input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>}</div>{csvType === "sessions" && <label className="wb-check"><input type="checkbox" checked={coverage} onChange={(event) => setCoverage(event.target.checked)} /> Подтверждаю полноту выгрузки по всем зонам и дням; пустые дни означают ноль сессий</label>}<label className="wb-field"><span>Исходный CSV · до {csvType === "sessions" ? 50 : 10} МиБ</span><input type="file" accept=".csv,text/csv" onChange={(event) => setCsvFile(event.target.files?.[0] || null)} /></label><button className="primary-button" disabled={busy || !scenario || !csvFile || !name.trim() || !source.trim() || !datasetName.trim() || !dateFrom || (csvType === "sessions" && !dateTo)} onClick={() => void perform(async () => { if (!scenario || !csvFile) return; const form = new FormData(); Object.entries({ scenario_name: name, dataset_name: datasetName, source, kind, time_zone: timeZone, license, ...(csvType === "sessions" ? { start_date: dateFrom, end_date: dateTo, coverage_complete: String(coverage) } : { profile_date: dateFrom }) }).forEach(([key, value]) => { if (value) form.set(key, value); }); form.set("file", csvFile); const body = await api("scenarios/" + scenario.id + "/imports/" + csvType, { method: "POST", body: form }); onSaved(body.scenario); setMessage("Новый снимок: " + body.scenario.name + " · SHA-256 " + body.sha256); await reloadDatasets(); })}>Импортировать и создать снимок <ArrowRight size={17} /></button><DatasetList datasets={datasets.filter((item) => item.format === "csv")} /></div>}
      {section === "geo" && <div className="wb-body"><p className="wb-note"><Info size={17} /> Четыре GeoJSON FeatureCollection: demand_zone, candidate_site, grid_node и travel_edge. Числа берутся из свойств объектов, а не из карты.</p>{metadata}<div className="wb-fields"><label className="wb-field"><span>Дата наблюдения · обязательна для observed</span><input type="datetime-local" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label><label className="wb-field"><span>GeoJSON · до 50 МиБ</span><input type="file" accept=".json,.geojson,application/geo+json" onChange={(event) => setGeoFile(event.target.files?.[0] || null)} /></label><label className="wb-field"><span>Часовой пояс IANA</span><input value={timeZone} onChange={(event) => setTimeZone(event.target.value)} /></label></div><div className="wb-actions"><button className="secondary-button" disabled={busy || !geoFile || !source.trim() || !datasetName.trim() || (kind === "observed" && !dateFrom)} onClick={() => void perform(async () => { if (!geoFile) return; const form = new FormData(); form.set("file", geoFile); form.set("name", datasetName); form.set("source", source); form.set("kind", kind); if (license) form.set("license", license); if (dateFrom) form.set("captured_at", new Date(dateFrom).toISOString()); const body = await api("datasets/import", { method: "POST", body: form }); setMessage("Слой " + body.dataset_id + " · " + body.features + " объектов · SHA-256 " + body.sha256); await reloadDatasets(); })}>Загрузить слой</button><button className="text-button" onClick={() => void reloadDatasets()}><RefreshCw size={15} /> Обновить версии</button></div><div className="wb-roles">{roles.map(([role, label]) => <label className="wb-field" key={role}><span>{label}</span><select value={versions[role] || ""} onChange={(event) => setVersions((current) => ({ ...current, [role]: event.target.value }))}><option value="">Выберите UUID версии</option>{datasets.filter((item) => item.format === "geojson").map((item) => <option key={item.id} value={item.id}>{item.name} · {item.id.slice(0, 8)} · {item.kind}</option>)}</select></label>)}</div><JsonEditor label="Варианты оборудования · JSON" value={optionsJson} setValue={setOptionsJson} rows={7} /><JsonEditor label="Параметры · JSON" value={parametersJson} setValue={setParametersJson} rows={10} /><JsonEditor label="Сценарии неопределённости · JSON" value={scenariosJson} setValue={setScenariosJson} rows={6} /><div className="wb-actions"><button className="secondary-button" disabled={busy || roles.some(([role]) => !versions[role])} onClick={() => void perform(async () => { const payload = builder(); setPreviewPayload(payload); setPreview(await api("scenarios/from-datasets/preview", { method: "POST", headers: jsonHeaders, body: pretty(payload) })); })}>Проверить сборку</button><button className="primary-button" disabled={busy || !preview || !previewPayload} onClick={() => void perform(async () => { const body = await api("scenarios/from-datasets", { method: "POST", headers: jsonHeaders, body: pretty(previewPayload) }); onSaved(body.scenario); setPreview(null); setMessage("Сохранён сценарий: " + body.scenario.name); })}>Сохранить сценарий <ArrowRight size={17} /></button></div>{preview && <div className="wb-preview"><strong>Качество исходных данных</strong><pre>{pretty(preview.data_quality)}</pre></div>}<DatasetList datasets={datasets.filter((item) => item.format === "geojson")} /></div>}
      {section === "dated" && <div className="wb-body"><p className="wb-note"><Info size={17} /> Календарь: 1–14 последовательных дней, явные зоны заявок и типового профиля. Экономика короткого периода масштабируется заданным annualization_factor.</p><DatedFields value={datedJson} onChange={setDatedJson} zones={spec.zones.map((item) => item.id)} /><details className="wb-advanced"><summary>Заявки и календарь · полный JSON</summary><JsonEditor label="demand-dataset-v1 · service_calendar и charging_requests" value={datedJson} setValue={setDatedJson} rows={22} /></details><button className="primary-button" disabled={busy} onClick={() => void perform(async () => { const input = JSON.parse(datedJson); if (input.schema_version !== "demand-dataset-v1") throw new Error("Нужен schema_version=demand-dataset-v1"); const manifest = await api("artifacts/demand", { method: "POST", headers: jsonHeaders, body: datedJson }); const next = { ...spec, demand_dataset: manifest } as Obj; delete next.service_calendar; delete next.charging_requests; setSpecJson(pretty(next)); setSection("editor"); setMessage("Артефакт " + manifest.artifact_id + " добавлен в редактор. Сохраните новую версию."); })}>Загрузить набор и открыть редактор <ArrowRight size={17} /></button></div>}
    </>}
    {view === "mobility" && <div className="wb-body"><p className="wb-note"><Info size={17} /> Потенциальные заявки из переданных маршрутов. Публичная зарядка условно учтена при проверке возможности последующих поездок; репрезентативность маршрутов подтверждает поставщик.</p><p className="wb-help">Зоны: {spec.zones.map((item) => item.id).join(", ")}. Время с UTC-смещением, расстояние в км, энергия в кВт·ч. Укажите covered_dates, replace_zone_ids, источник, машины и активности.</p><MobilityFields value={mobilityJson} onChange={setMobilityJson} zones={spec.zones.map((item) => item.id)} /><details className="wb-advanced"><summary>Машины, поездки и стоянки · полный JSON</summary><JsonEditor label="MobilityInput JSON" value={mobilityJson} setValue={setMobilityJson} rows={24} /></details><label className="wb-field"><span>Имя сохраняемого сценария</span><input value={name} onChange={(event) => setName(event.target.value)} /></label><div className="wb-actions"><button className="secondary-button" disabled={busy} onClick={() => void perform(async () => { const payload = { input: spec, mobility: JSON.parse(mobilityJson) }; setPreviewPayload(payload); setPreview(await api("scenarios/from-mobility/preview", { method: "POST", headers: jsonHeaders, body: pretty(payload) })); })}>Рассчитать предварительный спрос</button><button className="primary-button" disabled={busy || !preview || !previewPayload || !name.trim()} onClick={() => void perform(async () => { const body = await api("scenarios/from-mobility", { method: "POST", headers: jsonHeaders, body: pretty({ name, ...previewPayload }) }); onSaved(body.scenario); setAccessToken(body.source_access_token); setMessage("Сохранён источник маршрутов: SHA-256 " + body.source_sha256); })}>Сохранить источник и сценарий <ArrowRight size={17} /></button></div>{preview && <div className="wb-preview"><strong>Предпросмотр · {Array.isArray(preview.requests) ? preview.requests.length : 0} заявок</strong><p>Планировщик использует датированные окна; почасовой ряд служит контрольной сводкой.</p><pre>{pretty({ audit: preview.audit, requests: preview.requests, source_sha256: preview.source_sha256 })}</pre></div>}{accessToken && <div className="wb-secret"><strong>Одноразовый ключ к исходным маршрутам</strong><p>Сохраните его сейчас. Повторно получить ключ нельзя; не вставляйте его в URL.</p><code>{accessToken}</code><button className="secondary-button" onClick={() => void navigator.clipboard.writeText(accessToken)}>Скопировать</button></div>}</div>}
    {view === "models" && <div className="wb-body"><p className="wb-note"><Info size={17} /> Модели коридора и парка работают отдельно от городского плана и требуют собственных входов. Общие посты и бюджет между ними не распределяются.</p><div className="wb-segment"><button className={model === "corridors/check" ? "active" : ""} onClick={() => { setModel("corridors/check"); setModelJson("{}"); setModelResult(null); }}>Коридор</button><button className={model === "fleets/schedule" ? "active" : ""} onClick={() => { setModel("fleets/schedule"); setModelJson("{}"); setModelResult(null); }}>Парк</button></div><p className="wb-help">{model === "corridors/check" ? "Передайте CorridorSpec с маршрутом, энергетикой машины и станциями." : "Передайте FleetSpec с назначенными рейсами, окнами зарядки, батареями и лимитами депо."}</p><ModelFields model={model} value={modelJson} onChange={setModelJson} /><details className="wb-advanced"><summary>Полный контракт модели · JSON</summary><JsonEditor label={model === "corridors/check" ? "CorridorSpec JSON" : "FleetSpec JSON"} value={modelJson} setValue={setModelJson} rows={22} /></details><button className="primary-button" disabled={busy} onClick={() => void perform(async () => setModelResult(await api(model, { method: "POST", headers: jsonHeaders, body: pretty(JSON.parse(modelJson)) })))}>Выполнить расчёт <ArrowRight size={17} /></button>{modelResult !== null && <div className="wb-preview"><strong>Результат модели</strong><pre>{pretty(modelResult)}</pre></div>}</div>}
    {error && <p className="error-banner" role="alert">{error}</p>}{message && <p className="wb-success" role="status">{message}</p>}
  </section>;
}

function DatasetList({ datasets }: { datasets: Dataset[] }) {
  if (!datasets.length) return null;
  return <div className="wb-datasets"><h3>Версии данных</h3><div className="data-table-scroll"><table className="data-table"><thead><tr><th>Версия</th><th>Источник</th><th>Формат</th><th>SHA-256</th><th>Файл</th></tr></thead><tbody>{datasets.map((item) => <tr key={item.id}><th>{item.name}<small>{item.id}</small></th><td>{item.source}</td><td>{item.format} · {item.role || "—"}</td><td title={item.checksum}>{item.checksum?.slice(0, 12)}…</td><td>{item.format === "csv" && <a href={"/api/workbench/datasets/" + item.id + "/file"} download aria-label={"Скачать " + item.name}><Download size={16} /></a>}</td></tr>)}</tbody></table></div></div>;
}

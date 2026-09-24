"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, MapPin, Plus, Minus } from "lucide-react";
import { load } from "@2gis/mapgl";
import type { Map as MapGLMap } from "@2gis/mapgl/types";
import type { MapSite, MapZone } from "@/lib/planning";

type Selection = { site_id: string; option_id: string; year: number };
type MapStatus = "loading" | "ready" | "missing-key" | "error";
type Point = { id: string; name: string; kind: "site" | "demand"; subtitle: string };

const MAP_LOAD_TIMEOUT_MS = 12_000;

function withTimeout<T>(promise: Promise<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timeout = window.setTimeout(() => reject(new Error("Превышено время загрузки 2ГИС")), MAP_LOAD_TIMEOUT_MS);
    promise.then(
      (value) => { window.clearTimeout(timeout); resolve(value); },
      (error) => { window.clearTimeout(timeout); reject(error); },
    );
  });
}

export default function PlanningMap({ selected, sites, zones }: { selected?: Selection[]; sites: MapSite[]; zones: MapZone[] }) {
  const holder = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapGLMap | null>(null);
  const [status, setStatus] = useState<MapStatus>("loading");
  const [active, setActive] = useState<Point | null>(null);
  const bySite = useMemo(() => new Map((selected ?? []).map((item) => [item.site_id, item])), [selected]);
  const points = useMemo(() => [...sites, ...zones], [sites, zones]);
  const center = useMemo<[number, number]>(() => {
    if (!points.length) return [60.606, 56.829];
    return [points.reduce((sum, point) => sum + point.longitude, 0) / points.length,
      points.reduce((sum, point) => sum + point.latitude, 0) / points.length];
  }, [points]);

  useEffect(() => {
    let cancelled = false;
    let map: MapGLMap | null = null;
    async function initialize() {
      setStatus("loading");
      try {
        const response = await fetch("/api/maps/config", { cache: "no-store" });
        if (!response.ok) throw new Error("Настройки карты недоступны");
        const config: { configured: boolean; apiKey?: string; styleId?: string } = await response.json();
        if (!config.configured || !config.apiKey) { if (!cancelled) setStatus("missing-key"); return; }
        const api = await withTimeout(load());
        if (cancelled || !holder.current) return;
        map = new api.Map(holder.current, {
          center, zoom: 12, key: config.apiKey,
          ...(config.styleId ? { style: config.styleId, defaultBackgroundColor: "#171b20" } : {}),
        });
        mapRef.current = map;
        map.on("error", () => { if (!cancelled) setStatus("error"); });
        for (const zone of zones) {
          const marker = document.createElement("button");
          marker.type = "button";
          marker.className = "map-point demand";
          marker.title = `${zone.name} · зона спроса`;
          marker.setAttribute("aria-label", marker.title);
          marker.onclick = () => setActive({ id: zone.id, name: zone.name, kind: "demand", subtitle: "Зона спроса · сценарные данные" });
          new api.HtmlMarker(map, { coordinates: [zone.longitude, zone.latitude], html: marker,
            interactive: true, zIndex: 1 });
        }
        for (const site of sites) {
          const selection = bySite.get(site.id);
          const marker = document.createElement("button");
          marker.type = "button";
          marker.className = `map-point ${selection ? "selected" : "candidate"}`;
          marker.title = `${site.name} · ${selection ? `выбрана, ввод ${selection.year}` : "кандидат"}`;
          marker.setAttribute("aria-label", marker.title);
          marker.textContent = site.name.split(" · ")[0].replace("Площадка ", "");
          marker.onclick = () => setActive({ id: site.id, name: site.name, kind: "site",
            subtitle: selection ? `${selection.option_id.toUpperCase()} · ввод ${selection.year}` : "Площадка-кандидат" });
          new api.HtmlMarker(map, { coordinates: [site.longitude, site.latitude], html: marker,
            interactive: true, zIndex: selection ? 3 : 2 });
        }
        if (points.length > 1) {
          const longitudes = points.map((point) => point.longitude);
          const latitudes = points.map((point) => point.latitude);
          const west = Math.min(...longitudes), east = Math.max(...longitudes);
          const south = Math.min(...latitudes), north = Math.max(...latitudes);
          if (west < east || south < north) {
            map.fitBounds({ northEast: [east, north], southWest: [west, south] },
              { padding: { top: 42, right: 42, bottom: 65, left: 42 } });
          }
        }
        if (!cancelled) setStatus("ready");
      } catch {
        map?.destroy();
        if (mapRef.current === map) mapRef.current = null;
        if (!cancelled) setStatus("error");
      }
    }
    void initialize();
    return () => { cancelled = true; map?.destroy(); if (mapRef.current === map) mapRef.current = null; };
  }, [bySite, center, points, sites, zones]);

  function zoom(direction: 1 | -1) {
    if (!mapRef.current) return;
    mapRef.current.setZoom(Math.min(18, Math.max(3, mapRef.current.getZoom() + direction)));
  }

  return <div className="map-frame" role="group" aria-label="Карта территории сценария">
    <div ref={holder} className="map-canvas" aria-hidden={status !== "ready"} />
    {status === "loading" && <div className="map-state"><div className="map-state-icon"><MapPin size={22} /></div><strong>Открываем карту территории</strong><span>Подключаем картографический слой 2ГИС</span></div>}
    {status === "missing-key" && <div className="map-state"><div className="map-state-icon"><MapPin size={22} /></div><strong>Карта ожидает подключения</strong><span>Добавьте ключ 2ГИС MapGL в настройки развёртывания.</span><a href="https://docs.2gis.com/mapgl/start/first-steps" target="_blank" rel="noreferrer">Как получить ключ <ArrowUpRight size={15} /></a></div>}
    {status === "error" && <div className="map-state"><div className="map-state-icon"><MapPin size={22} /></div><strong>Карта сейчас недоступна</strong><span>Проверьте ключ 2ГИС MapGL, доступ к Map Tiles API и разрешённый домен.</span></div>}
    {status === "ready" && <div className="map-zoom" aria-label="Масштаб карты"><button type="button" onClick={() => zoom(1)} aria-label="Приблизить карту"><Plus size={17} /></button><button type="button" onClick={() => zoom(-1)} aria-label="Отдалить карту"><Minus size={17} /></button></div>}
    {active && status === "ready" && <div className="map-detail"><div><span>{active.kind === "site" ? "ИНФРАСТРУКТУРА" : "СПРОС"}</span><strong>{active.name}</strong><small>{active.subtitle}</small></div><button type="button" onClick={() => setActive(null)} aria-label="Закрыть сведения">×</button></div>}
    <div className="map-key" aria-label="Обозначения на карте"><span><i className="key-dot selected" />Выбрано</span><span><i className="key-dot candidate" />Кандидат</span><span><i className="key-dot demand" />Спрос</span></div>
    <span className="map-provider">2ГИС</span>
  </div>;
}

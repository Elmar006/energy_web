"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, MapPin, Plus, Minus } from "lucide-react";
import type {} from "@yandex/ymaps3-types";
import { demoSites, demoZones } from "@/lib/demo";

type Selection = { site_id: string; option_id: string; year: number };
type MapStatus = "loading" | "ready" | "missing-key" | "error";
type Point = { id: string; name: string; kind: "site" | "demand"; subtitle: string };

const center: [number, number] = [60.606, 56.829];
type YMapsRuntime = typeof import("@yandex/ymaps3-types");
let apiPromise: Promise<YMapsRuntime> | null = null;

function currentYMaps(): YMapsRuntime | undefined {
  return (window as Window & { ymaps3?: YMapsRuntime }).ymaps3;
}

function loadYandexMaps(key: string): Promise<YMapsRuntime> {
  const present = currentYMaps();
  if (present) return present.ready.then(() => present);
  if (!apiPromise) {
    apiPromise = new Promise<YMapsRuntime>((resolve, reject) => {
      const script = document.createElement("script");
      script.src = `https://api-maps.yandex.ru/v3/?apikey=${encodeURIComponent(key)}&lang=ru_RU`;
      script.async = true;
      script.onload = () => {
        const loaded = currentYMaps();
        if (!loaded) { reject(new Error("Яндекс Карты не загрузились")); return; }
        loaded.ready.then(() => resolve(loaded)).catch(reject);
      };
      script.onerror = () => reject(new Error("Не удалось загрузить Яндекс Карты"));
      document.head.appendChild(script);
    }).catch((error) => { apiPromise = null; throw error; });
  }
  return apiPromise;
}

export default function PlanningMap({ selected }: { selected?: Selection[] }) {
  const holder = useRef<HTMLDivElement>(null);
  const mapRef = useRef<InstanceType<typeof ymaps3.YMap> | null>(null);
  const [status, setStatus] = useState<MapStatus>("loading");
  const [active, setActive] = useState<Point | null>(null);
  const bySite = useMemo(() => new Map((selected ?? []).map((item) => [item.site_id, item])), [selected]);

  useEffect(() => {
    let cancelled = false;
    let map: InstanceType<typeof ymaps3.YMap> | null = null;
    async function initialize() {
      try {
        const response = await fetch("/api/maps/config", { cache: "no-store" });
        if (!response.ok) throw new Error("Настройки карты недоступны");
        const config: { configured: boolean; apiKey?: string } = await response.json();
        if (!config.configured || !config.apiKey) { if (!cancelled) setStatus("missing-key"); return; }
        const api = await loadYandexMaps(config.apiKey);
        if (cancelled || !holder.current) return;
        map = new api.YMap(holder.current, { location: { center, zoom: 12 }, theme: "dark", mode: "vector",
          behaviors: ["drag", "scrollZoom", "pinchZoom", "dblClick"] });
        mapRef.current = map;
        map.addChild(new api.YMapDefaultSchemeLayer({ customization: [
          { tags: { any: ["poi", "transit_location"] }, elements: "label.icon", stylers: [{ visibility: "off" }] },
          { tags: { all: ["landscape"] }, elements: "geometry", stylers: [{ saturation: -1 }] },
        ] }));
        map.addChild(new api.YMapDefaultFeaturesLayer({ zIndex: 1800 }));
        for (const zone of demoZones) {
          const marker = document.createElement("button");
          marker.type = "button";
          marker.className = "map-point demand";
          marker.title = `${zone.name} · зона спроса`;
          marker.setAttribute("aria-label", marker.title);
          marker.onclick = () => setActive({ id: zone.id, name: zone.name, kind: "demand", subtitle: "Зона спроса · сценарные данные" });
          map.addChild(new api.YMapMarker({ coordinates: [zone.longitude, zone.latitude] }, marker));
        }
        for (const site of demoSites) {
          const selection = bySite.get(site.id);
          const marker = document.createElement("button");
          marker.type = "button";
          marker.className = `map-point ${selection ? "selected" : "candidate"}`;
          marker.title = `${site.name} · ${selection ? `выбрана, ввод ${selection.year}` : "кандидат"}`;
          marker.setAttribute("aria-label", marker.title);
          marker.textContent = site.name.split(" · ")[0].replace("Площадка ", "");
          marker.onclick = () => setActive({ id: site.id, name: site.name, kind: "site",
            subtitle: selection ? `${selection.option_id.toUpperCase()} · ввод ${selection.year}` : "Площадка-кандидат" });
          map.addChild(new api.YMapMarker({ coordinates: [site.longitude, site.latitude] }, marker));
        }
        if (!cancelled) setStatus("ready");
      } catch {
        if (!cancelled) setStatus("error");
      }
    }
    void initialize();
    return () => { cancelled = true; map?.destroy(); if (mapRef.current === map) mapRef.current = null; };
  }, [bySite]);

  function zoom(direction: 1 | -1) {
    if (!mapRef.current) return;
    mapRef.current.update({ location: { zoom: Math.min(18, Math.max(3, mapRef.current.zoom + direction)) } });
  }

  return <div className="map-frame" role="group" aria-label="Карта пилотной территории">
    <div ref={holder} className="map-canvas" aria-hidden={status !== "ready"} />
    {status === "loading" && <div className="map-state"><div className="map-state-icon"><MapPin size={22} /></div><strong>Открываем карту территории</strong><span>Подключаем картографический слой</span></div>}
    {status === "missing-key" && <div className="map-state"><div className="map-state-icon"><MapPin size={22} /></div><strong>Карта ожидает подключения</strong><span>Добавьте ключ JavaScript API Яндекс Карт в настройки развёртывания.</span><a href="https://yandex.ru/maps-api/docs/js-api/common/quickstart.html" target="_blank" rel="noreferrer">Как получить ключ <ArrowUpRight size={15} /></a></div>}
    {status === "error" && <div className="map-state"><div className="map-state-icon"><MapPin size={22} /></div><strong>Карта сейчас недоступна</strong><span>Проверьте ключ, HTTP Referer и доступ к API Яндекс Карт.</span></div>}
    {status === "ready" && <div className="map-zoom" aria-label="Масштаб карты"><button type="button" onClick={() => zoom(1)} aria-label="Приблизить карту"><Plus size={17} /></button><button type="button" onClick={() => zoom(-1)} aria-label="Отдалить карту"><Minus size={17} /></button></div>}
    {active && status === "ready" && <div className="map-detail"><div><span>{active.kind === "site" ? "ИНФРАСТРУКТУРА" : "СПРОС"}</span><strong>{active.name}</strong><small>{active.subtitle}</small></div><button type="button" onClick={() => setActive(null)} aria-label="Закрыть сведения">×</button></div>}
    <div className="map-key" aria-label="Обозначения на карте"><span><i className="key-dot selected" />Выбрано</span><span><i className="key-dot candidate" />Кандидат</span><span><i className="key-dot demand" />Спрос</span></div>
    <span className="map-provider">Яндекс Карты</span>
  </div>;
}

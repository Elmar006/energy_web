import Link from "next/link";
import { ArrowRight, FileInput, SlidersHorizontal, ChartNoAxesCombined } from "lucide-react";
import NetworkFigure from "./network-figure";

export default function PlanningEmpty() {
  return (
    <section className="planning-empty" aria-label="Нет исходных данных">
      <div className="planning-empty-intro">
        <div className="planning-empty-copy">
          <h2>Данные не загружены</h2>
          <p>Загрузите территорию, спрос и ограничения подключения.</p>
          <Link className="primary-button" href="/data/scenario">Добавить данные <ArrowRight size={18} aria-hidden="true" /></Link>
          <span className="empty-caption">Готовый JSON можно импортировать ниже.</span>
        </div>
        <div className="empty-illustration"><NetworkFigure /><span>Схема инфраструктуры · иллюстрация</span></div>
      </div>
      <ol className="planning-steps" aria-label="Этапы планирования">
        <li><span className="step-index">01</span><FileInput size={20} aria-hidden="true" /><strong>Данные</strong><p>Территория, спрос, подключения</p></li>
        <li><span className="step-index">02</span><SlidersHorizontal size={20} aria-hidden="true" /><strong>Условия</strong><p>Бюджет, сроки, уровень обслуживания</p></li>
        <li><span className="step-index">03</span><ChartNoAxesCombined size={20} aria-hidden="true" /><strong>Результат</strong><p>Размещение, нагрузка, стоимость</p></li>
      </ol>
    </section>
  );
}

import Link from "next/link";
import { ArrowRight, FileInput, SlidersHorizontal, ChartNoAxesCombined } from "lucide-react";
import NetworkFigure from "./network-figure";

export default function PlanningEmpty() {
  return (
    <section className="planning-empty" aria-label="Нет исходных данных">
      <div className="planning-empty-intro">
        <div className="planning-empty-copy">
          <span className="empty-label">Начало работы</span>
          <h2>Данные не загружены</h2>
          <p>Подготовьте территорию, спрос и ограничения сети. На их основе система рассчитает размещение зарядок и инвестиционный план.</p>
          <Link className="primary-button" href="/data/scenario">Подготовить исходные данные <ArrowRight size={18} aria-hidden="true" /></Link>
          <span className="empty-caption">Готовый сценарий можно импортировать в панели условий.</span>
        </div>
        <div className="empty-illustration"><NetworkFigure /><span>Схема инфраструктуры · иллюстрация</span></div>
      </div>
      <ol className="planning-steps" aria-label="Этапы планирования">
        <li><span className="step-index">01</span><FileInput size={20} aria-hidden="true" /><strong>Подготовьте вход</strong><p>Территория, площадки и происхождение данных</p></li>
        <li><span className="step-index">02</span><SlidersHorizontal size={20} aria-hidden="true" /><strong>Задайте условия</strong><p>Бюджет, горизонт и требования обслуживания</p></li>
        <li><span className="step-index">03</span><ChartNoAxesCombined size={20} aria-hidden="true" /><strong>Сравните решения</strong><p>Размещение, эксплуатация и стоимость</p></li>
      </ol>
    </section>
  );
}

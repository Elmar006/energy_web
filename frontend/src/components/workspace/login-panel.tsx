"use client";

import Image from "next/image";
import { ArrowRight } from "lucide-react";
import NetworkFigure from "./network-figure";
import { brand } from "@/lib/brand";

export default function LoginPanel({
  password,
  onPasswordChange,
  onSubmit,
  error,
}: {
  password: string;
  onPasswordChange: (value: string) => void;
  onSubmit: (event: React.FormEvent) => Promise<void>;
  error: string;
}) {
  return (
    <main className="login-screen">
      <section className="login-story" aria-label="О платформе">
        <div className="login-brand"><Image src={brand.logo} width={40} height={40} alt="" /><span>{brand.name}</span></div>
        <div className="login-story-content"><h2>Планирование<br />инфраструктуры</h2><NetworkFigure /></div>
      </section>
      <div className="login-form-area">
      <div className="login-panel">
        <h1>Вход</h1>
        <form onSubmit={(event) => void onSubmit(event)}>
          <label htmlFor="password">Пароль доступа</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => onPasswordChange(event.target.value)}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? "password-error" : undefined}
            required
          />
          <button className="primary-button" type="submit">
            Войти <ArrowRight size={17} aria-hidden="true" />
          </button>
        </form>
        {error && (
          <p id="password-error" className="error-banner" role="alert">
            {error}
          </p>
        )}
      </div>
      </div>
    </main>
  );
}

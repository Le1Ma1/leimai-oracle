"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { detectDefaultLocale, getNextLocale, t } from "../lib/i18n";
import type { EvolutionValidation, LocaleCode, VisualState } from "../lib/types";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function formatSigned(value: number): string {
  if (!Number.isFinite(value)) {
    return "--";
  }
  return `${value >= 0 ? "+" : ""}${value.toFixed(4)}`;
}

function formatPct(value: number): string {
  if (!Number.isFinite(value)) {
    return "--";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function formatNumber(value: number, digits = 2): string {
  if (!Number.isFinite(value)) {
    return "--";
  }
  return value.toFixed(digits);
}

function freshness(lastSynced: string): { fresh: boolean; seconds: number } {
  const ts = Date.parse(lastSynced);
  if (!Number.isFinite(ts)) {
    return { fresh: false, seconds: Number.POSITIVE_INFINITY };
  }
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  return { fresh: seconds <= 600, seconds };
}

export default function HomePage() {
  const [locale, setLocale] = useState<LocaleCode>("en-US");
  const [visualState, setVisualState] = useState<VisualState | null>(null);
  const [evolution, setEvolution] = useState<EvolutionValidation | null>(null);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    setLocale(detectDefaultLocale());
    const fetchState = async () => {
      try {
        const stamp = `${Date.now()}`;
        const [vRes, eRes] = await Promise.all([
          fetch(`/state/visual_state.json?ts=${stamp}`, { cache: "no-store" }),
          fetch(`/state/evolution_validation.json?ts=${stamp}`, { cache: "no-store" })
        ]);
        if (!vRes.ok || !eRes.ok) {
          throw new Error("STATE_FETCH_FAILED");
        }
        const vPayload = (await vRes.json()) as VisualState;
        const ePayload = (await eRes.json()) as EvolutionValidation;
        setVisualState(vPayload);
        setEvolution(ePayload);
      } catch (fetchError) {
        setError(fetchError instanceof Error ? fetchError.message : "UNKNOWN_ERROR");
      }
    };
    void fetchState();
  }, []);

  const heartbeat = useMemo(() => {
    if (!visualState) {
      return { fresh: false, seconds: Number.POSITIVE_INFINITY };
    }
    return freshness(visualState.last_synced_at);
  }, [visualState]);

  const radarOption = useMemo(() => {
    const metrics = evolution?.metrics;
    if (!metrics) {
      return null;
    }
    const pboScore = clamp((1 - metrics.pbo) * 100, 0, 100);
    const dsrScore = clamp(((metrics.dsr + 2.0) / 2.5) * 100, 0, 100);
    const f1Score = clamp(metrics.f1 * 100, 0, 100);
    const floorScore = clamp(metrics.precision_floor_compliance_rate * 100, 0, 100);
    return {
      backgroundColor: "transparent",
      radar: {
        indicator: [
          { name: t(locale, "radarPbo"), max: 100 },
          { name: t(locale, "radarDsr"), max: 100 },
          { name: t(locale, "radarF1"), max: 100 },
          { name: t(locale, "radarFloor"), max: 100 }
        ],
        axisName: { color: "#f6deb2", fontSize: 12 },
        splitLine: { lineStyle: { color: "rgba(250, 224, 170, 0.18)" } },
        splitArea: { areaStyle: { color: ["rgba(255, 214, 127, 0.04)", "rgba(255, 214, 127, 0.02)"] } }
      },
      series: [
        {
          type: "radar",
          data: [
            {
              value: [pboScore, dsrScore, f1Score, floorScore],
              areaStyle: { color: "rgba(255, 196, 77, 0.22)" },
              lineStyle: { color: "#ffc44d", width: 2 },
              itemStyle: { color: "#ffd78f" }
            }
          ]
        }
      ]
    };
  }, [evolution?.metrics]);

  const rejectionOption = useMemo(() => {
    const breakdown = evolution?.rejection_breakdown || visualState?.rejection_breakdown || [];
    if (!breakdown.length) {
      return null;
    }
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "item" },
      series: [
        {
          type: "pie",
          radius: ["36%", "70%"],
          avoidLabelOverlap: false,
          label: { color: "#f8e6c8", fontSize: 12 },
          labelLine: { lineStyle: { color: "rgba(248, 230, 200, 0.5)" } },
          itemStyle: { borderColor: "#0d0d0d", borderWidth: 2 },
          data: breakdown.map((item) => ({
            name: t(locale, item.reason_key),
            value: item.count
          }))
        }
      ]
    };
  }, [evolution?.rejection_breakdown, locale, visualState?.rejection_breakdown]);

  return (
    <main className="dashboard">
      <header className="header">
        <div>
          <h1>{t(locale, "title")}</h1>
          <p>{t(locale, "subtitle")}</p>
        </div>
        <button className="localeButton" onClick={() => setLocale(getNextLocale(locale))} type="button">
          {t(locale, "toggle")}: {locale}
        </button>
      </header>

      {error ? <div className="errorBox">{error}</div> : null}

      <section className="topGrid">
        <article className="card">
          <span className="label">{t(locale, "marketRegime")}</span>
          <strong className="value">{t(locale, visualState?.regime_key || "REGIME_CONSOLIDATION")}</strong>
        </article>
        <article className="card">
          <span className="label">{t(locale, "liveAlpha")}</span>
          <strong className="value">{formatSigned(visualState?.live_alpha_vs_spot ?? Number.NaN)}</strong>
        </article>
        <article className="card">
          <span className="label">{t(locale, "maxDrawdown")}</span>
          <strong className="value">{formatSigned(visualState?.max_drawdown ?? Number.NaN)}</strong>
        </article>
        <article className="card">
          <span className="label">{t(locale, "heartbeat")}</span>
          <div className="heartbeatWrap">
            <span className={`pulse ${heartbeat.fresh && visualState?.heartbeat_ok ? "ok" : "stale"}`} />
            <strong className="value">
              {heartbeat.fresh && visualState?.heartbeat_ok ? t(locale, "heartbeatLive") : t(locale, "heartbeatStale")}
            </strong>
          </div>
          <small className="subtle">
            {t(locale, "lastSynced")}: {visualState?.last_synced_at || t(locale, "na")}
          </small>
        </article>
      </section>

      <details className="ceoBlock" open>
        <summary>
          <span>{t(locale, "ceoPanel")}</span>
          <small>{t(locale, "ceoHint")}</small>
        </summary>
        <section className="ceoGrid">
          <article className="card chartCard">
            <div className="cardHeader">{t(locale, "robustnessRadar")}</div>
            {radarOption ? <ReactECharts option={radarOption} style={{ height: 320 }} /> : <div className="empty">{t(locale, "na")}</div>}
          </article>
          <article className="card chartCard">
            <div className="cardHeader">{t(locale, "rejectionPie")}</div>
            {rejectionOption ? (
              <ReactECharts option={rejectionOption} style={{ height: 320 }} />
            ) : (
              <div className="empty">{t(locale, "na")}</div>
            )}
          </article>
          <article className="card diagnostics">
            <div className="cardHeader">{t(locale, "diagnostics")}</div>
            <div className="diagnosticsGrid">
              <div>
                <span className="label">{t(locale, "vetoRate")}</span>
                <strong>{formatPct(visualState?.meta_diagnostics?.veto_rate ?? Number.NaN)}</strong>
              </div>
              <div>
                <span className="label">{t(locale, "threshold")}</span>
                <strong>{formatNumber(visualState?.meta_diagnostics?.threshold_selected ?? Number.NaN, 2)}</strong>
              </div>
              <div>
                <span className="label">{t(locale, "precisionFloor")}</span>
                <strong>{formatNumber(visualState?.meta_diagnostics?.precision_floor ?? Number.NaN, 2)}</strong>
              </div>
              <div>
                <span className="label">{t(locale, "compliance")}</span>
                <strong>{formatPct(visualState?.meta_diagnostics?.precision_floor_compliance_rate ?? Number.NaN)}</strong>
              </div>
              <div>
                <span className="label">{t(locale, "failsafeRate")}</span>
                <strong>{formatPct(visualState?.meta_diagnostics?.failsafe_veto_all_rate ?? Number.NaN)}</strong>
              </div>
              <div>
                <span className="label">{t(locale, "runId")}</span>
                <strong className="mono">{visualState?.run_id || t(locale, "na")}</strong>
              </div>
            </div>
          </article>
        </section>
      </details>
    </main>
  );
}

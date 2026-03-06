"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { detectDefaultLocale, getNextLocale, t } from "../lib/i18n";
import type { EvolutionValidation, LocaleCode, TrainingRoadmap, TrainingRuntime, VisualState } from "../lib/types";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });
const POLL_INTERVAL_MS = 5000;

type ToastLevel = "info" | "warn" | "success";
type ToastItem = { id: number; level: ToastLevel; message: string };
type StateFetch<T> = { payload: T; sourceKey: string };

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

function formatDuration(seconds: number | null | undefined): string {
  if (!Number.isFinite(Number(seconds)) || seconds === null || seconds === undefined) {
    return "--";
  }
  const total = Math.max(0, Math.floor(Number(seconds)));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function freshness(lastSynced: string): { fresh: boolean; seconds: number } {
  const ts = Date.parse(lastSynced);
  if (!Number.isFinite(ts)) {
    return { fresh: false, seconds: Number.POSITIVE_INFINITY };
  }
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  return { fresh: seconds <= 600, seconds };
}

function toastLevelByNotify(key: string): ToastLevel {
  if (key === "NOTIFY_STALLED") {
    return "warn";
  }
  if (key === "NOTIFY_COMPLETED") {
    return "success";
  }
  return "info";
}

async function fetchStateFile<T>(name: string, stamp: string): Promise<StateFetch<T>> {
  const candidates = [`/api/state/${name}?ts=${stamp}`, `/state/${name}?ts=${stamp}`];
  for (const url of candidates) {
    const resp = await fetch(url, { cache: "no-store" });
    if (!resp.ok) {
      continue;
    }
    const sourceKey = String(
      resp.headers.get("x-state-source") || (url.startsWith("/api/state/") ? "SOURCE_API" : "SOURCE_STATIC")
    );
    const payload = (await resp.json()) as T;
    return { payload, sourceKey };
  }
  throw new Error(`STATE_FETCH_FAILED:${name}`);
}

export default function HomePage() {
  const [locale, setLocale] = useState<LocaleCode>("en-US");
  const [visualState, setVisualState] = useState<VisualState | null>(null);
  const [evolution, setEvolution] = useState<EvolutionValidation | null>(null);
  const [roadmap, setRoadmap] = useState<TrainingRoadmap | null>(null);
  const [runtime, setRuntime] = useState<TrainingRuntime | null>(null);
  const [stateSourceKey, setStateSourceKey] = useState<string>("SOURCE_UNKNOWN");
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [notificationPermission, setNotificationPermission] = useState<string>("default");
  const [error, setError] = useState<string>("");
  const lastNotifySeqRef = useRef<number>(0);

  const pushToast = (message: string, level: ToastLevel) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((prev) => [...prev, { id, level, message }].slice(-4));
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((row) => row.id !== id));
    }, 6500);
  };

  useEffect(() => {
    setLocale(detectDefaultLocale());
    if (typeof window !== "undefined" && "Notification" in window) {
      setNotificationPermission(Notification.permission);
      if (Notification.permission === "default") {
        void Notification.requestPermission().then((permission) => {
          setNotificationPermission(permission);
        });
      }
    }
  }, []);

  useEffect(() => {
    let disposed = false;

    const fetchState = async () => {
      try {
        const stamp = `${Date.now()}`;
        const [vData, eData, rData, rtData] = await Promise.all([
          fetchStateFile<VisualState>("visual_state.json", stamp),
          fetchStateFile<EvolutionValidation>("evolution_validation.json", stamp),
          fetchStateFile<TrainingRoadmap>("training_roadmap.json", stamp),
          fetchStateFile<TrainingRuntime>("training_runtime.json", stamp)
        ]);

        if (disposed) {
          return;
        }

        setVisualState(vData.payload);
        setEvolution(eData.payload);
        setRoadmap(rData.payload);
        setRuntime(rtData.payload);
        setStateSourceKey(rtData.sourceKey || vData.sourceKey || eData.sourceKey || rData.sourceKey || "SOURCE_UNKNOWN");
        setError("");

        const seq = Number(rtData.payload.notify_seq ?? 0);
        const notifyEvent = String(rtData.payload.notify_event_key || "");
        if (notifyEvent && Number.isFinite(seq) && seq > lastNotifySeqRef.current) {
          lastNotifySeqRef.current = seq;
          const message = t(locale, notifyEvent);
          const level = toastLevelByNotify(notifyEvent);
          pushToast(message, level);
          if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "granted") {
            try {
              void new Notification(t(locale, "missionTitle"), { body: message });
            } catch {
              // Ignore notification API errors.
            }
          }
        }
      } catch (fetchError) {
        if (!disposed) {
          setError(fetchError instanceof Error ? fetchError.message : "UNKNOWN_ERROR");
        }
      }
    };

    void fetchState();
    const timer = window.setInterval(fetchState, POLL_INTERVAL_MS);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [locale]);

  const heartbeat = useMemo(() => {
    if (!visualState) {
      return { fresh: false, seconds: Number.POSITIVE_INFINITY };
    }
    return freshness(visualState.last_synced_at);
  }, [visualState]);

  const runtimeProgressPct = useMemo(() => {
    if (!runtime) {
      return 0;
    }
    if (runtime.progress_completed) {
      return 100;
    }
    return clamp(Number(runtime.tasks_pct || 0), 0, 100);
  }, [runtime]);

  const gateBlocked = useMemo(() => {
    return Boolean(runtime?.gate_blocked && String(runtime?.gate_block_reason_key || "").length > 0);
  }, [runtime?.gate_block_reason_key, runtime?.gate_blocked]);

  const runtimeEtaConfidence = useMemo(() => {
    const key = String(runtime?.eta_confidence || "low").toLowerCase();
    if (key === "high" || key === "medium" || key === "low") {
      return t(locale, key);
    }
    return t(locale, "low");
  }, [locale, runtime?.eta_confidence]);

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
  }, [evolution?.metrics, locale]);

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

  const roadmapTrendOption = useMemo(() => {
    const rows = roadmap?.rounds || [];
    if (!rows.length) {
      return null;
    }
    const recent = rows.slice(-24);
    const labels = recent.map((row) => `R${row.round_index}`);
    const passSeries = recent.map((row) => clamp(row.validation_pass_rate * 100, 0, 100));
    const alphaSeries = recent.map((row) => row.all_window_alpha);
    const vetoSeries = recent.map((row) => clamp(Math.max(row.veto_rate, row.failsafe_veto_all_rate) * 100, 0, 100));

    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: {
        top: 2,
        textStyle: { color: "rgba(248, 230, 200, 0.75)", fontSize: 11 },
        data: [t(locale, "passRate"), t(locale, "alphaAll"), t(locale, "vetoPressure")]
      },
      grid: { left: 48, right: 48, top: 34, bottom: 24 },
      xAxis: {
        type: "category",
        data: labels,
        axisLine: { lineStyle: { color: "rgba(248, 230, 200, 0.24)" } },
        axisLabel: { color: "rgba(248, 230, 200, 0.7)", fontSize: 11 }
      },
      yAxis: [
        {
          type: "value",
          min: 0,
          max: 100,
          axisLine: { lineStyle: { color: "rgba(248, 230, 200, 0.24)" } },
          splitLine: { lineStyle: { color: "rgba(248, 230, 200, 0.12)" } },
          axisLabel: { color: "rgba(248, 230, 200, 0.7)", formatter: "{value}%" }
        },
        {
          type: "value",
          axisLine: { lineStyle: { color: "rgba(248, 230, 200, 0.24)" } },
          splitLine: { show: false },
          axisLabel: { color: "rgba(248, 230, 200, 0.7)" }
        }
      ],
      series: [
        {
          name: t(locale, "passRate"),
          type: "line",
          smooth: true,
          yAxisIndex: 0,
          data: passSeries,
          lineStyle: { color: "#ffd38a", width: 2 },
          itemStyle: { color: "#ffd38a" }
        },
        {
          name: t(locale, "alphaAll"),
          type: "line",
          smooth: true,
          yAxisIndex: 1,
          data: alphaSeries,
          lineStyle: { color: "#9bb7ff", width: 2 },
          itemStyle: { color: "#9bb7ff" }
        },
        {
          name: t(locale, "vetoPressure"),
          type: "line",
          smooth: true,
          yAxisIndex: 0,
          data: vetoSeries,
          lineStyle: { color: "#ff8a8a", width: 1.8, type: "dashed" },
          itemStyle: { color: "#ff8a8a" }
        }
      ]
    };
  }, [locale, roadmap?.rounds]);

  const recentRoadmapRounds = useMemo(() => (roadmap?.rounds || []).slice(-8).reverse(), [roadmap?.rounds]);
  const latestRoadmapRound = useMemo(
    () => (roadmap?.latest_round && "run_id" in roadmap.latest_round ? roadmap.latest_round : null),
    [roadmap?.latest_round]
  );
  const bestRoadmapRound = useMemo(
    () => (roadmap?.best_round && "run_id" in roadmap.best_round ? roadmap.best_round : null),
    [roadmap?.best_round]
  );
  const diagnosis = roadmap?.diagnosis || null;
  const profileComparisonRows = useMemo(() => roadmap?.profile_comparison?.rows || [], [roadmap?.profile_comparison?.rows]);

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

      <section className="missionBlock">
        <div className="missionHead">
          <div>
            <div className="missionTitle">{t(locale, "missionTitle")}</div>
            <div className="missionHint">{t(locale, "missionHint")}</div>
          </div>
          <div className="missionActions">
            <button
              className="notifyButton"
              type="button"
              onClick={() => {
                if (typeof window !== "undefined" && "Notification" in window) {
                  void Notification.requestPermission().then((permission) => {
                    setNotificationPermission(permission);
                  });
                }
              }}
            >
              {t(locale, "enableNotify")}
            </button>
            {notificationPermission === "denied" ? <span className="notifyDenied">{t(locale, "notifyDenied")}</span> : null}
          </div>
        </div>

        <div className="missionGrid">
          <article className="card">
            <span className="label">{t(locale, "runtimeStatus")}</span>
            <strong className="value">{t(locale, runtime?.runtime_status_key || "RUNTIME_IDLE")}</strong>
          </article>
          <article className="card">
            <span className="label">{t(locale, "runtimePhase")}</span>
            <strong className="value">{t(locale, runtime?.phase_key || "PHASE_WAITING")}</strong>
          </article>
          <article className="card">
            <span className="label">{t(locale, "runElapsed")}</span>
            <strong className="value mono">{formatDuration(runtime?.elapsed_sec ?? null)}</strong>
          </article>
          <article className="card">
            <span className="label">{t(locale, "runRemaining")}</span>
            <strong className="value mono">{formatDuration(runtime?.remaining_sec ?? null)}</strong>
          </article>
          <article className="card">
            <span className="label">{t(locale, "etaAt")}</span>
            <strong className="value mono">{runtime?.eta_utc || t(locale, "na")}</strong>
            <small className="subtle">
              {t(locale, "etaConfidence")}: {runtimeEtaConfidence}
            </small>
          </article>
          <article className="card">
            <span className="label">{t(locale, "runId")}</span>
            <strong className="value mono">{runtime?.run_id || t(locale, "na")}</strong>
          </article>
          <article className="card">
            <span className="label">{t(locale, "stateSource")}</span>
            <strong className="value">{t(locale, stateSourceKey || "SOURCE_UNKNOWN")}</strong>
          </article>
        </div>

        <div className="missionProgress">
          <div className="missionProgressMeta">
            <span>
              {t(locale, "cycle")}: {runtime?.cycle_current ?? 0}/{runtime?.cycle_total ?? 0}
            </span>
            <span>
              {t(locale, "tasks")}: {runtime?.tasks_done ?? 0}/{runtime?.tasks_total ?? 0}
            </span>
            <span>{formatPct(runtimeProgressPct / 100)}</span>
          </div>
          <div className="progressBar">
            <span style={{ width: `${runtimeProgressPct}%` }} />
          </div>
        </div>

        {gateBlocked ? (
          <div className="missionAlert warn">
            <strong>{t(locale, "stallReason")}:</strong> {t(locale, runtime?.gate_block_reason_key || "STALL_TARGET_NOT_MET")}
          </div>
        ) : null}
        {!gateBlocked && runtime?.runtime_status_key === "RUNTIME_STALLED" ? (
          <div className="missionAlert warn">
            <strong>{t(locale, "stallReason")}:</strong> {t(locale, runtime.stalled_reason_key || "STALL_UNKNOWN")}
          </div>
        ) : null}
        {runtime?.runtime_status_key === "RUNTIME_COMPLETED" ? (
          <div className="missionAlert ok">
            <strong>{t(locale, "completionReason")}:</strong> {t(locale, runtime.completion_reason_key || "COMPLETION_UNKNOWN")}
          </div>
        ) : null}
        {gateBlocked && diagnosis ? (
          <div className="missionAlert info">
            <strong>{t(locale, "objective")}:</strong> {t(locale, diagnosis.objective_key || "OBJECTIVE_STABILIZE_GENERALIZATION")} |{" "}
            <strong>{t(locale, "recommendedProfile")}:</strong> {t(locale, diagnosis.recommended_profile_key || "PROFILE_BASELINE")} |{" "}
            <strong>{t(locale, "confidenceScore")}:</strong> {formatPct(Number(diagnosis.confidence || 0))}
          </div>
        ) : null}
      </section>

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

      <section className="roadmapBlock">
        <div className="roadmapHead">
          <div>
            <div className="roadmapTitle">{t(locale, "roadmapTitle")}</div>
            <div className="roadmapHint">{t(locale, "roadmapHint")}</div>
            <div className="roadmapGate">
              {t(locale, "gateLabel")}: pass &gt;= {formatPct(roadmap?.gate?.min_validation_pass_rate ?? Number.NaN)} | alpha &gt;{" "}
              {formatNumber(roadmap?.gate?.min_all_window_alpha ?? Number.NaN, 2)} | deploy={" "}
              {roadmap?.gate?.require_deploy_ready ? t(locale, "readyYes") : t(locale, "readyNo")}
            </div>
          </div>
          <div className="roadmapStamp">
            {t(locale, "generatedAt")}: {roadmap?.generated_at_utc || t(locale, "na")}
          </div>
        </div>

        <div className="roadmapStats">
          <article className="card">
            <span className="label">{t(locale, "trainingStatus")}</span>
            <strong className="value">{t(locale, roadmap?.status_key || "TRAINING_STATUS_RUNNING")}</strong>
          </article>
          <article className="card">
            <span className="label">{t(locale, "streak")}</span>
            <strong className="value">
              {roadmap?.summary?.current_streak ?? 0}/{roadmap?.summary?.required_streak ?? 0}
            </strong>
          </article>
          <article className="card">
            <span className="label">{t(locale, "roundsTotal")}</span>
            <strong className="value">{roadmap?.summary?.rounds_total ?? 0}</strong>
          </article>
          <article className="card">
            <span className="label">{t(locale, "bestQuality")}</span>
            <strong className="value">{formatNumber(roadmap?.summary?.best_quality_score ?? Number.NaN, 3)}</strong>
          </article>
        </div>

        <div className="roadmapGrid">
          <article className="card chartCard">
            <div className="cardHeader">{t(locale, "roadmapTrend")}</div>
            {roadmapTrendOption ? (
              <ReactECharts option={roadmapTrendOption} style={{ height: 320 }} />
            ) : (
              <div className="empty">{t(locale, "roundsEmpty")}</div>
            )}
          </article>
          <article className="card roadmapList">
            <div className="cardHeader">{t(locale, "roadmapHistory")}</div>
            {recentRoadmapRounds.length ? (
              <ul className="roundList">
                {recentRoadmapRounds.map((row) => (
                  <li key={`${row.run_id}-${row.round_index}`} className={`roundItem ${row.gate_hit ? "hit" : "miss"}`}>
                    <div className="roundTop">
                      <span className="roundBadge">R{row.round_index}</span>
                      <span className="mono">{row.run_id || t(locale, "na")}</span>
                      <span className={`gateBadge ${row.gate_hit ? "ok" : "bad"}`}>
                        {row.gate_hit ? t(locale, "gateHit") : t(locale, "gateMiss")}
                      </span>
                    </div>
                    <div className="roundMetrics">
                      <span>
                        {t(locale, "passRate")}: {formatPct(row.validation_pass_rate)}
                      </span>
                      <span>
                        {t(locale, "alphaAll")}: {formatSigned(row.all_window_alpha)}
                      </span>
                      <span>
                        {t(locale, "vetoPressure")}: {formatPct(Math.max(row.veto_rate, row.failsafe_veto_all_rate))}
                      </span>
                    </div>
                    <div className="roundMeta">
                      <span>
                        {t(locale, "bottleneck")}: {row.primary_bottleneck || t(locale, "na")}
                      </span>
                      <span>
                        {t(locale, "action")}: {row.recommended_action || t(locale, "na")}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="empty">{t(locale, "roundsEmpty")}</div>
            )}
          </article>
          <article className="card diagnostics">
            <div className="cardHeader">
              {t(locale, "latestRound")} / {t(locale, "bestRound")}
            </div>
            <div className="diagnosticsGrid">
              <div>
                <span className="label">{t(locale, "latestRound")}</span>
                <strong className="mono">{latestRoadmapRound?.run_id || t(locale, "na")}</strong>
              </div>
              <div>
                <span className="label">{t(locale, "bestRound")}</span>
                <strong className="mono">{bestRoadmapRound?.run_id || t(locale, "na")}</strong>
              </div>
              <div>
                <span className="label">{t(locale, "qualityScore")}</span>
                <strong>{formatNumber(bestRoadmapRound?.quality_score ?? Number.NaN, 3)}</strong>
              </div>
              <div>
                <span className="label">{t(locale, "profile")}</span>
                <strong>{latestRoadmapRound?.round_profile || t(locale, "na")}</strong>
              </div>
              <div>
                <span className="label">{t(locale, "deployReady")}</span>
                <strong>{latestRoadmapRound?.deploy_ready ? t(locale, "readyYes") : t(locale, "readyNo")}</strong>
              </div>
              <div>
                <span className="label">{t(locale, "runId")}</span>
                <strong className="mono">{visualState?.run_id || t(locale, "na")}</strong>
              </div>
            </div>
          </article>
        </div>

        <div className="analysisGrid">
          <article className="card diagnosisCard">
            <div className="cardHeader">{t(locale, "diagnosisTitle")}</div>
            <div className="analysisHint">{t(locale, "diagnosisHint")}</div>
            <div className="diagnosisSummary">
              <div>
                <span className="label">{t(locale, "objective")}</span>
                <strong>{t(locale, diagnosis?.objective_key || "OBJECTIVE_STABILIZE_GENERALIZATION")}</strong>
              </div>
              <div>
                <span className="label">{t(locale, "recommendedProfile")}</span>
                <strong>{t(locale, diagnosis?.recommended_profile_key || "PROFILE_BASELINE")}</strong>
              </div>
              <div>
                <span className="label">{t(locale, "confidenceScore")}</span>
                <strong>{formatPct(Number(diagnosis?.confidence || 0))}</strong>
              </div>
            </div>
            <div className="bottleneckBlock">
              <div className="label">{t(locale, "topBottlenecks")}</div>
              {(diagnosis?.top_bottlenecks || []).length ? (
                <ul className="bottleneckList">
                  {(diagnosis?.top_bottlenecks || []).map((item, idx) => (
                    <li key={`${item.reason_key}-${idx}`}>
                      <span className="rank">#{idx + 1}</span>
                      <span className="reason">{t(locale, item.reason_key || "REASON_UNKNOWN")}</span>
                      <span className="severity">{formatPct(Number(item.severity || 0))}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="empty">{t(locale, "na")}</div>
              )}
            </div>
          </article>

          <article className="card profileTableCard">
            <div className="cardHeader">{t(locale, "profileCompareTitle")}</div>
            <div className="analysisHint">{t(locale, "profileCompareHint")}</div>
            <div className="winnerLine">
              <span className="label">{t(locale, "winnerProfile")}</span>
              <strong>{t(locale, roadmap?.profile_comparison?.winner_profile_key || "PROFILE_UNKNOWN")}</strong>
            </div>
            {profileComparisonRows.length ? (
              <div className="profileTableWrap">
                <table className="profileTable">
                  <thead>
                    <tr>
                      <th>{t(locale, "profileName")}</th>
                      <th>{t(locale, "roundCount")}</th>
                      <th>{t(locale, "avgPassRate")}</th>
                      <th>{t(locale, "avgAlpha")}</th>
                      <th>{t(locale, "avgVeto")}</th>
                      <th>{t(locale, "avgQuality")}</th>
                      <th>{t(locale, "gateHitRate")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {profileComparisonRows.slice(0, 6).map((row) => (
                      <tr key={`${row.profile_key}-${row.rounds}`}>
                        <td>{t(locale, row.profile_key || "PROFILE_UNKNOWN")}</td>
                        <td>{row.rounds}</td>
                        <td>{formatPct(row.avg_pass_rate)}</td>
                        <td>{formatSigned(row.avg_all_window_alpha)}</td>
                        <td>{formatPct(row.avg_veto_pressure)}</td>
                        <td>{formatNumber(row.avg_quality_score, 3)}</td>
                        <td>{formatPct(row.gate_hit_rate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty">{t(locale, "na")}</div>
            )}
          </article>
        </div>
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

      <div className="toastStack">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toastItem ${toast.level}`}>
            <span>{toast.message}</span>
            <button
              type="button"
              className="toastClose"
              onClick={() => setToasts((prev) => prev.filter((item) => item.id !== toast.id))}
            >
              {t(locale, "toastClose")}
            </button>
          </div>
        ))}
      </div>
    </main>
  );
}

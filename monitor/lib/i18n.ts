import type { LocaleCode } from "./types";

type Dict = Record<string, string>;
type LocalePack = {
  ui: Dict;
  enums: Dict;
};

const packs: Record<LocaleCode, LocalePack> = {
  "zh-TW": {
    ui: {
      title: "LEIMAI ORACLE 量化治理儀表板",
      subtitle: "客戶信任層 + CEO 演化層",
      toggle: "切換語言",
      marketRegime: "市場型態",
      liveAlpha: "即時 Alpha vs Spot",
      maxDrawdown: "最大回撤",
      heartbeat: "系統心跳",
      heartbeatLive: "同步中",
      heartbeatStale: "待同步",
      lastSynced: "最後同步",
      ceoPanel: "CEO 演化層",
      ceoHint: "展開查看穩健性雷達、拒絕原因與 Meta 診斷",
      robustnessRadar: "穩健性雷達",
      rejectionPie: "拒絕原因分布",
      diagnostics: "Meta 診斷",
      vetoRate: "Veto 比例",
      threshold: "採用門檻",
      precisionFloor: "Precision Floor",
      compliance: "Floor 合規率",
      failsafeRate: "Failsafe 觸發率",
      runId: "執行批次",
      na: "無資料",
      radarPbo: "PBO",
      radarDsr: "DSR",
      radarF1: "F1",
      radarFloor: "合規率"
    },
    enums: {
      STATUS_VETO_ALL: "全面否決保護",
      STATUS_STALLED: "策略停滯",
      STATUS_RECOVERY: "恢復階段",
      STATUS_STABLE: "穩定運行",
      REGIME_VETO_HOLD: "風控凍結",
      REGIME_CONSOLIDATION: "盤整",
      REGIME_EXPANSION: "擴張",
      REASON_ALL_WINDOW_ALPHA: "全窗 Alpha 未達標",
      REASON_CV_FAIL: "Purged CV 未通過",
      REASON_DSR_BELOW_MIN: "DSR 低於門檻",
      REASON_FINAL_SCORE_LOW: "最終分數不足",
      REASON_FRICTION_WEAK: "交易摩擦韌性不足",
      REASON_HIGH_PBO: "PBO 過高",
      REASON_LOW_PRECISION: "Precision Floor 不達標",
      REASON_WF_FAIL: "Walk-Forward 未通過",
      REASON_UNKNOWN: "未知原因"
    }
  },
  "en-US": {
    ui: {
      title: "LEIMAI ORACLE Quant Governance Dashboard",
      subtitle: "Client Trust Layer + CEO Evolution Layer",
      toggle: "Toggle language",
      marketRegime: "Market Regime",
      liveAlpha: "Live Alpha vs Spot",
      maxDrawdown: "Max Drawdown",
      heartbeat: "System Heartbeat",
      heartbeatLive: "Synced",
      heartbeatStale: "Awaiting sync",
      lastSynced: "Last synced",
      ceoPanel: "CEO Evolution Layer",
      ceoHint: "Expand for robustness radar, rejection causes, and meta diagnostics",
      robustnessRadar: "Robustness Radar",
      rejectionPie: "Rejection Breakdown",
      diagnostics: "Meta Diagnostics",
      vetoRate: "Veto Rate",
      threshold: "Chosen Threshold",
      precisionFloor: "Precision Floor",
      compliance: "Floor Compliance",
      failsafeRate: "Failsafe Trigger Rate",
      runId: "Run ID",
      na: "No data",
      radarPbo: "PBO",
      radarDsr: "DSR",
      radarF1: "F1",
      radarFloor: "Compliance"
    },
    enums: {
      STATUS_VETO_ALL: "Veto-All Safeguard",
      STATUS_STALLED: "Stalled",
      STATUS_RECOVERY: "Recovery",
      STATUS_STABLE: "Stable",
      REGIME_VETO_HOLD: "Veto-Hold",
      REGIME_CONSOLIDATION: "Consolidation",
      REGIME_EXPANSION: "Expansion",
      REASON_ALL_WINDOW_ALPHA: "All-window Alpha below target",
      REASON_CV_FAIL: "Purged CV failed",
      REASON_DSR_BELOW_MIN: "DSR below threshold",
      REASON_FINAL_SCORE_LOW: "Final score below threshold",
      REASON_FRICTION_WEAK: "Friction robustness weak",
      REASON_HIGH_PBO: "PBO above threshold",
      REASON_LOW_PRECISION: "Precision floor unmet",
      REASON_WF_FAIL: "Walk-forward failed",
      REASON_UNKNOWN: "Unknown reason"
    }
  }
};

const ASIA_LANG_PREFIXES = ["zh", "ja", "ko", "th", "vi", "id", "ms", "ar", "hi"];

export function detectDefaultLocale(): LocaleCode {
  if (typeof window === "undefined") {
    return "en-US";
  }
  const language = (window.navigator.language || "").toLowerCase();
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  if (ASIA_LANG_PREFIXES.some((prefix) => language.startsWith(prefix))) {
    return "zh-TW";
  }
  if (timeZone.startsWith("Asia/")) {
    return "zh-TW";
  }
  return "en-US";
}

export function t(locale: LocaleCode, key: string): string {
  const pack = packs[locale] || packs["en-US"];
  return pack.ui[key] ?? pack.enums[key] ?? key;
}

export function getNextLocale(locale: LocaleCode): LocaleCode {
  return locale === "zh-TW" ? "en-US" : "zh-TW";
}

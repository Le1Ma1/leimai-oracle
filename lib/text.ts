import type { SupportedLocale } from "@/lib/i18n";

const LABELS: Record<SupportedLocale, Record<string, string>> = {
  en: {
    title: "Project Panopticon",
    subtitle: "Historical in-sample optimization library for crypto parameter exploration.",
    methodology: "Methodology",
    summaries: "Summaries",
    atlas: "Atlas",
    disclaimerA: "IN_SAMPLE_ONLY",
    disclaimerB: "NOT_FINANCIAL_ADVICE",
    disclaimerC: "PAST_PERFORMANCE_NOT_PREDICTIVE",
    analysisPrefix: "In this slice, the selected combination reached a historical in-sample maximum after friction adjustment."
  },
  "zh-TW": {
    title: "Project Panopticon",
    subtitle: "加密參數歷史樣本內最佳化展示庫。",
    methodology: "方法論",
    summaries: "摘要",
    atlas: "參數圖譜",
    disclaimerA: "僅樣本內結果",
    disclaimerB: "非投資建議",
    disclaimerC: "歷史績效不代表未來",
    analysisPrefix: "在此切片中，選定組合在扣除摩擦成本後達到歷史樣本內最高值。"
  },
  ko: {
    title: "Project Panopticon",
    subtitle: "암호화폐 파라미터 역사 인샘플 최적화 라이브러리.",
    methodology: "방법론",
    summaries: "요약",
    atlas: "아틀라스",
    disclaimerA: "인샘플 결과 전용",
    disclaimerB: "투자 조언 아님",
    disclaimerC: "과거 성과는 미래를 보장하지 않음",
    analysisPrefix: "이 구간에서 선택 조합은 마찰 비용 반영 후 인샘플 최대값을 기록했습니다."
  },
  tr: {
    title: "Project Panopticon",
    subtitle: "Kripto parametreleri icin tarihsel in-sample optimizasyon kutuphanesi.",
    methodology: "Metodoloji",
    summaries: "Ozetler",
    atlas: "Atlas",
    disclaimerA: "SADECE_IN_SAMPLE",
    disclaimerB: "YATIRIM_TAVSIYESI_DEGIL",
    disclaimerC: "GECMIS_GETIRI_GELECEK_GARANTISI_DEGIL",
    analysisPrefix: "Bu kesitte secilen kombinasyon, surtunme maliyeti sonrasi tarihsel in-sample zirveyi verdi."
  },
  vi: {
    title: "Project Panopticon",
    subtitle: "Thu vien toi uu tham so in-sample lich su cho crypto.",
    methodology: "Phuong phap",
    summaries: "Tong hop",
    atlas: "Atlas",
    disclaimerA: "CHI_IN_SAMPLE",
    disclaimerB: "KHONG_PHAI_KHUYEN_NGHI_DAU_TU",
    disclaimerC: "HIEU_SUAT_QUA_KHU_KHONG_DAM_BAO_TUONG_LAI",
    analysisPrefix: "Trong lat cat nay, to hop da dat dinh lich su in-sample sau khi tru chi phi ma sat."
  }
};

export function t(locale: SupportedLocale, key: string): string {
  return LABELS[locale][key] ?? LABELS.en[key] ?? key;
}

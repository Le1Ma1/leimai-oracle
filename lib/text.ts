import type { SupportedLocale } from "@/lib/i18n";

const LABELS: Record<SupportedLocale, Record<string, string>> = {
  en: {
    title: "LeiMai Oracle",
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
    title: "LeiMai Oracle",
    subtitle: "Li shi in-sample can shu you hua zhan shi ku.",
    methodology: "Fang fa lun",
    summaries: "Zong jie",
    atlas: "Can shu tu pu",
    disclaimerA: "JIN_GONG_IN_SAMPLE",
    disclaimerB: "FEI_TOU_ZI_JIAN_YI",
    disclaimerC: "GUO_QU_BIAO_XIAN_BU_DAI_BIAO_WEI_LAI",
    analysisPrefix: "Zai ci qie pian zhong, suo xuan zu he zai kou chu mo ca cheng ben hou da dao li shi in-sample gao dian."
  },
  ko: {
    title: "LeiMai Oracle",
    subtitle: "History in-sample optimization library for crypto parameters.",
    methodology: "Methodology",
    summaries: "Summaries",
    atlas: "Atlas",
    disclaimerA: "IN_SAMPLE_ONLY",
    disclaimerB: "NOT_FINANCIAL_ADVICE",
    disclaimerC: "PAST_PERFORMANCE_NOT_PREDICTIVE",
    analysisPrefix: "In this slice, the selected combination reached a historical in-sample maximum after friction adjustment."
  },
  tr: {
    title: "LeiMai Oracle",
    subtitle: "Kripto parametreleri icin tarihsel in-sample optimizasyon kutuphanesi.",
    methodology: "Metodoloji",
    summaries: "Ozetler",
    atlas: "Atlas",
    disclaimerA: "SADECE_IN_SAMPLE",
    disclaimerB: "YATIRIM_TAVSIYESI_DEGIL",
    disclaimerC: "GECMIS_GETIRI_GELECEK_GARANTISI_DEGIL",
    analysisPrefix: "Bu kesitte secilen kombinasyon surtunme maliyeti sonrasi tarihsel in-sample zirveyi verdi."
  },
  vi: {
    title: "LeiMai Oracle",
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


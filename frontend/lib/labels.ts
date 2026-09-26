export const STATUS_KO: Record<string, string> = {
  BACKLOG: "대기", PLANNED: "계획", RESEARCHING: "조사 중", ANALYZING: "분석 중", WRITING: "작성 중", REVIEWING: "검토 중",
  WAITING_USER: "CEO 결재 대기", DONE: "완료", FAILED: "실패",
};
export const VERIF_KO: Record<string, [string, string]> = {
  verified: ["확인됨", "bg-mint text-ink"], partially_verified: ["부분확인", "bg-sky text-ink"], unverified: ["미확인", "bg-rose text-ink"],
  contradicted: ["충돌", "bg-orange-400 text-ink"], outdated: ["오래됨", "bg-yellow-300 text-ink"],
};
export const KIND_KO: Record<string, [string, string]> = {
  FACT: ["사실", "text-emerald-300"], ANALYSIS: ["분석", "text-sky-300"], ASSUMPTION: ["가정", "text-amber-300"],
  ESTIMATE: ["추정", "text-violet-300"], OPINION: ["의견", "text-gray-300"], UNKNOWN: ["미확인", "text-rose-300"],
};
export const RISK_COLOR: Record<string, string> = { LOW: "bg-mint text-ink", MEDIUM: "bg-sky text-ink", HIGH: "bg-orange-400 text-ink", CRITICAL: "bg-rose text-ink" };
export const TIER_KO: Record<number, string> = { 1: "정부·공공", 2: "공식 기업", 3: "학술", 4: "국제기구", 5: "전문기관", 6: "언론", 7: "기타" };

export function bar(pct: number, width = 10): string {
  const n = Math.round((Math.max(0, Math.min(100, pct)) / 100) * width);
  return "█".repeat(n) + "░".repeat(width - n);
}
export function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "방금";
  if (s < 3600) return `${Math.floor(s / 60)}분 전`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
  return new Date(iso).toLocaleDateString("ko-KR");
}

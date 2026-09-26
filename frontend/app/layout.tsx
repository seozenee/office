import "galmuri/dist/galmuri.css";
import "./globals.css";
import type { Metadata } from "next";
import AppShell from "@/components/AppShell";

export const metadata: Metadata = {
  title: "Personal AI Office",
  description: "나를 위해 일하는 개인 AI 회사 — 조사 → 분석 → 문서 → 검증 → 결재",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}

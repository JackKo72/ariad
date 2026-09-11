import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ARIAD",
  description: "진료 대화를 구조화하고 환자용 설명 초안을 만드는 의료진 보조 도구",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}

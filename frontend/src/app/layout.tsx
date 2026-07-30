import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "검색 기록 찾기",
  description: "내가 봤던 페이지를 자연어로 다시 찾아 주는 채팅",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="ko"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      {/* h-screen + overflow-hidden: 메시지 목록만 스크롤되고 입력창은 하단에 고정된다. */}
      <body className="flex h-screen flex-col overflow-hidden">{children}</body>
    </html>
  );
}

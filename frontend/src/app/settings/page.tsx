import type { Metadata } from "next";

import { SettingsForm, SettingsHeader } from "@/components/settings/SettingsForm";

export const metadata: Metadata = {
  title: "설정 · 검색 기록 찾기",
  description: "답변에 쓰는 AI 모델과 Gemini API key를 지정합니다",
};

export default function SettingsPage() {
  // 루트 레이아웃이 body 를 h-screen overflow-hidden 으로 잡아 두었으므로(채팅 입력창을 아래에
  // 고정하기 위한 것), 이 페이지는 스크롤 영역을 스스로 만들어야 한다.
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-zinc-50 dark:bg-zinc-950">
      <SettingsHeader />
      <div className="flex-1 overflow-y-auto">
        <main className="mx-auto w-full max-w-2xl px-4 py-6">
          <SettingsForm />
        </main>
      </div>
    </div>
  );
}

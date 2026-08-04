"use client";

import { useEffect, useRef, useState } from "react";

import { MessageBubble, PendingBubble } from "@/components/chat/MessageBubble";
import type { ChatMessage } from "@/lib/types";
import type { ChatStatus } from "@/hooks/useChatSessions";

interface MessageListProps {
  messages: ChatMessage[];
  status: ChatStatus;
  onPickSuggestion: (text: string) => void;
}

const SUGGESTIONS = [
  "어제 봤던 리액트 상태관리 글 찾아줘",
  "지난주에 읽은 도커 컴포즈 설정 문서",
  "전에 본 파이썬 비동기 관련 글",
  "저번에 찾아봤던 서울 맛집 페이지",
];

/** 사용자가 위로 스크롤했는지 판단하는 여유값(px) */
const STICK_THRESHOLD = 80;

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 px-4 text-center">
      <div className="space-y-2">
        <h2 className="bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-2xl font-semibold tracking-tight text-transparent">
          기억나는 대로 물어보세요
        </h2>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          내가 봤던 페이지를 찾아 줍니다. 아래 예시를 눌러 시작할 수 있어요.
        </p>
      </div>
      <div className="grid w-full max-w-2xl gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => onPick(suggestion)}
            className="rounded-xl border border-zinc-200 bg-white px-4 py-3 text-left text-sm text-zinc-700 shadow-sm transition-all hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:border-blue-900/60"
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}

export function MessageList({ messages, status, onPickSuggestion }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [stickToBottom, setStickToBottom] = useState(true);

  // 사용자가 위로 올려 이전 대화를 읽는 중이면 자동 스크롤을 멈춘다.
  useEffect(() => {
    const container = scrollRef.current;
    if (container === null || !stickToBottom) return;
    container.scrollTop = container.scrollHeight;
  }, [messages, status, stickToBottom]);

  function handleScroll() {
    const container = scrollRef.current;
    if (container === null) return;
    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    setStickToBottom(distanceFromBottom <= STICK_THRESHOLD);
  }

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className="flex-1 overflow-y-auto overscroll-contain bg-gradient-to-b from-zinc-50/60 to-transparent dark:from-zinc-950/40"
    >
      {messages.length === 0 ? (
        <EmptyState onPick={onPickSuggestion} />
      ) : (
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-6">
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          {status === "loading" && <PendingBubble />}
        </div>
      )}
    </div>
  );
}

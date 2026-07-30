"use client";

import type { ChatMessage, SearchResult } from "@/lib/types";

interface MessageBubbleProps {
  message: ChatMessage;
}

/** 말풍선 껍데기. 아바타와 배경색만 담당해 실제/로딩 말풍선이 같은 모양을 갖게 한다. */
function Bubble({ isUser, children }: { isUser: boolean; children: React.ReactNode }) {
  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      <div
        aria-hidden
        className={`mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold select-none ${
          isUser
            ? "bg-blue-600 text-white"
            : "bg-zinc-200 text-zinc-700 dark:bg-zinc-700 dark:text-zinc-200"
        }`}
      >
        {isUser ? "나" : "AI"}
      </div>

      <div
        className={`min-w-0 max-w-[min(46rem,85%)] rounded-2xl px-4 py-3 text-[15px] leading-relaxed ${
          isUser
            ? "rounded-tr-sm bg-blue-600 text-white"
            : "rounded-tl-sm bg-zinc-100 text-zinc-900 dark:bg-zinc-800/80 dark:text-zinc-100"
        }`}
      >
        {children}
      </div>
    </div>
  );
}

/** 표시용 도메인. 파싱할 수 없는 URL 이면 원문을 그대로 보여준다. */
function displayHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function ResultCard({ result }: { result: SearchResult }) {
  return (
    <a
      href={result.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block space-y-1 transition-opacity hover:opacity-70"
    >
      <span className="block font-medium break-words text-blue-700 underline decoration-blue-300 underline-offset-2 dark:text-blue-300 dark:decoration-blue-700">
        {result.title}
      </span>
      <span className="block text-xs break-all text-zinc-500 dark:text-zinc-400">
        {displayHost(result.url)}
      </span>
    </a>
  );
}

/** 백엔드 응답을 기다리는 동안 보여 줄 assistant 말풍선. */
export function PendingBubble() {
  return (
    <Bubble isUser={false}>
      <span className="flex items-center gap-1 py-1" aria-label="검색 중">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="size-2 animate-bounce rounded-full bg-current opacity-40"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </span>
    </Bubble>
  );
}

export function MessageBubble({ message }: MessageBubbleProps) {
  if (message.role === "user") {
    return (
      <Bubble isUser>
        <p className="whitespace-pre-wrap break-words">{message.content}</p>
      </Bubble>
    );
  }

  return (
    <Bubble isUser={false}>
      {message.result === null ? (
        <p className="text-zinc-500 dark:text-zinc-400">
          관련된 검색 기록을 찾지 못했습니다. 다른 표현으로 물어봐 주세요.
        </p>
      ) : (
        <ResultCard result={message.result} />
      )}
    </Bubble>
  );
}

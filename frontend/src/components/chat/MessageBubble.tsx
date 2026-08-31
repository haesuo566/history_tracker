"use client";

import { formatVisitedAt } from "@/lib/clock";
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
        className={`mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white shadow-sm select-none ${
          isUser
            ? "bg-gradient-to-br from-blue-600 to-indigo-600 shadow-blue-600/30"
            : "bg-gradient-to-br from-zinc-700 to-zinc-900 shadow-zinc-900/20 dark:from-zinc-600 dark:to-zinc-800"
        }`}
      >
        {isUser ? "나" : "AI"}
      </div>

      <div
        className={`min-w-0 max-w-[min(46rem,85%)] rounded-2xl px-4 py-3 text-[15px] leading-relaxed shadow-sm ${
          isUser
            ? "rounded-tr-sm bg-gradient-to-br from-blue-600 to-indigo-600 text-white"
            : "rounded-tl-sm bg-white text-zinc-900 ring-1 ring-zinc-200/70 dark:bg-zinc-800/80 dark:text-zinc-100 dark:ring-zinc-700/60"
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
  const visited = formatVisitedAt(result.visitedAt);

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
        {visited !== null && <span className="whitespace-nowrap"> · {visited}</span>}
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

  const hasAnswer = message.answer !== null;
  const hasResults = message.results.length > 0;

  return (
    <Bubble isUser={false}>
      <div className="space-y-3">
        {hasAnswer && <p className="whitespace-pre-wrap break-words">{message.answer}</p>}
        {hasResults ? (
          message.results.map((result) => <ResultCard key={result.url} result={result} />)
        ) : !hasAnswer ? (
          <p className="text-zinc-500 dark:text-zinc-400">
            관련된 검색 기록을 찾지 못했습니다. 다른 표현으로 물어봐 주세요.
          </p>
        ) : null}
      </div>
    </Bubble>
  );
}

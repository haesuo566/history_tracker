"use client";

import Link from "next/link";
import { useState } from "react";

import { BATCH_LABEL } from "@/components/chat/BatchControl";
import { useSettings } from "@/hooks/useSettings";
import type {
  EmbeddingProvider,
  ModelOption,
  ReindexSummary,
  SettingsBody,
  SettingsUpdateBody,
} from "@/lib/types";

function BackIcon() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-4">
      <path
        d="M9.5 3.5 5 8l4.5 4.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Spinner() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-3.5 animate-spin">
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="2" strokeOpacity="0.25" />
      <path d="M8 2a6 6 0 0 1 6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/** 화면이 편집 중인 값. */
interface Draft {
  answerModel: string;
  queryRewriteModel: string;
  embeddingProvider: EmbeddingProvider;
  embeddingModel: string;
  teiBaseUrl: string;
  teiModel: string;
  /** 비어 있으면 '키를 바꾸지 않음'이다. 저장된 키 원문은 화면으로 내려오지 않는다. */
  apiKey: string;
}

/**
 * 편집 상태를 Draft 통째로 들고 있지 않고 '사용자가 만진 항목'만 들고 있다가 서버 값에 덮어씌운다.
 *
 * 통째로 들고 있으면 저장에 성공한 뒤 서버가 돌려준 값으로 되돌리는 동기화가 필요한데, 그것은
 * effect 안에서 상태를 다시 쓰는 일이 된다. 만진 것만 들고 있으면 저장 성공 시 그 목록을 비우는
 * 것으로 끝나고, 표시값은 항상 서버 값에서 파생된다.
 */
type Overrides = Partial<Draft>;

function draftOf(settings: SettingsBody, overrides: Overrides): Draft {
  return {
    answerModel: settings.answer_model,
    queryRewriteModel: settings.query_rewrite_model,
    embeddingProvider: settings.embedding_provider,
    embeddingModel: settings.embedding_model,
    teiBaseUrl: settings.tei_base_url,
    teiModel: settings.tei_model,
    apiKey: "",
    ...overrides,
  };
}

function changesOf(draft: Draft, settings: SettingsBody): SettingsUpdateBody {
  const updates: SettingsUpdateBody = {};
  if (draft.answerModel !== settings.answer_model) updates.answer_model = draft.answerModel;
  if (draft.queryRewriteModel !== settings.query_rewrite_model) {
    updates.query_rewrite_model = draft.queryRewriteModel;
  }
  if (draft.embeddingProvider !== settings.embedding_provider) {
    updates.embedding_provider = draft.embeddingProvider;
  }
  // 지금 고른 제공자와 무관한 항목은 보내지 않는다. Gemini 를 쓰는 중에 TEI 주소를 함께 보내면
  // 백엔드가 쓰지도 않을 값을 저장하고, 화면은 바꾼 것이 있다고 표시한다.
  if (draft.embeddingProvider === "gemini") {
    if (draft.embeddingModel !== settings.embedding_model) updates.embedding_model = draft.embeddingModel;
  } else {
    const baseUrl = draft.teiBaseUrl.trim();
    if (baseUrl !== settings.tei_base_url) updates.tei_base_url = baseUrl;
    const teiModel = draft.teiModel.trim();
    if (teiModel !== settings.tei_model) updates.tei_model = teiModel;
  }
  if (draft.apiKey.trim().length > 0) updates.gemini_api_key = draft.apiKey.trim();
  return updates;
}

/** 저장 버튼을 누르지 못하게 막을 이유가 있으면 그 문구를, 없으면 null. */
function blockedReason(draft: Draft): string | null {
  if (draft.embeddingProvider !== "tei") return null;
  const baseUrl = draft.teiBaseUrl.trim();
  if (baseUrl.length === 0) return "TEI 주소를 입력해야 저장할 수 있습니다.";
  if (!/^https?:\/\//.test(baseUrl)) return "TEI 주소는 http:// 또는 https:// 로 시작해야 합니다.";
  return null;
}

const INPUT_CLASS =
  "w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-900 transition-colors hover:border-zinc-300 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-zinc-700";

const SELECT_CLASS =
  "w-full appearance-none rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-900 transition-colors hover:border-zinc-300 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-zinc-700";

interface FieldProps {
  id: string;
  label: string;
  hint: string;
  children: React.ReactNode;
}

function Field({ id, label, hint, children }: FieldProps) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-zinc-800 dark:text-zinc-100">
        {label}
      </label>
      <p id={`${id}-hint`} className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
        {hint}
      </p>
      {children}
    </div>
  );
}

interface ModelSelectProps {
  id: string;
  value: string;
  options: ModelOption[];
  disabled: boolean;
  onChange: (value: string) => void;
}

function ModelSelect({ id, value, options, disabled, onChange }: ModelSelectProps) {
  return (
    <select
      id={id}
      value={value}
      disabled={disabled}
      aria-describedby={`${id}-hint`}
      onChange={(event) => onChange(event.target.value)}
      className={SELECT_CLASS}
    >
      {options.map((option) => (
        <option key={option.id} value={option.id}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-5 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="text-sm font-semibold tracking-tight text-zinc-800 dark:text-zinc-100">{title}</h2>
      {children}
    </section>
  );
}

function Notice({ tone, children }: { tone: "info" | "warn" | "error"; children: React.ReactNode }) {
  const palette = {
    info: "border-zinc-200 bg-zinc-50 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-300",
    warn: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-300",
    error: "border-red-200 bg-red-50 text-red-600 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-400",
  }[tone];

  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-xl border px-4 py-3 text-sm leading-relaxed ${palette}`}
    >
      {children}
    </div>
  );
}

export function SettingsForm() {
  const { settings, status, error, isSaved, save, reindex, retry, clearSavedMark } = useSettings();
  const [overrides, setOverrides] = useState<Overrides>({});
  // 저장이 끝나면 편집 중이라는 표시가 사라지므로, 무엇을 바꿨다는 안내는 따로 들고 있어야 한다.
  const [embeddingChanged, setEmbeddingChanged] = useState(false);
  const [confirmingReindex, setConfirmingReindex] = useState(false);
  const [reindexResult, setReindexResult] = useState<ReindexSummary | null>(null);

  const isSaving = status === "saving";
  const isReindexing = status === "reindexing";
  const isBusy = isSaving || isReindexing;

  if (status === "loading" || (settings === null && status !== "failed")) {
    return (
      <div className="space-y-4" aria-busy>
        {[0, 1].map((key) => (
          <div key={key} className="h-48 animate-pulse rounded-xl bg-zinc-200/70 dark:bg-zinc-800/60" />
        ))}
      </div>
    );
  }

  if (settings === null) {
    return (
      <div className="space-y-3">
        <Notice tone="error">{error ?? "설정을 불러오지 못했습니다."}</Notice>
        <button
          type="button"
          onClick={retry}
          className="rounded-lg border border-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-600 transition-colors hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 dark:border-zinc-800 dark:text-zinc-300 dark:hover:border-blue-900/60 dark:hover:bg-blue-950/30"
        >
          다시 시도
        </button>
      </div>
    );
  }

  const draft = draftOf(settings, overrides);
  const updates = changesOf(draft, settings);
  const blocked = blockedReason(draft);
  const hasChanges = Object.keys(updates).length > 0;
  // 모델은 그대로인데 청크만 예전 기준인 경우. 벡터는 쓸 수 있으니 경고의 무게가 다르다.
  const chunkSizeStale =
    settings.expected_chunk_chars !== null &&
    settings.expected_chunk_chars !== settings.indexed_chunk_chars;

  function edit(patch: Overrides) {
    setOverrides((previous) => ({ ...previous, ...patch }));
    clearSavedMark();
    setEmbeddingChanged(false);
    setReindexResult(null);
    setConfirmingReindex(false);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!hasChanges || blocked !== null) return;

    // 임베딩이 달라졌는지는 저장 전에 판단해야 한다. 저장하면 서버 값이 갱신돼 차이가 사라진다.
    const changesEmbedding =
      updates.embedding_provider !== undefined ||
      updates.embedding_model !== undefined ||
      updates.tei_base_url !== undefined ||
      updates.tei_model !== undefined;

    const saved = await save(updates);
    // 저장된 값은 이제 서버가 돌려준 settings 에 있다. 만졌던 것을 비우면 표시값이 그쪽으로 넘어간다.
    if (saved) {
      setOverrides({});
      setEmbeddingChanged(changesEmbedding);
    }
  }

  async function handleReindex() {
    const summary = await reindex();
    setConfirmingReindex(false);
    if (summary !== null) {
      setReindexResult(summary);
      setEmbeddingChanged(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error !== null && <Notice tone="error">{error}</Notice>}

      {isSaved && <Notice tone="info">설정을 저장했습니다.</Notice>}

      <Section title="AI 모델">
        <Field
          id="answer-model"
          label="답변 생성"
          hint="찾은 기록과 본문을 근거로 답변 문장을 만드는 모델입니다."
        >
          <ModelSelect
            id="answer-model"
            value={draft.answerModel}
            options={settings.generation_models}
            disabled={isBusy}
            onChange={(value) => edit({ answerModel: value })}
          />
        </Field>

        <Field
          id="query-rewrite-model"
          label="질의 재작성"
          hint="질문의 의도를 판단하고 검색어로 다시 쓰는 모델입니다. 매 질문마다 한 번 불립니다."
        >
          <ModelSelect
            id="query-rewrite-model"
            value={draft.queryRewriteModel}
            options={settings.generation_models}
            disabled={isBusy}
            onChange={(value) => edit({ queryRewriteModel: value })}
          />
        </Field>

      </Section>

      <Section title="임베딩">
        <Field
          id="embedding-provider"
          label="제공자"
          hint={`기록 본문을 벡터로 바꿔 색인하고 검색하는 쪽입니다. 지금 색인은 ${settings.indexed_dim}차원, 청크 ${settings.indexed_chunk_chars}자로 만들어져 있습니다.`}
        >
          <ModelSelect
            id="embedding-provider"
            value={draft.embeddingProvider}
            options={settings.embedding_providers}
            disabled={isBusy}
            onChange={(value) => edit({ embeddingProvider: value as EmbeddingProvider })}
          />
        </Field>

        {draft.embeddingProvider === "gemini" ? (
          <Field
            id="embedding-model"
            label="Gemini 임베딩 모델"
            hint={`본문을 ${settings.embedding_dim}차원 벡터로 바꿉니다. 차원은 .env(EMBEDDING_DIM)가 정합니다.`}
          >
            <ModelSelect
              id="embedding-model"
              value={draft.embeddingModel}
              options={settings.embedding_models}
              disabled={isBusy}
              onChange={(value) => edit({ embeddingModel: value })}
            />
          </Field>
        ) : (
          <>
            <Field
              id="tei-base-url"
              label="TEI 주소"
              hint="OpenAI 호환 임베딩 경로를 제공하는 서버 주소입니다. /v1/embeddings 는 붙이지 않아도 됩니다."
            >
              <input
                id="tei-base-url"
                type="url"
                value={draft.teiBaseUrl}
                disabled={isBusy}
                autoComplete="off"
                spellCheck={false}
                aria-describedby="tei-base-url-hint"
                placeholder="http://127.0.0.1:8080"
                onChange={(event) => edit({ teiBaseUrl: event.target.value })}
                className={`${INPUT_CLASS} font-mono`}
              />
            </Field>

            <Field
              id="tei-model"
              label="모델 이름 (선택)"
              hint="TEI 는 서버에 올려 둔 모델 하나를 쓰므로 비워 둘 수 있습니다. 적어 두면 어떤 임베딩으로 색인했는지 구분하는 데 쓰입니다."
            >
              <input
                id="tei-model"
                type="text"
                value={draft.teiModel}
                disabled={isBusy}
                autoComplete="off"
                spellCheck={false}
                aria-describedby="tei-model-hint"
                placeholder="BAAI/bge-m3"
                onChange={(event) => edit({ teiModel: event.target.value })}
                className={`${INPUT_CLASS} font-mono`}
              />
            </Field>
          </>
        )}

        {blocked !== null && (
          <p className="text-xs leading-relaxed text-amber-700 dark:text-amber-400">{blocked}</p>
        )}

        {embeddingChanged && (
          <p className="text-xs leading-relaxed text-amber-700 dark:text-amber-400">
            저장했습니다. 아직 색인은 예전 임베딩으로 남아 있어 아래에서 다시 만들어야 합니다.
          </p>
        )}
      </Section>

      <Section title="색인">
        {!settings.vector_search_active ? (
          <Notice tone="warn">
            색인이 지금 임베딩과 다른 모델로 만들어져 있습니다. 예전 벡터는 다른 공간의 좌표라 검색에
            쓸 수 없어, 지금은 <strong>본문 단어 검색만</strong> 동작합니다. 아래에서 색인을 다시 만들어
            주세요.
          </Notice>
        ) : chunkSizeStale ? (
          <Notice tone="warn">
            색인의 청크가 {settings.indexed_chunk_chars}자로 잘려 있는데, 지금 임베딩이 한 번에 받는
            분량은 {settings.expected_chunk_chars}자입니다. 벡터 검색은 계속 동작하지만, 한계를 넘긴
            부분은 임베딩에 반영되지 않아 그만큼 검색에서 빠집니다. 다시 만들면 맞춰집니다.
          </Notice>
        ) : (
          <p className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
            색인이 지금 임베딩과 맞습니다. 임베딩을 바꾸지 않았다면 다시 만들 필요가 없습니다.
          </p>
        )}

        {reindexResult !== null && (
          <Notice tone="info">
            색인을 비웠습니다{reindexResult.recreated ? ` (${reindexResult.dim}차원으로 다시 만듦)` : ""}.
            앞으로 청크 하나에 {reindexResult.chunk_chars}자씩 담습니다.
            {reindexResult.pending > 0 ? (
              <>
                {" "}
                기록 {reindexResult.pending}건을 다시 색인해야 합니다 — 채팅 화면의 &lsquo;{BATCH_LABEL}
                &rsquo; 버튼을 눌러 주세요.
              </>
            ) : (
              " 색인할 기록이 없습니다."
            )}
          </Notice>
        )}

        {confirmingReindex ? (
          <div className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-900/50 dark:bg-amber-950/30">
            <p className="text-sm leading-relaxed text-amber-800 dark:text-amber-300">
              색인을 통째로 비웁니다. 되돌릴 수 없습니다. 수집한 기록 본문은 그대로 남고, 청크·벡터·단어
              색인만 지워집니다. 다시 쌓는 데는 기록 수만큼 임베딩 호출이 듭니다.
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleReindex}
                disabled={isBusy}
                aria-busy={isReindexing}
                className="flex items-center gap-2 rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isReindexing && <Spinner />}
                {isReindexing ? "비우는 중…" : "비우고 다시 만들기"}
              </button>
              <button
                type="button"
                onClick={() => setConfirmingReindex(false)}
                disabled={isBusy}
                className="rounded-lg px-3 py-1.5 text-sm font-medium text-amber-800 transition-colors hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60 dark:text-amber-300 dark:hover:bg-amber-900/40"
              >
                취소
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmingReindex(true)}
            disabled={isBusy || hasChanges}
            title={hasChanges ? "먼저 설정을 저장해 주세요." : undefined}
            className="rounded-lg border border-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-600 transition-colors hover:border-amber-300 hover:bg-amber-50 hover:text-amber-700 disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-800 dark:text-zinc-300 dark:hover:border-amber-900/60 dark:hover:bg-amber-950/30 dark:hover:text-amber-300"
          >
            색인 다시 만들기
          </button>
        )}

        {hasChanges && (
          <p className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
            바꾼 설정을 먼저 저장해야 그 임베딩으로 색인을 만듭니다.
          </p>
        )}
      </Section>

      <Section title="Gemini API key">
        <Field
          id="api-key"
          label="API key"
          hint={
            settings.api_key_configured
              ? `저장된 키가 있습니다${settings.api_key_hint === null ? "" : ` (${settings.api_key_hint})`}. 바꿀 때만 입력하세요.`
              : "키가 없으면 검색과 색인이 모두 실패합니다. Google AI Studio에서 발급한 키를 입력하세요."
          }
        >
          <input
            id="api-key"
            type="password"
            value={draft.apiKey}
            disabled={isBusy}
            autoComplete="off"
            spellCheck={false}
            aria-describedby="api-key-hint"
            placeholder={settings.api_key_configured ? "변경하지 않음" : "AIza…"}
            onChange={(event) => edit({ apiKey: event.target.value })}
            className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 font-mono text-sm text-zinc-900 transition-colors hover:border-zinc-300 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-zinc-700"
          />
        </Field>

        {!settings.api_key_configured && (
          <Notice tone="warn">API key가 설정되지 않아 지금은 질문에 답할 수 없습니다.</Notice>
        )}
      </Section>

      <div className="flex items-center justify-end gap-3 pb-4">
        <Link
          href="/"
          className="rounded-lg px-3 py-2 text-sm font-medium text-zinc-500 transition-colors hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-100"
        >
          채팅으로
        </Link>
        <button
          type="submit"
          disabled={!hasChanges || blocked !== null || isBusy}
          aria-busy={isSaving}
          className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm shadow-blue-600/25 transition-all hover:shadow-md hover:shadow-blue-600/35 hover:brightness-110 active:brightness-95 disabled:cursor-not-allowed disabled:from-zinc-300 disabled:to-zinc-300 disabled:shadow-none disabled:brightness-100 dark:disabled:from-zinc-800 dark:disabled:to-zinc-800 dark:disabled:text-zinc-500"
        >
          {isSaving && <Spinner />}
          {isSaving ? "저장 중…" : "저장"}
        </button>
      </div>
    </form>
  );
}

export function SettingsHeader() {
  return (
    <header className="flex items-center gap-3 border-b border-zinc-200/80 bg-white/80 px-4 py-3 backdrop-blur-sm dark:border-zinc-800/80 dark:bg-zinc-900/80">
      <Link
        href="/"
        aria-label="채팅으로 돌아가기"
        className="shrink-0 rounded-lg p-1.5 text-zinc-500 transition-colors hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
      >
        <BackIcon />
      </Link>
      <h1 className="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight text-zinc-800 dark:text-zinc-100">
        설정
      </h1>
    </header>
  );
}

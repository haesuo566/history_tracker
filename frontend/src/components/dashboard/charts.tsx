"use client";

import { useEffect, useRef, useState } from "react";

import type { DashboardPoint } from "@/lib/types";

/** 백엔드가 '기타'로 묶은 칸의 key. 범주 색을 주지 않고 회색으로 칠한다. */
const OTHERS_KEY = "__others__";

/** 도넛에 범주 색으로 칠할 최대 조각 수. 그 밖은 '기타'로 접는다 — 색을 새로 만들어 내지 않는다. */
const MAX_SLICES = 7;

const SERIES = Array.from({ length: MAX_SLICES }, (_, index) => `var(--viz-series-${index + 1})`);

const numberFormat = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 });

export function formatValue(value: number, unit: string): string {
  return `${numberFormat.format(value)}${unit}`;
}

/**
 * 요소의 실제 너비. SVG 를 viewBox 로 늘려 그리면 글자까지 함께 늘어나므로, 너비를 재서 그 너비로
 * 다시 그린다. ResizeObserver 는 observe 하는 순간 한 번 알려 주므로 첫 값도 여기서 받는다.
 *
 * 너비를 재기 전에는 SVG 가 없으므로, 감싸는 요소에 높이를 미리 잡아 둔다. 그러지 않으면 대화 목록이
 * 맨 아래로 스크롤한 뒤에 차트가 자라나 마지막 메시지가 화면 밖으로 밀린다.
 */
function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const element = ref.current;
    if (element === null) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return [ref, width] as const;
}

/** 0부터 시작하는 깔끔한 눈금(1·2·5 단위). 개수 같은 정수 값이면 소수 눈금을 만들지 않는다. */
function niceTicks(max: number, integers: boolean): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  const nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  const step = integers ? Math.max(1, nice * magnitude) : nice * magnitude;
  const top = Math.ceil(max / step) * step;
  const ticks = [];
  for (let tick = 0; tick <= top + step / 2; tick += step) ticks.push(tick);
  return ticks;
}

function Tooltip({ x, width, label, value }: { x: number; width: number; label: string; value: string }) {
  // 가장자리에서 잘리지 않게 좌우로 당긴다.
  const left = Math.min(Math.max(x, 64), Math.max(width - 64, 64));
  return (
    <div
      role="presentation"
      className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 rounded-lg bg-zinc-900 px-2.5 py-1.5 text-xs whitespace-nowrap text-white shadow-lg dark:bg-zinc-100 dark:text-zinc-900"
      style={{ left }}
    >
      <span className="opacity-70">{label}</span> <span className="font-semibold tabular-nums">{value}</span>
    </div>
  );
}

interface PlotProps {
  points: DashboardPoint[];
  unit: string;
}

const HEIGHT = 200;
const MARGIN = { top: 28, right: 12, bottom: 24, left: 40 };
/** x축 글자 하나가 차지할 최소 폭. 칸이 이보다 좁으면 글자를 건너뛰며 적는다. */
const MIN_LABEL_SPACING = 48;

/** 축과 눈금. 세로 막대와 꺾은선이 함께 쓴다. */
function useFrame(points: DashboardPoint[], width: number) {
  const values = points.map((point) => point.value);
  const ticks = niceTicks(Math.max(0, ...values), values.every(Number.isInteger));
  const top = ticks[ticks.length - 1];
  const plotWidth = Math.max(width - MARGIN.left - MARGIN.right, 0);
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const y = (value: number) => MARGIN.top + plotHeight - (value / top) * plotHeight;
  const labelEvery = Math.max(1, Math.ceil(points.length / Math.max(1, Math.floor(plotWidth / MIN_LABEL_SPACING))));
  return { ticks, plotWidth, plotHeight, y, labelEvery };
}

function Axes({
  ticks,
  y,
  width,
  unit,
}: {
  ticks: number[];
  y: (value: number) => number;
  width: number;
  unit: string;
}) {
  return (
    <g>
      {ticks.map((tick) => (
        <g key={tick}>
          <line
            x1={MARGIN.left}
            x2={width - MARGIN.right}
            y1={y(tick)}
            y2={y(tick)}
            stroke={tick === 0 ? "var(--viz-axis)" : "var(--viz-grid)"}
            strokeWidth={1}
            shapeRendering="crispEdges"
          />
          <text
            x={MARGIN.left - 6}
            y={y(tick)}
            dy="0.32em"
            textAnchor="end"
            fontSize={11}
            fill="var(--viz-muted)"
            className="tabular-nums"
          >
            {numberFormat.format(tick)}
          </text>
        </g>
      ))}
      <text x={MARGIN.left - 6} y={MARGIN.top - 14} textAnchor="end" fontSize={11} fill="var(--viz-muted)">
        ({unit})
      </text>
    </g>
  );
}

/** 위가 둥근 세로 막대. 바닥은 기준선에 붙어 각지게 둔다. */
function columnPath(x: number, top: number, bottom: number, width: number): string {
  const height = bottom - top;
  if (height <= 0) return "";
  const radius = Math.min(4, width / 2, height);
  return [
    `M${x},${bottom}`,
    `V${top + radius}`,
    `Q${x},${top} ${x + radius},${top}`,
    `H${x + width - radius}`,
    `Q${x + width},${top} ${x + width},${top + radius}`,
    `V${bottom}`,
    "Z",
  ].join(" ");
}

/** 시간 축이나 요일·시간대처럼 순서가 있는 칸을 세로 막대로 그린다. */
export function ColumnChart({ points, unit }: PlotProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hovered, setHovered] = useState<number | null>(null);
  const { ticks, plotWidth, y, labelEvery } = useFrame(points, width);

  const band = points.length > 0 ? plotWidth / points.length : 0;
  const barWidth = Math.max(1, Math.min(24, band - 2));
  const baseline = y(0);

  return (
    <div ref={ref} className="relative" style={{ height: HEIGHT }}>
      {width > 0 && (
        <svg width={width} height={HEIGHT} aria-hidden>
          <Axes ticks={ticks} y={y} width={width} unit={unit} />
          {points.map((point, index) => {
            const x = MARGIN.left + band * index + (band - barWidth) / 2;
            return (
              <path
                key={point.key}
                d={columnPath(x, y(point.value), baseline, barWidth)}
                fill="var(--viz-series-1)"
                opacity={hovered === null || hovered === index ? 1 : 0.45}
              />
            );
          })}
          {points.map((point, index) =>
            index % labelEvery === 0 ? (
              <text
                key={point.key}
                x={MARGIN.left + band * (index + 0.5)}
                y={HEIGHT - 6}
                textAnchor="middle"
                fontSize={11}
                fill="var(--viz-muted)"
              >
                {point.label}
              </text>
            ) : null,
          )}
          {/* 맞히기 쉽게 막대보다 넓은 칸 전체를 호버 영역으로 둔다. */}
          {points.map((point, index) => (
            <rect
              key={point.key}
              x={MARGIN.left + band * index}
              y={MARGIN.top}
              width={band}
              height={baseline - MARGIN.top}
              fill="transparent"
              onMouseEnter={() => setHovered(index)}
              onMouseLeave={() => setHovered(null)}
            />
          ))}
        </svg>
      )}
      {hovered !== null && points[hovered] !== undefined && (
        <Tooltip
          x={MARGIN.left + band * (hovered + 0.5)}
          width={width}
          label={points[hovered].label}
          value={formatValue(points[hovered].value, unit)}
        />
      )}
    </div>
  );
}

/** 날짜·주·월의 추이. 2px 선과 옅은 면, 끝점에만 값을 적는다. */
export function LineChart({ points, unit }: PlotProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hovered, setHovered] = useState<number | null>(null);
  const { ticks, plotWidth, y, labelEvery } = useFrame(points, width);

  const step = points.length > 1 ? plotWidth / (points.length - 1) : 0;
  const x = (index: number) => (points.length > 1 ? MARGIN.left + step * index : MARGIN.left + plotWidth / 2);
  const baseline = y(0);
  const line = points.map((point, index) => `${index === 0 ? "M" : "L"}${x(index)},${y(point.value)}`).join(" ");
  const area = points.length > 0 ? `${line} L${x(points.length - 1)},${baseline} L${x(0)},${baseline} Z` : "";
  const last = points.length - 1;

  function handleMove(event: React.MouseEvent<SVGRectElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const offset = event.clientX - bounds.left;
    const index = step > 0 ? Math.round(offset / step) : 0;
    setHovered(Math.min(Math.max(index, 0), last));
  }

  return (
    <div ref={ref} className="relative" style={{ height: HEIGHT }}>
      {width > 0 && (
        <svg width={width} height={HEIGHT} aria-hidden>
          <Axes ticks={ticks} y={y} width={width} unit={unit} />
          <path d={area} fill="var(--viz-series-1)" opacity={0.1} />
          <path
            d={line}
            fill="none"
            stroke="var(--viz-series-1)"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          {points.map((point, index) =>
            index % labelEvery === 0 ? (
              <text key={point.key} x={x(index)} y={HEIGHT - 6} textAnchor="middle" fontSize={11} fill="var(--viz-muted)">
                {point.label}
              </text>
            ) : null,
          )}
          {hovered !== null && (
            <line
              x1={x(hovered)}
              x2={x(hovered)}
              y1={MARGIN.top}
              y2={baseline}
              stroke="var(--viz-axis)"
              strokeWidth={1}
              shapeRendering="crispEdges"
            />
          )}
          {last >= 0 && (
            <>
              <circle
                cx={x(hovered ?? last)}
                cy={y(points[hovered ?? last].value)}
                r={4}
                fill="var(--viz-series-1)"
                stroke="var(--viz-surface)"
                strokeWidth={2}
              />
              {hovered === null && (
                <text
                  x={x(last)}
                  y={y(points[last].value) - 10}
                  textAnchor="end"
                  fontSize={11}
                  fontWeight={600}
                  fill="var(--viz-ink)"
                  className="tabular-nums"
                >
                  {formatValue(points[last].value, unit)}
                </text>
              )}
            </>
          )}
          <rect
            x={MARGIN.left}
            y={MARGIN.top}
            width={plotWidth}
            height={baseline - MARGIN.top}
            fill="transparent"
            onMouseMove={handleMove}
            onMouseLeave={() => setHovered(null)}
          />
        </svg>
      )}
      {hovered !== null && points[hovered] !== undefined && (
        <Tooltip
          x={x(hovered)}
          width={width}
          label={points[hovered].label}
          value={formatValue(points[hovered].value, unit)}
        />
      )}
    </div>
  );
}

/** 사이트처럼 이름이 긴 범주는 가로 막대로 그린다. 이름이 잘리지 않고 값은 막대 끝에 적는다. */
export function BarList({ points, unit }: PlotProps) {
  const max = Math.max(0, ...points.map((point) => point.value));

  return (
    <ul className="space-y-1.5">
      {points.map((point) => (
        <li
          key={point.key}
          className="grid grid-cols-[minmax(0,9rem)_1fr] items-center gap-3 rounded-md px-1 py-0.5 text-xs transition-colors hover:bg-zinc-100 sm:grid-cols-[minmax(0,12rem)_1fr] dark:hover:bg-zinc-800/60"
        >
          <span className="truncate text-[color:var(--viz-ink-2)]" title={point.label}>
            {point.label}
          </span>
          <span className="flex min-w-0 items-center gap-2">
            <span
              className="h-3.5 shrink-0 rounded-r"
              style={{
                width: `${max > 0 ? Math.max((point.value / max) * 85, 0.5) : 0}%`,
                background: point.key === OTHERS_KEY ? "var(--viz-others)" : "var(--viz-series-1)",
              }}
            />
            <span className="font-medium whitespace-nowrap text-[color:var(--viz-ink)] tabular-nums">
              {formatValue(point.value, unit)}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** 범주 색을 넘는 조각은 '기타'로 접는다. 백엔드가 이미 접은 '기타'가 있으면 거기에 더한다. */
function foldSlices(points: DashboardPoint[]): DashboardPoint[] {
  const named = points.filter((point) => point.key !== OTHERS_KEY);
  const others = points.find((point) => point.key === OTHERS_KEY)?.value ?? 0;
  const kept = named.slice(0, MAX_SLICES);
  const folded = others + named.slice(MAX_SLICES).reduce((sum, point) => sum + point.value, 0);
  return folded > 0 ? [...kept, { key: OTHERS_KEY, label: "기타", value: folded }] : kept;
}

function arcPath(cx: number, cy: number, outer: number, inner: number, start: number, end: number): string {
  // 한 조각이 원 전체면 시작점과 끝점이 같아 호가 그려지지 않는다. 아주 조금 덜 그린다.
  const sweep = Math.min(end - start, Math.PI * 2 - 0.0001);
  const finish = start + sweep;
  const large = sweep > Math.PI ? 1 : 0;
  const point = (radius: number, angle: number) =>
    `${cx + radius * Math.sin(angle)},${cy - radius * Math.cos(angle)}`;
  return [
    `M${point(outer, start)}`,
    `A${outer},${outer} 0 ${large} 1 ${point(outer, finish)}`,
    `L${point(inner, finish)}`,
    `A${inner},${inner} 0 ${large} 0 ${point(inner, start)}`,
    "Z",
  ].join(" ");
}

/** 비중. 범례가 이름과 값, 몫을 함께 적어 색만으로 읽게 하지 않는다. */
export function DonutChart({ points, unit }: PlotProps) {
  const [hovered, setHovered] = useState<string | null>(null);
  const slices = foldSlices(points).filter((point) => point.value > 0);
  const total = slices.reduce((sum, point) => sum + point.value, 0);
  const size = 160;
  const center = size / 2;

  const angleOf = (value: number) => (total > 0 ? (value / total) * Math.PI * 2 : 0);
  const arcs = slices.map((point, index) => {
    const start = angleOf(slices.slice(0, index).reduce((sum, previous) => sum + previous.value, 0));
    const end = start + angleOf(point.value);
    const color = point.key === OTHERS_KEY ? "var(--viz-others)" : SERIES[index];
    return { point, color, path: arcPath(center, center, center - 2, center - 30, start, end) };
  });

  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start">
      <svg width={size} height={size} aria-hidden className="shrink-0">
        {arcs.map(({ point, color, path }) => (
          <path
            key={point.key}
            d={path}
            fill={color}
            // 조각 사이의 틈은 테두리가 아니라 바탕색 선이다.
            stroke="var(--viz-surface)"
            strokeWidth={2}
            opacity={hovered === null || hovered === point.key ? 1 : 0.45}
            onMouseEnter={() => setHovered(point.key)}
            onMouseLeave={() => setHovered(null)}
          />
        ))}
        <text x={center} y={center - 4} textAnchor="middle" fontSize={18} fontWeight={600} fill="var(--viz-ink)">
          {numberFormat.format(total)}
        </text>
        <text x={center} y={center + 14} textAnchor="middle" fontSize={11} fill="var(--viz-muted)">
          합계({unit})
        </text>
      </svg>
      <ul className="w-full min-w-0 space-y-1 text-xs">
        {arcs.map(({ point, color }) => (
          <li
            key={point.key}
            onMouseEnter={() => setHovered(point.key)}
            onMouseLeave={() => setHovered(null)}
            className={`flex items-center gap-2 rounded-md px-1.5 py-1 ${
              hovered === point.key ? "bg-zinc-100 dark:bg-zinc-800/60" : ""
            }`}
          >
            <span className="size-2.5 shrink-0 rounded-sm" style={{ background: color }} />
            <span className="min-w-0 flex-1 truncate text-[color:var(--viz-ink-2)]" title={point.label}>
              {point.label}
            </span>
            <span className="font-medium whitespace-nowrap text-[color:var(--viz-ink)] tabular-nums">
              {formatValue(point.value, unit)}
            </span>
            <span className="w-10 text-right whitespace-nowrap text-[color:var(--viz-muted)] tabular-nums">
              {total > 0 ? `${Math.round((point.value / total) * 100)}%` : "-"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 표. 표 패널 자체이기도 하고, 다른 차트의 '표로 보기'이기도 하다. */
export function DataTable({
  points,
  unit,
  dimensionLabel,
  measureLabel,
}: PlotProps & { dimensionLabel: string; measureLabel: string }) {
  return (
    <div className="max-h-72 overflow-y-auto">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-[color:var(--viz-surface)]">
          <tr className="border-b border-[color:var(--viz-grid)] text-left text-[color:var(--viz-muted)]">
            <th className="py-1.5 font-medium">{dimensionLabel}</th>
            <th className="py-1.5 text-right font-medium">{measureLabel}</th>
          </tr>
        </thead>
        <tbody>
          {points.map((point) => (
            <tr key={point.key} className="border-b border-[color:var(--viz-grid)] last:border-0">
              <td className="max-w-0 truncate py-1.5 pr-3 text-[color:var(--viz-ink-2)]" title={point.label}>
                {point.label}
              </td>
              <td className="py-1.5 text-right whitespace-nowrap text-[color:var(--viz-ink)] tabular-nums">
                {formatValue(point.value, unit)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

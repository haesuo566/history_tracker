// 최소 체류시간 값 하나를 background / popup / options 세 곳이 같이 다루므로
// 읽기·환산·표기를 여기에 모아둔다. background.js는 importScripts로,
// 페이지는 <script src>로 불러온다.

const DEFAULT_MIN_DWELL_SECONDS = 0;

// UI에서 고른 단위 -> 초 배수
const MIN_DWELL_UNIT_SECONDS = { sec: 1, min: 60 };
const DEFAULT_MIN_DWELL_UNIT = 'sec';

function normalizeSeconds(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return 0;
  // 0.1초 단위까지만 의미 있게 취급 (그 아래는 NOISE_FLOOR_MS에 먹힌다)
  return Math.round(n * 10) / 10;
}

// 초 단위가 정식 저장 키다. 초 단위 지원 이전 버전이 쓰던 minDwellMinutes만
// 남아있는 프로필에서도 설정값이 유실되지 않도록 여기서 함께 읽어 환산한다.
async function readMinDwellSeconds() {
  const { minDwellSeconds, minDwellMinutes } = await chrome.storage.local.get([
    'minDwellSeconds',
    'minDwellMinutes',
  ]);
  if (minDwellSeconds !== undefined) return normalizeSeconds(minDwellSeconds);
  if (minDwellMinutes !== undefined) return normalizeSeconds(Number(minDwellMinutes) * 60);
  return DEFAULT_MIN_DWELL_SECONDS;
}

function trimNumber(n) {
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 10) / 10);
}

// 0 -> '필터 없음', 45 -> '45초', 120 -> '2분', 150 -> '2분 30초'
function formatDwell(totalSeconds) {
  const seconds = normalizeSeconds(totalSeconds);
  if (seconds === 0) return '필터 없음';
  if (seconds < 60) return `${trimNumber(seconds)}초`;

  const minutes = Math.floor(seconds / 60);
  const rest = normalizeSeconds(seconds - minutes * 60);
  return rest === 0 ? `${minutes}분` : `${minutes}분 ${trimNumber(rest)}초`;
}

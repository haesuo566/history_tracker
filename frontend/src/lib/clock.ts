/**
 * 브라우저의 현재 시각을 UTC 오프셋까지 붙인 ISO 문자열로 만든다.
 *
 * `toISOString()` 을 쓰지 않는 것은 그쪽이 UTC(`...Z`)로만 찍어 오프셋이 사라지기 때문이다.
 * 백엔드는 "어제"의 경계를 사용자의 자정으로 잡는데, 그러려면 시각뿐 아니라 이 사람이 UTC 에서
 * 몇 시간 떨어져 있는지를 알아야 한다. 한국에서 밤 9시 이후에 본 페이지가 "오늘"에서 빠지는
 * 어긋남이 여기서 갈린다.
 *
 * 서버(라우트 핸들러)에서 부르면 서버가 선 지역의 시각이 되므로 브라우저에서만 부른다.
 */
/** 그날 0시. 날짜 차이를 시분초에 흔들리지 않게 세려고 쓴다. */
function startOfDay(moment: Date): Date {
  return new Date(moment.getFullYear(), moment.getMonth(), moment.getDate());
}

/**
 * 결과 카드에 적을 "언제 본 글인지". 읽을 수 없는 값이면 null 이라 그 자리가 비워진다.
 *
 * 어제까지는 날짜 대신 "오늘"·"어제"로 적는다. 방금 본 것을 굳이 날짜로 읽게 할 이유가 없고,
 * 사용자가 "어제 본 거"라고 물어 받은 결과에 같은 말이 찍혀 있으면 맞게 찾았다는 것이 바로 보인다.
 * 해가 바뀐 기록에만 연도를 붙인다.
 */
export function formatVisitedAt(iso: string | null, now: Date = new Date()): string | null {
  if (iso === null) return null;

  const visited = new Date(iso);
  if (Number.isNaN(visited.getTime())) return null;

  const days = Math.round(
    (startOfDay(now).getTime() - startOfDay(visited).getTime()) / (24 * 60 * 60 * 1000),
  );
  if (days === 0) return "오늘";
  if (days === 1) return "어제";

  const monthDay = `${visited.getMonth() + 1}월 ${visited.getDate()}일`;
  return visited.getFullYear() === now.getFullYear()
    ? monthDay
    : `${visited.getFullYear()}년 ${monthDay}`;
}

export function localNowIso(now: Date = new Date()): string {
  const pad = (value: number): string => String(value).padStart(2, "0");

  // getTimezoneOffset 은 "UTC - 로컬" 을 분으로 주므로 부호가 뒤집혀 있다(KST 는 -540).
  const offsetMinutes = -now.getTimezoneOffset();
  const sign = offsetMinutes < 0 ? "-" : "+";
  const absolute = Math.abs(offsetMinutes);

  const date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  const offset = `${sign}${pad(Math.floor(absolute / 60))}:${pad(absolute % 60)}`;
  return `${date}T${time}${offset}`;
}

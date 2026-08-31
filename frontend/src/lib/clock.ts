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

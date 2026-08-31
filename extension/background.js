const RETRY_ALARM = 'retry-queue';
const RETRY_INTERVAL_MINUTES = 0.5; // 30초마다 실패 건 재시도
const DEFAULT_API_ENDPOINT = 'http://127.0.0.1:8000';
// 이전 기본값. 실제로 존재하는 placeholder 도메인이라 설정 없이 리로드하면 그쪽으로
// 조용히 전송을 시도했다. 사용자가 직접 넣은 주소는 건드리지 않고 이 값만 교체한다.
const LEGACY_DEFAULT_API_ENDPOINT = 'https://example.com';
const COLLECT_PATH = '/collect';
// 체류시간 필터를 걷어내기 전 버전이 남긴 키들. 설치/업데이트 시 정리한다.
const OBSOLETE_LOCAL_KEYS = ['minDwellSeconds', 'minDwellUnit', 'minDwellMinutes'];
// 큐 항목은 본문 전체를 담는다. 서버를 꺼둔 채로 오래 브라우징하면 storage.local 용량
// (확장 기본 약 10MB)을 넘겨 저장 자체가 실패하므로 오래된 건부터 버린다.
const MAX_QUEUE_SIZE = 300;

async function sendRecord(record) {
  const { apiEndpoint = DEFAULT_API_ENDPOINT } = await chrome.storage.local.get('apiEndpoint');
  const url = `${apiEndpoint.replace(/\/$/, '')}${COLLECT_PATH}`;
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(record),
    });
    console.log('[visit-tracker] POST', url, res.status, record.url);
    return res.ok;
  } catch (e) {
    console.error('[visit-tracker] fetch 실패', url, e);
    return false;
  }
}

// 큐는 storage 를 읽고 고쳐 다시 쓰는 방식이라, 여러 페이지의 전송이 동시에 실패하면
// 서로의 쓰기를 덮어쓴다. 방문 세션 하나만 다루던 이전 구조에선 전송이 직렬이라 생기지
// 않던 문제라서, 큐에 손대는 구간만 프라미스 체인으로 직렬화한다.
let queueLock = Promise.resolve();

// 큐를 비운 시점을 구분하는 카운터. 재시도 루프는 시작할 때 값을 잡아두고 매 건마다
// 비교해, 도중에 사용자가 큐를 비웠으면 남은 건을 보내지 않고 빠져나온다.
let queueGeneration = 0;

function withQueueLock(fn) {
  const run = queueLock.then(fn, fn);
  queueLock = run.catch(() => {});
  return run;
}

// 즉시 전송에 실패한 건만 재시도 큐에 남긴다 (오프라인/서버 다운 대응).
async function enqueueForRetry(record) {
  await withQueueLock(async () => {
    const { queue = [] } = await chrome.storage.local.get('queue');
    queue.push(record);
    const overflow = queue.length - MAX_QUEUE_SIZE;
    if (overflow > 0) {
      queue.splice(0, overflow);
      console.warn('[visit-tracker] 재시도 큐가 가득 차 오래된 건을 버림', overflow);
    }
    try {
      await chrome.storage.local.set({ queue });
    } catch (e) {
      console.error('[visit-tracker] 재시도 큐 저장 실패', e);
    }
  });
}

// 재시도 큐를 통째로 버린다. 서버 주소를 잘못 넣어두고 브라우징한 뒤처럼, 쌓인 건들이
// 성공할 리 없는데 30초마다 계속 재시도되는 상황을 사용자가 직접 끊을 수 있게 한다.
async function clearQueue() {
  return withQueueLock(async () => {
    const { queue = [] } = await chrome.storage.local.get('queue');
    queueGeneration += 1;
    await chrome.storage.local.set({ queue: [] });
    console.log('[visit-tracker] 재시도 큐 비움', queue.length);
    return queue.length;
  });
}

// 서비스워커는 유휴 시 종료되고 메시지가 오면 다시 깨어난다. 토글을 전역 변수에 캐시하면
// 깨어난 직후 초기화가 끝나기 전에 도착한 메시지가 기본값(켜짐)으로 처리되므로 매번 읽는다.
async function isTrackingEnabled() {
  const { trackingEnabled } = await chrome.storage.local.get('trackingEnabled');
  return trackingEnabled !== false;
}

// 본문 추출이 끝난 시점에 그 자리에서 전송한다. 방문이 끝날 때까지 본문을 들고 있지 않으므로
// 탭/URL 매칭도 진행 중 세션 상태도 필요 없고, 로드가 느린 페이지를 먼저 떠나거나
// 브라우저를 그냥 종료해도 이미 추출된 본문은 유실되지 않는다.
async function collectPage(message) {
  if (!/^https?:\/\//.test(message.url || '')) return;
  if (!(await isTrackingEnabled())) return;

  const record = {
    url: message.url,
    title: message.title || '',
    content: message.text || '',
    startTime: new Date().toISOString(),
  };

  const sent = await sendRecord(record);
  if (!sent) {
    await enqueueForRetry(record);
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === 'PAGE_CONTENT') {
    collectPage(message);
    return;
  }
  if (message?.type === 'CLEAR_QUEUE') {
    // 비동기 응답을 쓰려면 리스너가 true를 반환해 채널을 열어둬야 한다.
    clearQueue().then(
      (cleared) => sendResponse({ ok: true, cleared }),
      (e) => sendResponse({ ok: false, error: String(e) })
    );
    return true;
  }
});

chrome.runtime.onInstalled.addListener(async () => {
  const { deviceId } = await chrome.storage.local.get('deviceId');
  if (!deviceId) {
    await chrome.storage.local.set({ deviceId: crypto.randomUUID() });
  }
  const { apiEndpoint } = await chrome.storage.local.get('apiEndpoint');
  if (!apiEndpoint || apiEndpoint === LEGACY_DEFAULT_API_ENDPOINT) {
    await chrome.storage.local.set({ apiEndpoint: DEFAULT_API_ENDPOINT });
  }
  const { trackingEnabled } = await chrome.storage.local.get('trackingEnabled');
  if (trackingEnabled === undefined) {
    await chrome.storage.local.set({ trackingEnabled: true });
  }

  await chrome.storage.local.remove(OBSOLETE_LOCAL_KEYS);
  // 진행 중 방문을 담아두던 세션 상태도 더 이상 쓰지 않는다.
  await chrome.storage.session.remove('currentSession');

  chrome.alarms.create(RETRY_ALARM, { periodInMinutes: RETRY_INTERVAL_MINUTES });
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(RETRY_ALARM, { periodInMinutes: RETRY_INTERVAL_MINUTES });
});

// SPA 라우팅(pushState/replaceState)은 실제 문서 로드가 아니라서 content_scripts가
// 재주입되지 않는다. 라우팅 감지 후 콘텐츠 스크립트에 재추출을 직접 요청한다.
chrome.webNavigation.onHistoryStateUpdated.addListener(
  (details) => {
    if (details.frameId !== 0) return;
    setTimeout(() => {
      chrome.tabs.sendMessage(details.tabId, { type: 'REQUEST_CONTENT' }).catch(() => {});
    }, 800);
  },
  { url: [{ schemes: ['http', 'https'] }] }
);

// 성공한 건만 그때그때 큐에서 빼낸다. 큐를 미리 비워두고 돌리면 도중에 서비스워커가
// 종료될 때 아직 못 보낸 건이 함께 사라지고, 재시도 중 새로 실패한 건도 덮어쓰게 된다.
async function retryQueue() {
  const { queue = [] } = await chrome.storage.local.get('queue');
  if (queue.length === 0) return;

  const generation = queueGeneration;
  for (const record of queue) {
    if (generation !== queueGeneration) return; // 도중에 큐를 비웠다
    const sent = await sendRecord(record);
    if (!sent) continue;

    await withQueueLock(async () => {
      const { queue: current = [] } = await chrome.storage.local.get('queue');
      const index = current.findIndex(
        (r) => r.url === record.url && r.startTime === record.startTime
      );
      if (index === -1) return;
      current.splice(index, 1);
      await chrome.storage.local.set({ queue: current });
    });
  }
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === RETRY_ALARM) {
    retryQueue();
  }
});

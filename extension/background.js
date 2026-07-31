importScripts('dwell.js');

const RETRY_ALARM = 'retry-queue';
const RETRY_INTERVAL_MINUTES = 0.5; // 30초마다 실패 건 재시도
const NOISE_FLOOR_MS = 500; // 이보다 짧은 체류는 탭 전환 튐으로 보고 무조건 버림
const DEFAULT_API_ENDPOINT = 'http://127.0.0.1:8000';
// 이전 기본값. 실제로 존재하는 placeholder 도메인이라 설정 없이 리로드하면 그쪽으로
// 조용히 전송을 시도했다. 사용자가 직접 넣은 주소는 건드리지 않고 이 값만 교체한다.
const LEGACY_DEFAULT_API_ENDPOINT = 'https://example.com';
const COLLECT_PATH = '/collect';

// 서비스워커는 필요시 재시작되므로, 재시작에도 살아남아야 하는 진행중 방문 상태는
// storage.session(브라우저 세션 동안 유지되는 메모리 저장소)에 둔다.
async function getSession() {
  const { currentSession } = await chrome.storage.session.get('currentSession');
  return currentSession || null;
}

async function setSession(session) {
  await chrome.storage.session.set({ currentSession: session });
}

async function clearSession() {
  await chrome.storage.session.remove('currentSession');
}

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

// 즉시 전송에 실패한 건만 재시도 큐에 남긴다 (오프라인/서버 다운 대응).
async function enqueueForRetry(record) {
  const { queue = [] } = await chrome.storage.local.get('queue');
  queue.push(record);
  await chrome.storage.local.set({ queue });
}

async function finalizeSession() {
  const session = await getSession();
  if (!session) return;

  const endTime = Date.now();
  const duration = endTime - session.startTime;
  await clearSession();

  const minDwellSeconds = await readMinDwellSeconds();
  const thresholdMs = Math.max(NOISE_FLOOR_MS, minDwellSeconds * 1000);
  if (duration < thresholdMs) {
    console.log('[visit-tracker] 임계값 미달로 스킵', session.url, `${duration}ms`, `기준 ${thresholdMs}ms`);
    return;
  }

  const record = {
    url: session.url,
    title: session.title,
    content: session.content || '',
    startTime: new Date(session.startTime).toISOString(),
    endTime: new Date(endTime).toISOString(),
  };

  const sent = await sendRecord(record);
  if (!sent) {
    await enqueueForRetry(record);
  }
}

// 서비스워커가 깨어날 때마다 새로 계산해야 하는 휘발성 상태.
let lastFocusedWindowId = chrome.windows.WINDOW_ID_NONE;
let lastIdleState = 'active';
let pendingTransitionType = null;
let trackingEnabled = true;

async function computeQualifyingTab() {
  if (!trackingEnabled) return null;
  if (lastIdleState !== 'active') return null;
  if (lastFocusedWindowId === chrome.windows.WINDOW_ID_NONE) return null;
  const tabs = await chrome.tabs.query({ active: true, windowId: lastFocusedWindowId });
  return tabs[0] || null;
}

async function refreshSession() {
  const activeTab = await computeQualifyingTab();
  const session = await getSession();

  const unchanged =
    session && activeTab && session.tabId === activeTab.id && session.url === activeTab.url;
  if (unchanged) return;

  if (session) {
    await finalizeSession();
  }

  if (activeTab && /^https?:\/\//.test(activeTab.url || '')) {
    console.log('[visit-tracker] 세션 시작', activeTab.url);
    await setSession({
      tabId: activeTab.id,
      windowId: activeTab.windowId,
      url: activeTab.url,
      title: activeTab.title || '',
      startTime: Date.now(),
      transitionType: pendingTransitionType,
      content: null,
    });
  } else if (!activeTab) {
    console.log('[visit-tracker] 추적 대상 탭 없음 (idle/포커스없음/트래킹꺼짐 중 하나)');
  }
  pendingTransitionType = null;
}

async function initState() {
  try {
    const win = await chrome.windows.getLastFocused({ windowTypes: ['normal'] });
    lastFocusedWindowId = win.focused ? win.id : chrome.windows.WINDOW_ID_NONE;
  } catch {
    lastFocusedWindowId = chrome.windows.WINDOW_ID_NONE;
  }
  lastIdleState = await new Promise((resolve) => chrome.idle.queryState(60, resolve));
  const { trackingEnabled: stored } = await chrome.storage.local.get('trackingEnabled');
  trackingEnabled = stored !== false;
  await refreshSession();
}
initState();

chrome.runtime.onInstalled.addListener(async () => {
  const { deviceId } = await chrome.storage.local.get('deviceId');
  if (!deviceId) {
    await chrome.storage.local.set({ deviceId: crypto.randomUUID() });
  }
  const { apiEndpoint } = await chrome.storage.local.get('apiEndpoint');
  if (!apiEndpoint || apiEndpoint === LEGACY_DEFAULT_API_ENDPOINT) {
    await chrome.storage.local.set({ apiEndpoint: DEFAULT_API_ENDPOINT });
  }
  // 구버전(분 단위 전용)에서 올라온 경우 기존 값을 초로 환산해 옮기고 옛 키는 버린다.
  const { minDwellSeconds, minDwellMinutes } = await chrome.storage.local.get([
    'minDwellSeconds',
    'minDwellMinutes',
  ]);
  if (minDwellSeconds === undefined) {
    const migrated =
      minDwellMinutes === undefined
        ? DEFAULT_MIN_DWELL_SECONDS
        : Math.max(0, Number(minDwellMinutes) || 0) * 60;
    await chrome.storage.local.set({
      minDwellSeconds: migrated,
      minDwellUnit: migrated > 0 && migrated % 60 === 0 ? 'min' : DEFAULT_MIN_DWELL_UNIT,
    });
  }
  if (minDwellMinutes !== undefined) {
    await chrome.storage.local.remove('minDwellMinutes');
  }
  const { trackingEnabled } = await chrome.storage.local.get('trackingEnabled');
  if (trackingEnabled === undefined) {
    await chrome.storage.local.set({ trackingEnabled: true });
  }
  chrome.idle.setDetectionInterval(60);
  chrome.alarms.create(RETRY_ALARM, { periodInMinutes: RETRY_INTERVAL_MINUTES });
});

// popup에서 토글을 바꾸면 즉시 반영 — 끄는 순간 진행중 세션을 바로 종료 처리한다.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local' || !changes.trackingEnabled) return;
  trackingEnabled = changes.trackingEnabled.newValue !== false;
  refreshSession();
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(RETRY_ALARM, { periodInMinutes: RETRY_INTERVAL_MINUTES });
});

chrome.webNavigation.onCommitted.addListener(
  (details) => {
    if (details.frameId !== 0) return;
    pendingTransitionType = details.transitionType;
    refreshSession();
  },
  { url: [{ schemes: ['http', 'https'] }] }
);

// SPA 라우팅(pushState/replaceState)은 실제 문서 로드가 아니라서 content_scripts가
// 재주입되지 않는다. 라우팅 감지 후 콘텐츠 스크립트에 재추출을 직접 요청한다.
chrome.webNavigation.onHistoryStateUpdated.addListener(
  (details) => {
    if (details.frameId !== 0) return;
    pendingTransitionType = details.transitionType;
    refreshSession().then(() => {
      setTimeout(() => {
        chrome.tabs.sendMessage(details.tabId, { type: 'REQUEST_CONTENT' }).catch(() => {});
      }, 800);
    });
  },
  { url: [{ schemes: ['http', 'https'] }] }
);

chrome.tabs.onActivated.addListener(() => {
  refreshSession();
});

// onCommitted 시점엔 아직 title이 안 잡혀있는 경우가 많아서, 브라우저가 실제로
// 탭 title을 갱신하는 순간을 별도로 잡아 세션에 반영한다.
// tab.url 확인이 반드시 필요하다: 같은 탭에서 다음 페이지로 이동한 뒤 도착한 title이
// 아직 열려있는 이전 방문 세션에 기록되면, 전송 레코드의 title이 url과 어긋난다.
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (!changeInfo.title) return;
  const session = await getSession();
  if (session && session.tabId === tabId && session.url === tab.url) {
    session.title = changeInfo.title;
    await setSession(session);
  }
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const session = await getSession();
  if (session && session.tabId === tabId) {
    await finalizeSession();
  }
});

chrome.windows.onFocusChanged.addListener((windowId) => {
  lastFocusedWindowId = windowId;
  refreshSession();
});

chrome.idle.onStateChanged.addListener((state) => {
  lastIdleState = state;
  refreshSession();
});

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message?.type !== 'PAGE_CONTENT') return;
  const tabId = sender.tab?.id;
  if (tabId == null) return;

  getSession().then((session) => {
    if (session && session.tabId === tabId && session.url === message.url) {
      session.content = message.text || '';
      session.title = message.title || session.title;
      setSession(session);
    }
  });
});

async function retryQueue() {
  const { queue = [] } = await chrome.storage.local.get('queue');
  if (queue.length === 0) return;

  const remaining = [];
  for (const record of queue) {
    const sent = await sendRecord(record);
    if (!sent) remaining.push(record);
  }
  await chrome.storage.local.set({ queue: remaining });
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === RETRY_ALARM) {
    retryQueue();
  }
});

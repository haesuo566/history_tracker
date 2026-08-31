const $ = (id) => document.getElementById(id);

function applyTrackingState(enabled) {
  $('trackingToggle').checked = enabled;
  $('statusCard').classList.toggle('is-off', !enabled);
  $('trackingLabel').textContent = enabled ? '수집 중' : '수집 꺼짐';
  $('trackingSub').textContent = enabled
    ? '페이지를 열면 본문을 수집해 전송합니다'
    : '새 방문을 기록하지 않습니다';
}

// 값이 길면 CSS로 잘리므로 전체 값은 title로 남겨 hover 시 볼 수 있게 한다.
function setText(id, value) {
  const el = $(id);
  el.textContent = value;
  el.title = value;
}

// 큐를 비우면 아직 못 보낸 본문이 그대로 사라진다. 팝업에서 confirm()을 띄우면 팝업이
// 닫혀버리는 경우가 있어, 버튼 자체를 한 번 더 눌러야 실행되는 확인 단계로 쓴다.
const CLEAR_CONFIRM_MS = 3000;
let clearConfirmTimer = null;

function setClearConfirming(on) {
  const btn = $('clearQueue');
  btn.classList.toggle('is-confirm', on);
  btn.textContent = on ? '정말 비울까요?' : '비우기';
  clearTimeout(clearConfirmTimer);
  if (on) {
    clearConfirmTimer = setTimeout(() => setClearConfirming(false), CLEAR_CONFIRM_MS);
  }
}

$('clearQueue').addEventListener('click', async () => {
  const btn = $('clearQueue');
  if (!btn.classList.contains('is-confirm')) {
    setClearConfirming(true);
    return;
  }

  setClearConfirming(false);
  btn.disabled = true;
  const res = await chrome.runtime.sendMessage({ type: 'CLEAR_QUEUE' }).catch(() => null);
  // 성공하면 storage 변경 알림으로 render가 돌아 상태를 맞춘다. 실패했을 때만 되돌린다.
  if (!res?.ok) {
    btn.disabled = false;
  }
});

async function render() {
  const { queue = [], deviceId, apiEndpoint, trackingEnabled } = await chrome.storage.local.get([
    'queue',
    'deviceId',
    'apiEndpoint',
    'trackingEnabled',
  ]);

  const queueBadge = $('queueCount');
  queueBadge.textContent = queue.length;
  queueBadge.classList.toggle('is-warn', queue.length > 0);

  $('clearQueue').disabled = queue.length === 0;
  if (queue.length === 0) setClearConfirming(false);

  setText('endpoint', apiEndpoint ? `${apiEndpoint.replace(/\/$/, '')}/collect` : '미설정');
  setText('deviceId', deviceId || '-');
  $('version').textContent = `v${chrome.runtime.getManifest().version}`;

  applyTrackingState(trackingEnabled !== false);
}

$('trackingToggle').addEventListener('change', async (e) => {
  applyTrackingState(e.target.checked);
  await chrome.storage.local.set({ trackingEnabled: e.target.checked });
});

// 설정 페이지에서 값을 바꿨거나 재시도 큐가 비워지면 팝업이 열려있는 동안에도 반영한다.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local') render();
});

$('openOptions').addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
});

render();

const $ = (id) => document.getElementById(id);

function applyTrackingState(enabled) {
  $('trackingToggle').checked = enabled;
  $('statusCard').classList.toggle('is-off', !enabled);
  $('trackingLabel').textContent = enabled ? '수집 중' : '수집 꺼짐';
  $('trackingSub').textContent = enabled
    ? '방문이 끝나면 서버로 전송합니다'
    : '새 방문을 기록하지 않습니다';
}

// 값이 길면 CSS로 잘리므로 전체 값은 title로 남겨 hover 시 볼 수 있게 한다.
function setText(id, value) {
  const el = $(id);
  el.textContent = value;
  el.title = value;
}

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

  setText('minDwell', formatDwell(await readMinDwellSeconds()));
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

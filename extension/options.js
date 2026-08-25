const $ = (id) => document.getElementById(id);

const endpointInput = $('endpoint');

// ── 수집 켜기/끄기 (팝업과 동일하게 즉시 저장) ─────────────
function applyTrackingState(enabled) {
  $('trackingToggle').checked = enabled;
  $('statusCard').classList.toggle('is-off', !enabled);
  $('trackingLabel').textContent = enabled ? '수집 중' : '수집 꺼짐';
  $('trackingSub').textContent = enabled
    ? '페이지를 열면 본문을 수집해 전송합니다'
    : '새 방문을 기록하지 않습니다';
}

$('trackingToggle').addEventListener('change', async (e) => {
  applyTrackingState(e.target.checked);
  await chrome.storage.local.set({ trackingEnabled: e.target.checked });
});

// 팝업 토글로 바꿔도 열려있는 설정 화면이 따라오게 한다.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.trackingEnabled) {
    applyTrackingState(changes.trackingEnabled.newValue !== false);
  }
});

// ── 저장 / 로드 ───────────────────────────────────────────
function showToast(message, isError = false) {
  const el = $('status');
  el.textContent = message;
  el.classList.toggle('is-error', isError);
  el.classList.add('is-visible');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => el.classList.remove('is-visible'), 2200);
}

function validateEndpoint(value) {
  if (!value) return true; // 비워두면 미설정 상태로 남긴다
  try {
    return /^https?:$/.test(new URL(value).protocol);
  } catch {
    return false;
  }
}

$('save').addEventListener('click', async () => {
  const endpoint = endpointInput.value.trim();
  const valid = validateEndpoint(endpoint);
  endpointInput.classList.toggle('is-invalid', !valid);
  $('endpointError').textContent = valid ? '' : 'http:// 또는 https:// 로 시작하는 주소를 입력하세요.';
  if (!valid) {
    endpointInput.focus();
    showToast('저장하지 못했습니다.', true);
    return;
  }

  await chrome.storage.local.set({ apiEndpoint: endpoint });
  showToast('저장되었습니다.');
});

endpointInput.addEventListener('input', () => {
  endpointInput.classList.remove('is-invalid');
  $('endpointError').textContent = '';
});

async function load() {
  const { apiEndpoint, deviceId, trackingEnabled } = await chrome.storage.local.get([
    'apiEndpoint',
    'deviceId',
    'trackingEnabled',
  ]);

  endpointInput.value = apiEndpoint || '';
  $('deviceId').textContent = deviceId || '-';
  $('version').textContent = `v${chrome.runtime.getManifest().version}`;

  applyTrackingState(trackingEnabled !== false);
}

load();

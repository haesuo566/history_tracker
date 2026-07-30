const $ = (id) => document.getElementById(id);

const dwellValueInput = $('dwellValue');
const dwellUnitSelect = $('dwellUnit');
const endpointInput = $('endpoint');

// ── 수집 켜기/끄기 (팝업과 동일하게 즉시 저장) ─────────────
function applyTrackingState(enabled) {
  $('trackingToggle').checked = enabled;
  $('statusCard').classList.toggle('is-off', !enabled);
  $('trackingLabel').textContent = enabled ? '수집 중' : '수집 꺼짐';
  $('trackingSub').textContent = enabled
    ? '방문이 끝나면 서버로 전송합니다'
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

// ── 최소 체류시간 ─────────────────────────────────────────
function currentUnitSeconds() {
  return MIN_DWELL_UNIT_SECONDS[dwellUnitSelect.value] || 1;
}

function currentDwellSeconds() {
  return normalizeSeconds((Number(dwellValueInput.value) || 0) * currentUnitSeconds());
}

// 입력칸에 넣을 표시값. 초 단위는 정수, 분 단위는 소수점 둘째 자리까지.
function toUnitValue(seconds, unit) {
  const raw = seconds / (MIN_DWELL_UNIT_SECONDS[unit] || 1);
  return String(Math.round(raw * 100) / 100);
}

function syncStep() {
  // 분 단위에선 30초(0.5분) 단위로 오르내리는 게 자연스럽다.
  dwellValueInput.step = dwellUnitSelect.value === 'min' ? '0.5' : '1';
}

function refreshDwellUi() {
  const seconds = currentDwellSeconds();
  $('dwellPreview').textContent = formatDwell(seconds);
  for (const chip of $('presets').querySelectorAll('.chip')) {
    chip.setAttribute('aria-pressed', String(Number(chip.dataset.seconds) === seconds));
  }
}

// change 이벤트 시점엔 select.value가 이미 새 단위라서, 환산에 쓸 직전 단위를 따로 들고 있는다.
let previousUnit = DEFAULT_MIN_DWELL_UNIT;

function setDwell(seconds, unit) {
  dwellUnitSelect.value = unit;
  dwellValueInput.value = toUnitValue(seconds, unit);
  previousUnit = unit;
  syncStep();
  refreshDwellUi();
}

dwellValueInput.addEventListener('input', refreshDwellUi);

// 단위를 바꿀 때 숫자를 그대로 두면 60배가 튀므로, 같은 시간을 유지하도록 환산한다.
dwellUnitSelect.addEventListener('change', () => {
  const seconds = normalizeSeconds(
    (Number(dwellValueInput.value) || 0) * (MIN_DWELL_UNIT_SECONDS[previousUnit] || 1)
  );
  setDwell(seconds, dwellUnitSelect.value);
});

$('presets').addEventListener('click', (e) => {
  const chip = e.target.closest('.chip');
  if (!chip) return;
  const seconds = Number(chip.dataset.seconds);
  setDwell(seconds, seconds > 0 && seconds % 60 === 0 ? 'min' : 'sec');
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

  await chrome.storage.local.set({
    apiEndpoint: endpoint,
    minDwellSeconds: currentDwellSeconds(),
    minDwellUnit: dwellUnitSelect.value,
  });
  showToast('저장되었습니다.');
});

endpointInput.addEventListener('input', () => {
  endpointInput.classList.remove('is-invalid');
  $('endpointError').textContent = '';
});

async function load() {
  const { apiEndpoint, deviceId, minDwellUnit, trackingEnabled } = await chrome.storage.local.get([
    'apiEndpoint',
    'deviceId',
    'minDwellUnit',
    'trackingEnabled',
  ]);

  endpointInput.value = apiEndpoint || '';
  $('deviceId').textContent = deviceId || '-';
  $('version').textContent = `v${chrome.runtime.getManifest().version}`;

  const seconds = await readMinDwellSeconds();
  const unit = minDwellUnit in MIN_DWELL_UNIT_SECONDS ? minDwellUnit : DEFAULT_MIN_DWELL_UNIT;
  setDwell(seconds, unit);

  applyTrackingState(trackingEnabled !== false);
}

load();

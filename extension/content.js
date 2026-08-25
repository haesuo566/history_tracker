(function () {
  // 초기 로드분과 SPA 재추출 요청분이 같은 결과를 낼 수 있다. 서버가 (url, 본문) 해시로
  // 중복을 걸러주긴 하지만 굳이 왕복할 필요는 없어서 직전 전송분을 기억해둔다.
  let lastReported = null;

  function parseArticle() {
    try {
      return new Readability(document.cloneNode(true)).parse();
    } catch {
      return null;
    }
  }

  function reportContent() {
    const article = parseArticle();
    const rawText = article?.textContent || (document.body ? document.body.innerText : '');
    const text = rawText.replace(/\s+/g, ' ').trim();
    const url = location.href;

    const fingerprint = `${url}\n${text}`;
    if (fingerprint === lastReported) return;
    lastReported = fingerprint;

    chrome.runtime.sendMessage({
      type: 'PAGE_CONTENT',
      url,
      title: article?.title || document.title,
      text,
    });
  }

  if (document.readyState === 'complete') {
    reportContent();
  } else {
    window.addEventListener('load', reportContent, { once: true });
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type === 'REQUEST_CONTENT') {
      reportContent();
    }
  });
})();

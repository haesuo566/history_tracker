(function () {
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

    chrome.runtime.sendMessage({
      type: 'PAGE_CONTENT',
      url: location.href,
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

(() => {
  const chinese = location.pathname.startsWith('/zh/');
  const header = document.querySelector('.nav-inner') || document.querySelector('.masthead, header nav');
  if (!header) return;
  const link = document.createElement('a');
  link.className = 'language-link';
  link.lang = chinese ? 'en' : 'zh-Hans';
  link.textContent = chinese ? 'English' : '中文';
  function update() {
    const url = new URL(location.href);
    url.pathname = chinese ? url.pathname.slice(3) : '/zh'+url.pathname;
    link.href = url.href;
  }
  update();
  link.addEventListener('focus', update);
  link.addEventListener('pointerdown', update);
  link.addEventListener('click', update);
  document.addEventListener('click', () => queueMicrotask(update));
  window.addEventListener('hashchange', update);
  header.append(link);
})();

// Apply the same reading order to both languages after the visitor UI is built.
document.addEventListener('DOMContentLoaded', () => {
  const page = document.getElementById('view-models');
  if (!page) return;
  const chinese = location.pathname.startsWith('/zh/');
  const coverage = page.querySelector('.visitor-coverage-details');
  const table = page.querySelector('.original-model-table');
  if (!coverage || !table) return;
  const evidence = document.createElement('section');
  evidence.className = 'ranking-evidence';
  const heading = document.createElement('h3');
  heading.textContent = chinese ? '覆盖与来源' : 'Coverage and sources';
  evidence.setAttribute('aria-labelledby', 'ranking-evidence-heading');
  heading.id = 'ranking-evidence-heading';
  page.append(evidence);
  evidence.append(heading, coverage, table);
  page.classList.add('ranking-layout');
}, {once: true});

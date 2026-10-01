document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.querySelector('.menu-toggle');
  const nav = document.querySelector('.main-nav');
  if (toggle && nav) toggle.addEventListener('click', () => {
    const open = nav.classList.toggle('open');
    toggle.setAttribute('aria-expanded', String(open));
  });

  document.querySelectorAll('[data-confirm]').forEach(form => form.addEventListener('submit', e => {
    if (!window.confirm(form.dataset.confirm)) e.preventDefault();
  }));

  document.querySelectorAll('[data-share="copy"]').forEach(btn => btn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(btn.dataset.url);
      const old = btn.textContent;
      btn.textContent = 'لینک کپی شد';
      setTimeout(() => btn.textContent = old, 1800);
    } catch { window.prompt('لینک خبر:', btn.dataset.url); }
  }));
});

"use strict";
(() => {
  const root = document.documentElement;
  const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const activeAnimations = new Set();
  const observed = new WeakSet();
  const selectors = '[data-reveal], .resource-card, .about-card, .lunch-intro, .coming-card, .public-contact-card, .section-heading, .contacts-heading, .team-console .panel, .team-console .stat-card, .team-console .home-action-card, .team-console .lunch-stats article';
  let saved = 'on';
  try { saved = localStorage.getItem('peac.motion') || 'on'; } catch (_) {}
  root.dataset.motion = saved === 'off' ? 'off' : 'on';
  const reduced = () => preference.matches || root.dataset.motion === 'off';

  function syncControls() {
    const off = reduced();
    const button = document.getElementById('motionToggle');
    const checkbox = document.getElementById('consoleMotion');
    if (button) {
      button.setAttribute('aria-pressed', String(off));
      button.textContent = off ? 'Motion reduced' : 'Reduce motion';
      button.disabled = preference.matches;
      button.title = preference.matches ? 'Reduced motion is enabled in your device settings.' : '';
    }
    if (checkbox) {
      checkbox.checked = off;
      checkbox.disabled = preference.matches;
    }
    if (off) {
      activeAnimations.forEach(animation => animation.cancel());
      activeAnimations.clear();
    }
  }

  function setReduced(off) {
    root.dataset.motion = off ? 'off' : 'on';
    try { localStorage.setItem('peac.motion', root.dataset.motion); } catch (_) {}
    syncControls();
  }

  function enter(element, delay = 0) {
    if (reduced() || !element.animate || !element.getClientRects().length) return;
    // Content is visible by default. A failed script can never hide a section.
    const animation = element.animate([
      { opacity: 0, transform: 'translateY(22px) scale(.985)' },
      { opacity: 1, transform: 'translateY(0) scale(1)' }
    ], { duration: 640, delay, easing: 'cubic-bezier(.16, 1, .3, 1)', fill: 'backwards' });
    activeAnimations.add(animation);
    const done = () => activeAnimations.delete(animation);
    animation.addEventListener('finish', done, { once: true });
    animation.addEventListener('cancel', done, { once: true });
  }

  const observer = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
    let index = 0;
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      observer.unobserve(entry.target);
      enter(entry.target, Math.min(index++ * 65, 260));
    }
  }, { threshold: .08, rootMargin: '0px 0px -18px 0px' }) : null;

  function reveal(container = document, replay = false) {
    const candidates = Array.from(container.querySelectorAll(selectors));
    // Animate one level of a composition so text never gets two entrances.
    const elements = candidates.filter(el => !candidates.some(parent => parent !== el && parent.contains(el)));
    let index = 0;
    elements.forEach(element => {
      if (replay && element.getClientRects().length) {
        observer?.unobserve(element);
        observed.add(element);
        enter(element, Math.min(index++ * 55, 220));
      } else if (!observed.has(element)) {
        observed.add(element);
        observer?.observe(element);
      }
    });
  }

  document.getElementById('motionToggle')?.addEventListener('click', () => setReduced(root.dataset.motion !== 'off'));
  document.getElementById('consoleMotion')?.addEventListener('change', event => setReduced(event.target.checked));
  preference.addEventListener('change', syncControls);
  window.addEventListener('storage', event => {
    if (event.key !== 'peac.motion') return;
    root.dataset.motion = event.newValue === 'off' ? 'off' : 'on';
    syncControls();
  });
  window.addEventListener('peac:view', () => requestAnimationFrame(() => reveal(document, true)));
  window.PEACMotion = { reveal, reduced, setReduced };
  syncControls();
  reveal();
})();

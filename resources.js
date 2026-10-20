"use strict";
(() => {
  const dialog = document.getElementById('resourceDialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const resources = {
    introductions: {
      title: 'PEAC Introductions', type: 'Meet the team',
      description: 'Get to know PEAC and the people behind it. Explore the team introductions and contact details in the original slideshow.',
      url: 'https://drive.google.com/file/d/18vwwCEegtnDTB4ZGt6wJjACBHwT6JhQf/view',
      preview: 'https://drive.google.com/file/d/18vwwCEegtnDTB4ZGt6wJjACBHwT6JhQf/preview'
    },
    lunch: {
      title: 'PEAC Lunch Support', type: 'A seat for you',
      description: 'Want someone to eat lunch with, play a game with, or talk to? Send a request using PEAC’s Google Form. Check your school email for a reply.',
      url: 'https://docs.google.com/forms/d/e/1FAIpQLSf-QVjC-qH_q51a_1xwjpNM03ankrg31aVvUsJm6dw8VcJWjQ/viewform?pli=1',
      preview: 'https://docs.google.com/forms/d/e/1FAIpQLSf-QVjC-qH_q51a_1xwjpNM03ankrg31aVvUsJm6dw8VcJWjQ/viewform?embedded=true'
    }
  };
  const frame = document.getElementById('resourceFrame');
  const close = document.getElementById('closeResource');
  const external = document.getElementById('resourceExternal');
  const localSignup = document.getElementById('resourceLocalSignup');
  let opener = null;

  document.querySelectorAll('[data-resource]').forEach(trigger => {
    const resource = resources[trigger.dataset.resource];
    if (!resource) return;
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.setAttribute('aria-controls', 'resourceDialog');
    trigger.addEventListener('click', event => {
      // Preserve normal new-tab gestures and the original link when JS is unavailable.
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      opener = trigger;
      document.getElementById('resourceTitle').textContent = resource.title;
      document.getElementById('resourceType').textContent = resource.type;
      document.getElementById('resourceDescription').textContent = resource.description;
      external.href = resource.url;
      external.setAttribute('aria-label', `Open ${resource.title} in a new tab`);
      localSignup.hidden = trigger.dataset.resource !== 'lunch';
      frame.title = `${resource.title} Google preview`;
      frame.src = resource.preview;
      dialog.showModal();
      document.body.classList.add('resource-dialog-open');
      close.focus({ preventScroll: true });
    });
  });

  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  dialog.addEventListener('close', () => {
    frame.removeAttribute('src');
    document.body.classList.remove('resource-dialog-open');
    opener?.focus({ preventScroll: true });
  });
  localSignup.addEventListener('click', () => {
    dialog.close();
    requestAnimationFrame(() => document.querySelector('#lunchForm input[name="preferred_name"]')?.focus({ preventScroll: true }));
  });

  // Hover summaries are dismissible with Escape and stay inside the hovered card.
  // They never open a dialog or load Google until someone clicks.
  document.querySelectorAll('.resource-card').forEach(card => {
    card.addEventListener('pointerenter', () => card.classList.remove('peek-dismissed'));
    card.addEventListener('focusin', () => card.classList.remove('peek-dismissed'));
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') document.querySelectorAll('.resource-card').forEach(card => card.classList.add('peek-dismissed'));
  });
})();

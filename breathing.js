"use strict";
(() => {
  const dialog = document.getElementById('breathingDialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;

  // Static UI only. No personal data, network requests, or saved breathing history.
  dialog.innerHTML = `
    <div class="breathing-header">
      <div><p class="breathing-eyebrow">A moment for you</p><h2 id="breathingTitle">Box breathing</h2></div>
      <button class="breathing-close" type="button" aria-label="Close box breathing"><svg class="peac-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><use href="/icons.svg#close"/></svg></button>
    </div>
    <p id="breathingDescription" class="breathing-description">Four seconds on each side. Breathe in, hold, breathe out, hold.</p>
    <div class="breathing-visual" aria-hidden="true">
      <div class="breathing-glow"></div>
      <svg class="breathing-square" viewBox="0 0 300 300" fill="none">
        <path class="breathing-track" d="M35 265V35H265V265Z"/>
        <path class="breathing-track-accent" d="M35 265V35H265V265Z" pathLength="1"/>
        <circle class="breathing-corner" cx="35" cy="35" r="3"/><circle class="breathing-corner" cx="265" cy="35" r="3"/>
        <circle class="breathing-corner" cx="265" cy="265" r="3"/><circle class="breathing-corner" cx="35" cy="265" r="3"/>
        <text x="150" y="19" text-anchor="middle">HOLD · 4</text>
        <text x="281" y="150" text-anchor="middle" transform="rotate(90 281 150)">EXHALE · 4</text>
        <text x="150" y="289" text-anchor="middle">HOLD · 4</text>
        <text x="19" y="150" text-anchor="middle" transform="rotate(-90 19 150)">INHALE · 4</text>
        <circle class="breathing-traveler-halo" cx="35" cy="265" r="11"/>
        <circle class="breathing-traveler" cx="35" cy="265" r="5"/>
      </svg>
      <div class="breathing-orb"></div>
      <div class="breathing-center"><strong class="breathing-count">48</strong><span class="breathing-count-label">seconds total</span></div>
    </div>
    <div class="breathing-guidance"><p class="breathing-phase">Ready when you are</p><p class="breathing-meta">Three rounds. One quiet moment.</p></div>
    <div class="breathing-rounds" aria-hidden="true"><span></span><span></span><span></span></div>
    <p class="breathing-status sr-only" role="status" aria-live="polite" aria-atomic="true">Ready. Three rounds of box breathing, 48 seconds in total.</p>
    <div class="breathing-actions"><button class="breathing-main btn primary" type="button">Start 3 rounds</button><button class="breathing-restart btn light" type="button" hidden>Restart</button><button class="breathing-back btn light" type="button">Back to website</button></div>
    <p class="breathing-comfort">Keep it gentle. Stop whenever you need to.</p>`;

  const phaseDuration = 4000;
  const roundDuration = phaseDuration * 4;
  const totalDuration = roundDuration * 3;
  const phases = [
    { title: 'Inhale', instruction: 'Breathe in gently.', from: [35, 265], to: [35, 35] },
    { title: 'Hold', instruction: 'Hold gently.', from: [35, 35], to: [265, 35] },
    { title: 'Exhale', instruction: 'Breathe out slowly.', from: [265, 35], to: [265, 265] },
    { title: 'Hold', instruction: 'Pause gently before your next breath.', from: [265, 265], to: [35, 265] }
  ];
  const $ = selector => dialog.querySelector(selector);
  const ui = {
    main: $('.breathing-main'), close: $('.breathing-close'), back: $('.breathing-back'), restart: $('.breathing-restart'),
    phase: $('.breathing-phase'), meta: $('.breathing-meta'), count: $('.breathing-count'),
    countLabel: $('.breathing-count-label'), status: $('.breathing-status'),
    traveler: $('.breathing-traveler'), halo: $('.breathing-traveler-halo'),
    rounds: Array.from(dialog.querySelectorAll('.breathing-rounds span'))
  };
  let state = 'ready';
  let elapsed = 0;
  let startedAt = 0;
  let frame = 0;
  let opener = null;
  let lastPhaseKey = '';
  let lastCount = '';

  function cancelFrame() {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
  }

  function positionGuide(phase, progress) {
    const x = phase.from[0] + (phase.to[0] - phase.from[0]) * progress;
    const y = phase.from[1] + (phase.to[1] - phase.from[1]) * progress;
    for (const circle of [ui.traveler, ui.halo]) {
      circle.setAttribute('cx', x.toFixed(2));
      circle.setAttribute('cy', y.toFixed(2));
    }
  }

  function renderTimer(ms) {
    const bounded = Math.min(Math.max(ms, 0), totalDuration - 0.001);
    const round = Math.floor(bounded / roundDuration);
    const phaseIndex = Math.floor((bounded % roundDuration) / phaseDuration);
    const phaseProgress = (bounded % phaseDuration) / phaseDuration;
    const phase = phases[phaseIndex];
    const key = `${round}-${phaseIndex}`;
    const seconds = String(Math.max(1, Math.ceil((phaseDuration - bounded % phaseDuration) / 1000)));
    if (key !== lastPhaseKey) {
      lastPhaseKey = key;
      ui.phase.textContent = phase.title;
      ui.meta.textContent = `Round ${round + 1} of 3 · ${phase.instruction}`;
      ui.status.textContent = `Round ${round + 1} of 3. ${phase.title}, 4 seconds. ${phase.instruction}`;
    }
    if (seconds !== lastCount) {
      lastCount = seconds;
      ui.count.textContent = seconds;
    }
    ui.countLabel.textContent = 'seconds';
    ui.rounds.forEach((dot, index) => {
      dot.classList.toggle('is-complete', index < round);
      dot.classList.toggle('is-current', index === round);
    });
    positionGuide(phase, phaseProgress);
    const scale = phaseIndex === 0 ? .68 + .32 * phaseProgress : phaseIndex === 1 ? 1 : phaseIndex === 2 ? 1 - .32 * phaseProgress : .68;
    dialog.style.setProperty('--breath-scale', scale.toFixed(4));
    dialog.style.setProperty('--breath-progress', String((bounded % roundDuration) / roundDuration));
  }

  function finish() {
    cancelFrame();
    const restartHadFocus = document.activeElement === ui.restart;
    state = 'complete';
    elapsed = totalDuration;
    dialog.dataset.breathingState = state;
    dialog.style.setProperty('--breath-scale', '.8');
    dialog.style.setProperty('--breath-progress', '1');
    positionGuide(phases[0], 0);
    ui.phase.textContent = 'Three rounds complete';
    ui.meta.textContent = 'Take your time. Continue when you’re ready.';
    ui.count.textContent = '3';
    ui.countLabel.textContent = 'rounds complete';
    ui.main.textContent = 'Redo 3 rounds';
    ui.restart.hidden = true;
    ui.back.textContent = 'Back to website';
    ui.rounds.forEach(dot => { dot.classList.add('is-complete'); dot.classList.remove('is-current'); });
    ui.status.textContent = 'All three rounds complete. Choose Redo 3 rounds or Back to website.';
    if (restartHadFocus) ui.main.focus({ preventScroll: true });
  }

  function tick(now) {
    frame = 0;
    if (state !== 'running' || !dialog.open) return;
    const current = elapsed + Math.max(0, now - startedAt);
    if (current >= totalDuration) { finish(); return; }
    renderTimer(current);
    frame = requestAnimationFrame(tick);
  }

  function start() {
    cancelFrame();
    if (state !== 'paused') elapsed = 0;
    lastPhaseKey = '';
    lastCount = '';
    state = 'running';
    dialog.dataset.breathingState = state;
    ui.main.textContent = 'Pause';
    ui.restart.hidden = false;
    ui.back.textContent = 'End session';
    startedAt = performance.now();
    renderTimer(elapsed);
    frame = requestAnimationFrame(tick);
  }

  function pause(hidden = false) {
    if (state !== 'running') return;
    elapsed = Math.min(totalDuration, elapsed + Math.max(0, performance.now() - startedAt));
    cancelFrame();
    if (elapsed >= totalDuration) { finish(); return; }
    renderTimer(elapsed);
    state = 'paused';
    dialog.dataset.breathingState = state;
    ui.phase.textContent = 'Paused';
    ui.meta.textContent = hidden ? 'Paused while you were away. Resume when you’re ready.' : 'Take your time. Resume when you’re ready.';
    ui.main.textContent = 'Resume';
    ui.status.textContent = hidden ? 'Box breathing paused because the page is hidden. Choose Resume to continue.' : 'Box breathing paused. Choose Resume to continue.';
  }

  function reset() {
    cancelFrame();
    state = 'ready';
    elapsed = 0;
    lastPhaseKey = '';
    lastCount = '';
    dialog.dataset.breathingState = state;
    dialog.style.setProperty('--breath-scale', '.8');
    dialog.style.setProperty('--breath-progress', '0');
    positionGuide(phases[0], 0);
    ui.phase.textContent = 'Ready when you are';
    ui.meta.textContent = 'Three rounds. One quiet moment.';
    ui.count.textContent = '48';
    ui.countLabel.textContent = 'seconds total';
    ui.main.textContent = 'Start 3 rounds';
    ui.restart.hidden = true;
    ui.back.textContent = 'Back to website';
    ui.rounds.forEach(dot => { dot.classList.remove('is-complete', 'is-current'); });
    ui.status.textContent = 'Ready. Three rounds of box breathing, 48 seconds in total.';
  }

  document.addEventListener('click', event => {
    const trigger = event.target.closest?.('[data-open-breathing]');
    if (!trigger || dialog.open) return;
    event.preventDefault();
    opener = trigger;
    reset();
    dialog.showModal();
    document.body.classList.add('breathing-dialog-open');
    ui.main.focus({ preventScroll: true });
  });
  ui.main.addEventListener('click', () => state === 'running' ? pause() : start());
  ui.restart.addEventListener('click', () => { reset(); start(); ui.main.focus({ preventScroll: true }); });
  const closeDialog = () => { cancelFrame(); dialog.close(); };
  ui.close.addEventListener('click', closeDialog);
  ui.back.addEventListener('click', closeDialog);
  dialog.addEventListener('cancel', cancelFrame);
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closeDialog();
  });
  dialog.addEventListener('close', () => {
    reset();
    document.body.classList.remove('breathing-dialog-open');
    if (opener?.isConnected) opener.focus({ preventScroll: true });
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) pause(true); });
  window.addEventListener('pagehide', () => { if (dialog.open) pause(true); else cancelFrame(); });
})();

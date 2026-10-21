"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const feed = $('newsletterFeed');
  if (!feed) return;
  const more = $('newsletterMore');
  const retry = $('newsletterRetry');
  const dialog = $('newsletterDialog');
  let posts = [], shown = 0, returnFocus = null, loading = false;
  const dateFormat = new Intl.DateTimeFormat('en-US', {year:'numeric', month:'short', day:'numeric'});

  function fillDate(element, value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) { element.textContent = 'PEAC update'; element.removeAttribute('datetime'); return; }
    element.dateTime = date.toISOString();
    element.textContent = dateFormat.format(date);
  }

  function showEmpty(title, detail) {
    feed.replaceChildren();
    const empty = document.createElement('div'); empty.className = 'newsletter-empty';
    const mark = document.createElement('span'); mark.className = 'newsletter-empty-mark'; mark.setAttribute('aria-hidden', 'true'); mark.textContent = '✳';
    const copy = document.createElement('div');
    const strong = document.createElement('strong'); strong.textContent = title;
    const p = document.createElement('p'); p.textContent = detail;
    copy.append(strong, p); empty.append(mark, copy); feed.append(empty);
  }

  function openPost(post, trigger) {
    if (!dialog || typeof dialog.showModal !== 'function') return;
    returnFocus = trigger;
    $('newsletterPostTitle').textContent = post.title;
    $('newsletterPostBody').textContent = post.body;
    fillDate($('newsletterPostDate'), post.published_at);
    dialog.showModal();
    document.body.classList.add('resource-dialog-open');
    $('closeNewsletter').focus();
  }

  function appendPosts(moveFocus = false) {
    const next = posts.slice(shown, shown + 6);
    let firstButton = null;
    next.forEach(post => {
      const article = document.createElement('article'); article.className = 'newsletter-card'; article.setAttribute('data-reveal', '');
      const date = document.createElement('time'); date.className = 'newsletter-date'; fillDate(date, post.published_at);
      const title = document.createElement('h3'); title.textContent = post.title;
      const excerpt = document.createElement('p'); excerpt.className = 'newsletter-excerpt';
      excerpt.textContent = post.body.length > 240 ? post.body.slice(0, 240).trimEnd() + '…' : post.body;
      const read = document.createElement('button'); read.type = 'button'; read.className = 'newsletter-read'; read.textContent = 'Read update'; read.setAttribute('aria-label', 'Read update: ' + post.title);
      read.setAttribute('aria-haspopup', 'dialog'); read.setAttribute('aria-controls', 'newsletterDialog');
      const arrow = document.createElement('span'); arrow.setAttribute('aria-hidden', 'true'); arrow.textContent = '↗'; read.append(arrow);
      read.addEventListener('click', () => openPost(post, read));
      if (!firstButton) firstButton = read;
      article.append(date, title, excerpt, read); feed.append(article);
    });
    shown += next.length;
    more.hidden = shown >= posts.length;
    window.PEACMotion?.reveal(feed);
    if (moveFocus) firstButton?.focus({preventScroll:true});
  }

  async function load() {
    if (loading) return;
    loading = true; retry.hidden = true; more.hidden = true; feed.setAttribute('aria-busy', 'true');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch('/api/public/newsletter', {cache:'no-store', credentials:'same-origin', signal:controller.signal});
      if (!response.ok) throw new Error('Newsletter unavailable');
      const data = await response.json();
      if (!Array.isArray(data.items)) throw new Error('Invalid newsletter response');
      posts = data.items.filter(item => item && typeof item.title === 'string' && typeof item.body === 'string' && item.published_at);
      shown = 0; feed.replaceChildren();
      if (!posts.length) showEmpty('The next update starts here.', 'There are no published updates yet. Check back for news from the PEAC team.');
      else appendPosts();
    } catch (_) {
      showEmpty('Updates could not load.', 'Please try again in a moment.');
      retry.hidden = false;
    } finally {
      clearTimeout(timeout); loading = false; feed.setAttribute('aria-busy', 'false');
    }
  }

  more.addEventListener('click', () => appendPosts(true));
  retry.addEventListener('click', load);
  $('closeNewsletter')?.addEventListener('click', () => dialog.close());
  $('backFromNewsletter')?.addEventListener('click', () => dialog.close());
  dialog?.addEventListener('close', () => {
    document.body.classList.remove('resource-dialog-open');
    if (returnFocus?.isConnected) returnFocus.focus({preventScroll:true});
    returnFocus = null;
  });
  dialog?.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  load();
})();

(() => {
  'use strict';
  const form = document.querySelector('[data-search-form]');
  if (!form) return;
  const input = form.querySelector('input[name="q"]');
  const status = document.querySelector('[data-search-status]');
  const results = document.querySelector('[data-search-results]');
  const root = form.dataset.root || '/';
  const normalize = value => String(value || '').normalize('NFKC').toLocaleLowerCase();
  let entries;
  let pending;
  let timer;
  let revision = 0;

  const tagNames = entry => (Array.isArray(entry.tags) ? entry.tags : []).map(tag => typeof tag === 'string' ? tag : tag.name || '');
  const bodyText = entry => String(entry.content || entry.body || entry.text || entry.summary || '');
  const safeUrl = entry => {
    const path = entry.path || entry.url;
    if (!path) return null;
    try {
      const url = new URL(path, location.origin + root);
      return url.origin === location.origin && url.pathname.startsWith(root) ? url.pathname + url.search + url.hash : null;
    } catch { return null; }
  };
  const load = () => {
    if (entries) return Promise.resolve(entries);
    if (!pending) {
      pending = fetch(form.dataset.index).then(response => {
        if (!response.ok) throw new Error('Search index unavailable');
        return response.json();
      }).then(data => {
        const list = Array.isArray(data) ? data : data.entries;
        if (!Array.isArray(list)) throw new Error('Invalid search index');
        entries = list.filter(entry => typeof entry.title === 'string' && safeUrl(entry)).map(entry => ({
          ...entry,
          searchable: normalize([entry.title, ...tagNames(entry), bodyText(entry)].join(' '))
        }));
        return entries;
      }).catch(error => { pending = null; throw error; });
    }
    return pending;
  };
  const snippet = (entry, terms) => {
    const text = bodyText(entry).replace(/\s+/g, ' ').trim();
    const normalized = normalize(text);
    const position = terms.map(term => normalized.indexOf(term)).filter(index => index >= 0).sort((a, b) => a - b)[0] || 0;
    const start = Math.max(0, position - 65);
    const excerpt = text.slice(start, start + 230);
    return (start ? '…' : '') + excerpt + (start + 230 < text.length ? '…' : '');
  };
  const render = (matches, terms) => {
    const fragment = document.createDocumentFragment();
    matches.forEach(entry => {
      const item = document.createElement('li');
      item.className = 'search-result';
      const heading = document.createElement('h2');
      const link = document.createElement('a');
      link.href = safeUrl(entry);
      link.textContent = entry.title;
      heading.append(link);
      item.append(heading);
      if (entry.draft) {
        const label = document.createElement('span');
        label.className = 'draft-label';
        label.textContent = 'Draft';
        item.append(label);
      } else if (entry.dateLabel) {
        const date = document.createElement('time');
        date.dateTime = entry.date || entry.dateLabel;
        date.textContent = entry.dateLabel;
        item.append(date);
      }
      const excerpt = snippet(entry, terms);
      if (excerpt) {
        const paragraph = document.createElement('p');
        paragraph.textContent = excerpt;
        item.append(paragraph);
      }
      fragment.append(item);
    });
    results.replaceChildren(fragment);
  };
  const search = async (updateUrl = true) => {
    const current = ++revision;
    const query = input.value.trim();
    if (updateUrl) {
      const url = new URL(location.href);
      if (query) url.searchParams.set('q', query);
      else url.searchParams.delete('q');
      history.replaceState(null, '', url.pathname + url.search + url.hash);
    }
    if (!query) {
      results.replaceChildren();
      status.textContent = 'Search article titles, topics, and text.';
      return;
    }
    status.textContent = 'Searching…';
    try {
      const data = await load();
      if (current !== revision) return;
      const terms = normalize(query).split(/\s+/).filter(Boolean);
      const matches = data.filter(entry => terms.every(term => entry.searchable.includes(term)));
      render(matches, terms);
      status.textContent = matches.length ? `${matches.length} ${matches.length === 1 ? 'article' : 'articles'} found.` : 'No articles found. Try another term, or browse the archive.';
    } catch {
      if (current !== revision) return;
      results.replaceChildren();
      status.textContent = 'Search is unavailable right now. You can still browse articles in the archive.';
    }
  };
  form.addEventListener('submit', event => { event.preventDefault(); clearTimeout(timer); search(); });
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => search(), 180); });
  window.addEventListener('popstate', () => { input.value = new URLSearchParams(location.search).get('q') || ''; search(false); });
  input.value = new URLSearchParams(location.search).get('q') || '';
  if (input.value) search(false);
})();

'use strict';

/** AI Frontier v1: only reads a static, pre-generated JSON file. */
const DATA_URL = './data/news.json';
const CHECK_EVERY_MS = 5 * 60 * 1000; // Site polls published JSON. Collection runs hourly elsewhere.
const STORAGE_SEEN = 'ai-frontier-seen-v1';
const STORAGE_THEME = 'ai-frontier-theme-v1';
const CATEGORY = {
  all: '全部资讯', official: '公司动态', industry: '行业新闻',
  papers: 'AI 论文', opensource: '开源生态',
};
const $ = (id) => document.getElementById(id);

const state = {
  data: null,
  tab: 'all',
  query: '',
  days: 'all',
  visibleCount: 12,
  seen: new Set(),
  initialized: false,
  loading: false,
};

function safeLoadStorage(key) {
  try { return localStorage.getItem(key); } catch (_) { return null; }
}
function safeSaveStorage(key, value) {
  try { localStorage.setItem(key, value); } catch (_) { /* Private browsing: temporary state. */ }
}
function formatDatetime(iso, dateOnly = false) {
  if (!iso) return '尚未更新';
  const d = new Date(iso);
  if (Number.isNaN(d.valueOf())) return '时间未知';
  const fmt = new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    ...(dateOnly ? {} : { hour: '2-digit', minute: '2-digit', hour12: false }),
  });
  return fmt.format(d);
}
function relativeTime(iso) {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return '时间未知';
  const minutes = Math.floor((Date.now() - t) / 60000);
  if (minutes < 0) return formatDatetime(iso, true);
  if (minutes < 60) return `${Math.max(1, minutes)} 分钟前`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)} 小时前`;
  if (minutes < 10080) return `${Math.floor(minutes / 1440)} 天前`;
  return formatDatetime(iso, true);
}
function el(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = String(content);
  return node;
}
function verifiedLink(href) {
  try {
    const url = new URL(href);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null;
  } catch (_) { return null; }
}
function sourceName(cat) { return CATEGORY[cat] || 'AI 动态'; }
function getItems() {
  const data = state.data?.items || [];
  const term = state.query.toLocaleLowerCase().trim();
  const cutoff = state.days === 'all' ? 0 : Date.now() - Number(state.days) * 86400000;
  return data.filter((item) => {
    if (state.tab !== 'all' && item.category !== state.tab) return false;
    if (cutoff && new Date(item.published_at).getTime() < cutoff) return false;
    if (term && !`${item.title || ''} ${item.source || ''} ${item.summary || ''}`.toLocaleLowerCase().includes(term)) return false;
    return true;
  });
}
function getUnread() {
  return (state.data?.items || []).filter((item) => !state.seen.has(item.id));
}
function saveSeen() {
  safeSaveStorage(STORAGE_SEEN, JSON.stringify({ ids: [...state.seen].slice(-1000), initialized: state.initialized }));
}
function hydrateSeen(data) {
  if (!state.initialized && data.items.length) {
    // First visit is a baseline, not an instant flood of NEW notifications.
    for (const item of data.items) state.seen.add(item.id);
    state.initialized = true;
    saveSeen();
  }
}
function markRead(id) {
  state.seen.add(id);
  saveSeen();
  renderUnread();
  renderCards();
}
function markAllRead() {
  for (const item of state.data?.items || []) state.seen.add(item.id);
  saveSeen();
  renderUnread();
  renderCards();
}
function renderUnread() {
  const newItems = state.initialized ? getUnread() : [];
  $('unreadBanner').classList.toggle('hidden', newItems.length === 0);
  $('unreadTitle').textContent = `发现 ${newItems.length} 条新资讯`;
}
function renderMetrics() {
  if (!state.data) return;
  const data = state.data;
  const items = data.items || [];
  $('metricTotal').textContent = items.length.toLocaleString('zh-CN');
  $('metricToday').textContent = items.filter((item) => new Date(item.published_at).getTime() >= Date.now() - 86400000).length;
  $('metricSources').textContent = `${data.successful_sources || 0} / ${data.total_sources || 0}`;
  $('metricUpdate').textContent = data.last_success_at ? formatDatetime(data.last_success_at).replace(/\d{4}\//, '') : '等待更新';
  for (const category of Object.keys(CATEGORY)) {
    const count = category === 'all' ? items.length : items.filter((item) => item.category === category).length;
    const badge = document.querySelector(`[data-count="${category}"]`);
    if (badge) badge.textContent = count;
  }
  const success = Number(data.successful_sources) || 0;
  const total = Number(data.total_sources) || 0;
  $('sourceHealth').textContent = `${success} / ${total} 个来源连接正常`;
  const dot = $('sourceDot');
  dot.className = 'source-dot ' + (data.status === 'ok' ? 'good' : data.status === 'partial' ? 'warn' : data.status === 'error' ? 'error' : '');
}
function showNotice(status, message) {
  const node = $('statusNotice');
  node.className = 'notice ' + (status === 'ok' ? 'notice-ok' : status === 'partial' || status === 'stale' ? 'notice-warn' : status === 'error' ? 'notice-error' : 'notice-loading');
  $('statusText').textContent = message;
  node.querySelector('.notice-symbol').textContent = status === 'ok' ? '✓' : status === 'error' ? '!' : status === 'stale' || status === 'partial' ? '⚠' : '◷';
}
function renderStatus() {
  if (!state.data) return;
  const d = state.data;
  if (!d.last_attempt_at) {
    showNotice('loading', '还没有执行首次采集。部署后进入 GitHub → Actions 手动运行「Update AI News」即可获取真实资讯。');
  } else if (d.status === 'error') {
    showNotice('error', '本轮全部来源采集失败。正在展示历史缓存；请在“数据来源”中检查各来源报错。');
  } else if (!d.last_success_at || Date.now() - new Date(d.last_success_at).getTime() > 150 * 60000) {
    showNotice('stale', `成功采集时间较久（${formatDatetime(d.last_success_at)}）。数据可能不是最新的，请检查定时任务。`);
  } else if (d.status === 'partial') {
    showNotice('partial', `新闻已更新；本轮 ${d.successful_sources}/${d.total_sources} 个来源成功，其余来源异常，历史内容已保留。`);
  } else {
    showNotice('ok', `数据最近更新于 ${formatDatetime(d.last_success_at)} · 每60分钟采集 · 新闻时间以原始来源为准`);
  }
}
function createCard(item) {
  const card = el('article', 'news-card');
  const meta = el('div', 'card-meta');
  const cat = el('span', `card-category ${item.category}`);
  cat.append(el('span', 'category-mini-dot'), document.createTextNode(sourceName(item.category)));
  meta.append(cat, el('span', 'card-source', item.source || '来源未知'));
  const time = el('time', 'card-time', relativeTime(item.published_at));
  time.dateTime = item.published_at;
  time.title = `${item.date_type === 'updated' ? '原始来源更新时间' : item.date_type === 'created' ? '模型创建时间' : '原始来源发布时间'}：${formatDatetime(item.published_at)}`;
  meta.append(time);
  card.append(meta);
  const title = el('h3');
  const url = verifiedLink(item.url);
  const titleLink = el('a', '', item.title || '(无标题)');
  if (url) {
    titleLink.href = url; titleLink.target = '_blank'; titleLink.rel = 'noopener noreferrer';
    titleLink.addEventListener('click', () => markRead(item.id));
  }
  title.append(titleLink);
  if (!state.seen.has(item.id) && state.initialized) title.append(el('span', 'new-pill', 'NEW'));
  card.append(title);
  card.append(el('p', 'card-summary', item.summary || '暂无摘要，请打开原始链接阅读完整信息。'));
  const footer = el('div', 'card-footer');
  const dateLabel = item.date_type === 'updated' ? '来源更新' : item.date_type === 'created' ? '仓库创建' : '原始发布';
  footer.append(el('span', 'card-type', `${dateLabel} · ${formatDatetime(item.published_at, true)}`));
  const read = el('a', 'card-read', '查看原文 ↗');
  if (url) {
    read.href = url; read.target = '_blank'; read.rel = 'noopener noreferrer';
    read.addEventListener('click', () => markRead(item.id));
  } else {
    read.href = '#'; read.addEventListener('click', (e) => e.preventDefault());
  }
  footer.append(read);
  card.append(footer);
  return card;
}
function renderCards() {
  const list = getItems();
  $('resultsCount').textContent = `共 ${list.length} 条符合条件的资讯`;
  const grid = $('newsGrid');
  grid.replaceChildren();
  const items = list.slice(0, state.visibleCount);
  if (!list.length) {
    const container = el('div', 'empty-state');
    const icon = el('div', 'empty-icon', '⌁');
    const heading = el('h3', '', state.data?.last_success_at ? '这里暂时没有符合条件的资讯' : '准备接收第一批 AI 新闻');
    const text = el('p', '', state.data?.last_success_at
      ? '尝试切换分类、扩大时间范围或修改搜索词；本站不会用模拟新闻填充页面。'
      : '前端已准备好。首次部署后，运行 GitHub Actions 定时采集工作流即可显示真实资讯。');
    container.append(icon, heading, text);
    grid.append(container);
  } else {
    const frag = document.createDocumentFragment();
    for (const item of items) frag.append(createCard(item));
    grid.append(frag);
  }
  $('loadMoreBtn').classList.toggle('hidden', list.length <= state.visibleCount);
}
function renderSourceList() {
  const list = $('sourceList');
  list.replaceChildren();
  const sources = state.data?.sources || [];
  if (!sources.length) {
    list.append(el('p', 'dialog-intro', '尚未采集到来源状态；首次执行采集后这里会显示详细结果。'));
    return;
  }
  for (const src of sources) {
    const row = el('div', 'source-row');
    const left = el('div');
    const line = el('div', 'source-row-title');
    const a = el('a', '', src.name || '数据源');
    const url = verifiedLink(src.url);
    if (url) { a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; }
    line.append(a);
    left.append(line, el('div', 'source-row-sub', src.ok ? `${sourceName(src.category)} · 本轮有效 ${src.count} 条` : (src.message || '采集失败')));
    row.append(left, el('span', `source-row-status ${src.ok ? 'ok' : 'failed'}`, src.ok ? '✓ 正常' : '× 异常'));
    list.append(row);
  }
}
function render() {
  renderMetrics();
  renderStatus();
  renderUnread();
  renderCards();
  renderSourceList();
}
async function loadData(userInitiated = false) {
  if (state.loading) return;
  state.loading = true;
  $('refreshBtn').classList.add('loading');
  try {
    const response = await fetch(`${DATA_URL}?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!data || !Array.isArray(data.items) || !Array.isArray(data.sources)) throw new Error('新闻数据结构无效');
    state.data = data;
    hydrateSeen(data);
    render();
    if (userInitiated && data.last_attempt_at) {
      // Just checks the static JSON; does not pretend to trigger a new crawl.
      $('refreshBtn').title = '已检查最新发布的数据（网页刷新不触发采集）';
    }
  } catch (err) {
    showNotice('error', `读取静态数据失败：${err.message}。若在本地预览，请运行 python -m http.server，而不是直接双击 HTML 文件。`);
    if (!state.data) {
      state.data = { items: [], sources: [], total_sources: 0, successful_sources: 0 };
      renderMetrics(); renderCards();
    }
  } finally {
    state.loading = false;
    $('refreshBtn').classList.remove('loading');
  }
}
function chooseTab(tab) {
  if (!(tab in CATEGORY)) return;
  state.tab = tab;
  state.visibleCount = 12;
  document.querySelectorAll('[data-tab]').forEach((btn) => {
    const selected = btn.dataset.tab === tab;
    btn.classList.toggle('active', selected);
    btn.setAttribute('aria-pressed', String(selected));
  });
  $('breadcrumbLabel').textContent = CATEGORY[tab];
  $('feedTitle').textContent = CATEGORY[tab] === '全部资讯' ? '前沿速递 ✳' : `${CATEGORY[tab]} ✳`;
  renderCards();
}
function setTheme(theme) {
  const dark = theme === 'dark';
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  $('themeGlyph').textContent = dark ? '☀' : '☾';
  $('themeBtn').setAttribute('aria-label', dark ? '切换浅色主题' : '切换深色主题');
  safeSaveStorage(STORAGE_THEME, theme);
}
function init() {
  const saved = safeLoadStorage(STORAGE_SEEN);
  if (saved) {
    try {
      const json = JSON.parse(saved);
      state.initialized = json.initialized === true;
      state.seen = new Set(Array.isArray(json.ids) ? json.ids : []);
    } catch (_) { /* Ignore invalid or old storage. */ }
  }
  setTheme(safeLoadStorage(STORAGE_THEME) === 'dark' ? 'dark' : 'light');
  $('themeBtn').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
  $('refreshBtn').addEventListener('click', () => loadData(true));
  $('markReadBtn').addEventListener('click', markAllRead);
  $('loadMoreBtn').addEventListener('click', () => { state.visibleCount += 12; renderCards(); });
  document.querySelectorAll('[data-tab]').forEach((btn) => btn.addEventListener('click', () => chooseTab(btn.dataset.tab)));
  $('searchInput').addEventListener('input', (e) => { state.query = e.target.value; state.visibleCount = 12; renderCards(); });
  $('dateFilter').addEventListener('change', (e) => { state.days = e.target.value; state.visibleCount = 12; renderCards(); });
  $('showSources').addEventListener('click', () => $('sourcesDialog').showModal());
  $('headerSourcesBtn').addEventListener('click', () => $('sourcesDialog').showModal());
  $('closeDialog').addEventListener('click', () => $('sourcesDialog').close());
  $('sourcesDialog').addEventListener('click', (e) => { if (e.target === $('sourcesDialog')) $('sourcesDialog').close(); });
  const renderClock = () => { $('localClock').textContent = new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date()); };
  renderClock();
  setInterval(renderClock, 30000);
  setInterval(() => { if (!document.hidden) loadData(); }, CHECK_EVERY_MS);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) loadData(); });
  chooseTab('all');
  loadData();
}
document.addEventListener('DOMContentLoaded', init);

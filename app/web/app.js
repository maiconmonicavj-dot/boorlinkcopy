/* boorlinkcopy — painel */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = (v) => v == null ? '' : Number(v).toLocaleString('pt-BR', {style:'currency', currency:'BRL'});

let challenge = null;

function toast(msg, kind = '') {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast ' + kind;
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add('hidden'), 3800);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: {'Content-Type': 'application/json'},
    ...opts,
  });
  let data = {};
  try { data = await res.json(); } catch (e) {}
  if (res.status === 423) { showLock(data.detail); throw new Error(data.detail || 'bloqueado'); }
  if (!res.ok) throw new Error(data.detail || ('erro ' + res.status));
  return data;
}

/* ---------- telas de autenticação ---------- */
function show(id) {
  ['formLogin','formRegister','setup2fa','verify2fa','formRecover'].forEach(x =>
    $('#' + x).classList.toggle('hidden', x !== id));
}
const showLogin = () => show('formLogin');
const showRegister = () => show('formRegister');
const showRecover = () => show('formRecover');

function showLock(reason) {
  $('#auth').classList.remove('hidden');
  $('#app').classList.add('hidden');
  $('#lockBanner').classList.remove('hidden');
  $('#lockReason').textContent = reason || '';
  showRecover();
}

$('#formLogin').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const r = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({email: $('#email').value, password: $('#password').value}),
    });
    if (r.status === 'need_2fa') {
      challenge = r.challenge;
      $('#verifyCode').value = '';
      show('verify2fa');
      $('#verifyCode').focus();
    } else if (r.status === 'setup_2fa') {
      await startSetup($('#email').value, $('#password').value);
    }
  } catch (err) { toast(err.message, 'bad'); }
});

$('#formRegister').addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = $('#regEmail').value, password = $('#regPass').value;
  try {
    await api('/api/auth/register', {method: 'POST', body: JSON.stringify({email, password})});
    await startSetup(email, password);
  } catch (err) { toast(err.message, 'bad'); }
});

async function startSetup(email, password) {
  const r = await api('/api/auth/setup-2fa', {method: 'POST', body: JSON.stringify({email, password})});
  $('#qrImg').src = r.qr_svg;
  $('#totpSecret').textContent = r.secret;
  $('#qrImg').dataset.email = email;
  $('#setupCode').value = '';
  show('setup2fa');
}

async function confirm2fa() {
  const email = $('#qrImg').dataset.email;
  try {
    await api('/api/auth/confirm-2fa', {
      method: 'POST', body: JSON.stringify({email, code: $('#setupCode').value}),
    });
    toast('2FA ativado. Bem-vindo!', 'ok');
    enterApp();
  } catch (err) { toast(err.message, 'bad'); }
}

async function verify2fa() {
  try {
    await api('/api/auth/verify', {
      method: 'POST', body: JSON.stringify({challenge, code: $('#verifyCode').value}),
    });
    enterApp();
  } catch (err) { toast(err.message, 'bad'); }
}

$('#formRecover').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api('/api/recover', {method: 'POST', body: JSON.stringify({password: $('#recoverPass').value})});
    toast('Sistema reativado. Faça login novamente.', 'ok');
    $('#lockBanner').classList.add('hidden');
    showLogin();
  } catch (err) { toast(err.message, 'bad'); }
});

async function logout() {
  await api('/api/auth/logout', {method: 'POST'});
  location.reload();
}

/* ---------- app ---------- */
async function enterApp() {
  $('#auth').classList.add('hidden');
  $('#app').classList.remove('hidden');
  const me = await api('/api/auth/me');
  $('#whoami').textContent = me.email;
  loadDashboard(); loadMenus(); loadOffers(); loadStores(); loadCoupons(); loadRuns(); loadEvents();
}

async function boot() {
  const st = await api('/api/status');
  if (st.locked) { showLock(st.locked_reason); return; }
  try { await api('/api/auth/me'); enterApp(); }
  catch (e) { showLogin(); }
}

$$('.tab').forEach(t => t.addEventListener('click', () => {
  $$('.tab').forEach(x => x.classList.toggle('active', x === t));
  $$('.tabpane').forEach(p => p.classList.toggle('hidden', p.id !== 'tab-' + t.dataset.tab));
  if (t.dataset.tab === 'seguranca') loadEvents();
  if (t.dataset.tab === 'cupons') loadCoupons();
  if (t.dataset.tab === 'robo') { loadRuns(); loadCriteria(); }
  if (t.dataset.tab === 'telegram') loadTelegram();
}));

async function loadDashboard() {
  const d = await api('/api/dashboard');
  const card = (n, l) => `<div class="card"><div class="n">${n}</div><div class="l">${l}</div></div>`;
  $('#dashCards').innerHTML = card(d.offers, 'ofertas ativas') + card(d.blocked, 'bloqueadas') +
    card(d.coupons, 'cupons') + card(d.stores, 'lojas') + card(d.alerts, 'alertas de segurança');
}

let activeDeal = '';

async function loadMenus() {
  const [c, d] = await Promise.all([api('/api/categories'), api('/api/deals')]);
  $('#dealMenu').innerHTML = Object.entries(d.labels).map(([k, v]) => {
    const n = (d.deals[k] || []).length;
    return `<button class="deal ${activeDeal === k ? 'active' : ''}" onclick="pickDeal('${k}')">
      <span class="em">${v[0]}</span><span>${esc(v[1])}</span><b>${n}</b></button>`;
  }).join('');
  $('#catMenu').innerHTML = c.categories.filter(x => x.count > 0).map(x =>
    `<button class="cat ${activeDeal === 'cat:' + x.slug ? 'active' : ''}"
      onclick="pickDeal('cat:${x.slug}')">${x.emoji} ${esc(x.label)} <b>${x.count}</b></button>`).join('');
  const sel = $('#offerCategory');
  if (sel.options.length <= 1) {
    sel.innerHTML = '<option value="">todas as categorias</option>' +
      c.categories.map(x => `<option value="${x.slug}">${esc(x.label)}</option>`).join('');
  }
}

function pickDeal(key) {
  activeDeal = activeDeal === key ? '' : key;
  $('#offerSearch').value = '';
  $('#offerStatus').value = 'approved';
  loadMenus(); loadOffers();
}

async function loadOffers() {
  const status = $('#offerStatus').value;
  const q = $('#offerSearch').value.trim();
  let url = `/api/offers?status=${status}${q ? '&q=' + encodeURIComponent(q) : ''}`;
  const cat = $('#offerCategory').value;
  if (activeDeal.startsWith('cat:')) url += '&category=' + activeDeal.slice(4);
  else if (activeDeal) url += '&deal=' + activeDeal;
  else if (cat) url += '&category=' + cat;
  const {offers} = await api(url);
  $('#offersList').innerHTML = offers.length ? offers.map(o => {
    const cp = o.coupon ? `<div class="coupon"><span>Cupom</span><code>${esc(o.coupon.code || '')}</code>
        <button class="btn sm" onclick="copyText('${esc(o.coupon.code || '')}')">copiar</button></div>` : '';
    const bad = o.status === 'blocked'
      ? `<span class="badge bad" title="${esc(o.block_reason || '')}">bloqueada</span>
         <div class="muted small">${esc(o.block_reason || '')}</div>` : '';
    return `<article class="offer">
      <img src="${esc(o.image_url || '/static/noimage.svg')}" alt="${esc(o.title)}"
           loading="lazy" onerror="this.onerror=null;this.src='/static/noimage.svg'">
      <div class="body">
        <span class="badge">${esc(o.store_name)}</span>
        <span class="badge">${esc(o.category_label || '')}</span>
        <div class="title">${esc(o.title)}</div>
        <div><span class="price">${money(o.price)}</span>
          ${o.original_price ? `<span class="old">${money(o.original_price)}</span>` : ''}
          ${o.discount_pct ? `<span class="badge disc">-${Math.round(o.discount_pct)}%</span>` : ''}</div>
        ${o.seller_name ? `<div class="muted small">vendedor: ${esc(o.seller_name)}
          ${o.seller_rating ? ' · ⭐ ' + o.seller_rating : ''}</div>` : ''}
        ${cp}${bad}
        <div class="actions">
          <a class="btn ok" href="/api/offers/${o.id}/go" target="_blank" rel="noopener">Ir para a oferta</a>
          <button class="btn" onclick="copyText('${esc(o.affiliate_url || o.original_url)}')">Copiar link</button>
        </div>
        <button class="btn ghost sm" onclick="fixImage(${o.id})">Buscar foto no link</button>
      </div></article>`;
  }).join('') : '<p class="muted">Nenhuma oferta aqui ainda. Rode um ciclo do robô ou cadastre uma loja com API.</p>';
}

async function fixImage(id) {
  toast('Buscando a foto real do produto...');
  try {
    const r = await api(`/api/offers/${id}/refresh-image`, {method: 'POST'});
    toast('Foto atualizada', 'ok');
    loadOffers();
  } catch (e) { toast(e.message, 'bad'); }
}

async function backfillImages() {
  toast('Buscando as fotos reais nos links das ofertas...');
  try {
    const r = await api('/api/images/backfill', {method: 'POST'});
    toast(`Analisadas ${r.checked}: ${r.fixed} com foto real, ${r.placeholders} sem foto no link`, 'ok');
    loadOffers();
  } catch (e) { toast(e.message, 'bad'); }
}

async function copyText(txt) {
  try { await navigator.clipboard.writeText(txt); toast('Copiado!', 'ok'); }
  catch (e) { toast(txt, ''); }
}

async function convertLinks() {
  const links = $('#linksInput').value;
  const tag = $('#tagOverride').value.trim() || null;
  try {
    const {results} = await api('/api/convert', {method: 'POST', body: JSON.stringify({links, tag})});
    $('#convertResults').innerHTML = results.map(r => r.ok
      ? `<div class="result"><span class="lbl">${esc(r.store_name)} · tag ${esc(r.tag)}</span>
           <a href="${esc(r.affiliate_url)}" target="_blank" rel="noopener">${esc(r.affiliate_url)}</a>
           <button class="btn sm" onclick="copyText('${esc(r.affiliate_url)}')">copiar link de afiliado</button></div>`
      : `<div class="result"><span class="lbl">não convertido</span>${esc(r.input)}
           <span class="badge bad">${esc(r.error || 'erro')}</span></div>`).join('');
  } catch (err) { toast(err.message, 'bad'); }
}

async function loadStores() {
  const {stores} = await api('/api/stores');
  $('#storesList').innerHTML = stores.map(s => `
    <div class="store" data-slug="${esc(s.slug)}">
      <strong>${esc(s.name)} <span class="muted small">(${esc(s.domain)})</span></strong>
      <label class="small">tag de afiliado
        <input class="st-tag" value="${esc(s.affiliate_value || '')}" placeholder="ex: maicon-20"></label>
      <label class="small">parâmetro <input class="st-param" value="${esc(s.affiliate_param)}"></label>
      <label class="small">tipo de API
        <select class="st-kind">
          ${['manual','generic','mercado_livre','amazon','shopee'].map(k =>
            `<option ${k === s.api_kind ? 'selected' : ''}>${k}</option>`).join('')}
        </select></label>
      <label class="small">base da API <input class="st-base" value="${esc(s.api_base || '')}" placeholder="https://api.loja.com"></label>
      <label class="small">refresh token ${s.refresh_token_set ? '<span class="badge">configurado</span>' : ''}
        <input class="st-rt" type="password" placeholder="${s.refresh_token_set ? '•••• (manter)' : 'cole o refresh token'}"></label>
      <label class="small">reputação mínima <input class="st-rating" type="number" step="0.1" value="${s.min_rating}"></label>
      <div class="row">
        <button class="btn primary sm" onclick="saveStore('${esc(s.slug)}')">Salvar</button>
        <button class="btn sm" onclick="refreshToken('${esc(s.slug)}')">Renovar token</button>
      </div>
    </div>`).join('');
  const opts = stores.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
  $('#couponStore').innerHTML = opts;
  $('#robotStore').innerHTML = '<option value="">todas as lojas</option>' +
    stores.map(s => `<option value="${esc(s.slug)}">${esc(s.name)}</option>`).join('');
}

async function saveStore(slug) {
  const card = $(`.store[data-slug="${slug}"]`);
  const body = {
    slug,
    name: card.querySelector('strong').textContent.split('(')[0].trim(),
    domain: card.querySelector('.muted').textContent.replace(/[()]/g, '').trim(),
    affiliate_value: card.querySelector('.st-tag').value.trim(),
    affiliate_param: card.querySelector('.st-param').value.trim() || 'tag',
    api_kind: card.querySelector('.st-kind').value,
    api_base: card.querySelector('.st-base').value.trim() || null,
    refresh_token: card.querySelector('.st-rt').value.trim() || null,
    min_rating: parseFloat(card.querySelector('.st-rating').value) || 4.0,
  };
  try { await api('/api/stores', {method: 'POST', body: JSON.stringify(body)}); toast('Loja salva', 'ok'); }
  catch (e) { toast(e.message, 'bad'); }
}

async function refreshToken(slug) {
  try {
    const r = await api(`/api/stores/${slug}/refresh-token`, {method: 'POST'});
    toast('Token renovado até ' + r.expires_at, 'ok');
  } catch (e) { toast(e.message, 'bad'); }
}

async function loadCoupons() {
  const {coupons} = await api('/api/coupons');
  $('#couponsList').innerHTML = coupons.length ? coupons.map(c => `
    <article class="offer"><div class="body">
      <span class="badge">${esc(c.store_name)}</span>
      <div class="title">${esc(c.title)}</div>
      ${c.code ? `<div class="coupon"><code>${esc(c.code)}</code>
        <button class="btn sm" onclick="copyText('${esc(c.code)}')">copiar</button></div>` : ''}
      <div class="actions">
        ${c.affiliate_url ? `<a class="btn ok" href="${esc(c.affiliate_url)}" target="_blank" rel="noopener">Ir para a oferta</a>` : ''}
      </div>
    </div></article>`).join('') : '<p class="muted">Nenhum cupom ativo.</p>';
}

async function addCoupon() {
  const body = {
    store_id: Number($('#couponStore').value),
    code: $('#couponCode').value.trim() || null,
    title: $('#couponTitle').value.trim() || 'Cupom',
    url: $('#couponUrl').value.trim() || null,
  };
  try { await api('/api/coupons', {method: 'POST', body: JSON.stringify(body)});
    toast('Cupom salvo', 'ok'); loadCoupons(); } catch (e) { toast(e.message, 'bad'); }
}

async function runRobot() {
  const store = $('#robotStore').value;
  toast('Ciclo do robô iniciado...');
  try {
    const r = await api('/api/robot/run' + (store ? '?store=' + store : ''), {method: 'POST'});
    toast(`Coletadas ${r.collected}, bloqueadas ${r.blocked}`, 'ok');
    loadRuns(); loadOffers(); loadDashboard();
  } catch (e) { toast(e.message, 'bad'); }
}

async function loadRuns() {
  const {runs} = await api('/api/robot/runs');
  $('#robotRuns').innerHTML = runs.length ? runs.map(r => `
    <div class="result"><span class="lbl">${esc(r.started_at)} · ${esc(r.status)}</span>
      coletadas: <strong>${r.collected}</strong> · bloqueadas: <strong>${r.blocked}</strong>
      ${r.detail ? `<span class="muted small">${esc(r.detail)}</span>` : ''}</div>`).join('')
    : '<p class="muted">Nenhum ciclo executado ainda.</p>';
}

async function loadTelegram() {
  const t = await api('/api/telegram');
  $('#tgCards').innerHTML =
    `<div class="card"><div class="n">${t.configured ? 'ON' : 'OFF'}</div><div class="l">publicação</div></div>` +
    `<div class="card"><div class="n">${t.pending}</div><div class="l">ofertas pendentes</div></div>` +
    `<div class="card"><div class="n">${t.min_discount}%</div><div class="l">desconto mínimo</div></div>`;
  if (t.chat_id) $('#tgChat').value = t.chat_id;
  const {offers} = await api('/api/offers?status=approved&limit=1');
  if (offers.length) {
    const p = await api(`/api/telegram/preview?offer_id=${offers[0].id}`);
    $('#tgPreview').innerHTML = `<div class="result"><span class="lbl">${p.worth ? 'vale postar' : 'não vale postar'}</span>
      <pre class="tgtext">${esc(p.text).replace(/\n/g, '<br>')}</pre>
      <span class="muted small">${esc(p.reasons.join(' · '))}</span></div>`;
  }
}

async function saveTelegram() {
  try {
    await api('/api/telegram', {method: 'POST', body: JSON.stringify({
      token: $('#tgToken').value.trim() || null,
      chat_id: $('#tgChat').value.trim() || null})});
    toast('Configuração salva', 'ok'); loadTelegram();
  } catch (e) { toast(e.message, 'bad'); }
}

async function testTelegram() {
  try {
    const r = await api('/api/telegram/test', {method: 'POST'});
    toast(r.ok ? 'Mensagem de teste enviada' : (r.error || 'falhou'), r.ok ? 'ok' : 'bad');
  } catch (e) { toast(e.message, 'bad'); }
}

async function publishTelegram() {
  toast('Publicando as melhores ofertas...');
  try {
    const r = await api('/api/telegram/publish', {method: 'POST'});
    toast(`Postadas ${r.posted} · puladas ${r.skipped}${r.errors.length ? ' · ' + r.errors[0] : ''}`,
      r.errors.length ? 'bad' : 'ok');
    loadTelegram(); loadOffers();
  } catch (e) { toast(e.message, 'bad'); }
}

function criteriaBody() {
  return {
    min_discount: Number($('#critDiscount').value),
    min_score: Number($('#critScore').value),
    min_rating: Number($('#critRating').value),
    min_sales: Number($('#critSales').value),
    max_posts: Number($('#critMaxPosts').value),
    post_interval: Number($('#critInterval').value),
    hot_keywords: $('#critHot').value,
    hot_blocked: $('#critBlocked').value,
    caution_keywords: $('#critCaution').value,
    risk_terms: $('#critRisk').value,
  };
}

async function loadCriteria() {
  const c = await api('/api/criteria');
  const k = c.criteria;
  $('#critDiscount').value = k.min_discount;
  $('#critScore').value = k.min_score;
  $('#critRating').value = k.min_rating;
  $('#critSales').value = k.min_sales;
  $('#critMaxPosts').value = k.max_posts;
  $('#critInterval').value = k.post_interval;
  $('#critHot').value = c.hot_custom;
  $('#critBlocked').value = c.hot_blocked;
  $('#critCaution').value = c.caution_custom;
  $('#critRisk').value = c.risk_terms;
  $('#critDefaults').textContent = 'Palavras-chave padrão que já contam: ' +
    c.hot_default.join(', ') + '. Cautela: ' + c.caution_default.join(', ') + '.';
}

async function previewCriteria() {
  try {
    const r = await api('/api/criteria/preview', {method: 'POST', body: JSON.stringify(criteriaBody())});
    $('#critPreview').innerHTML = `<div class="result">
      <span class="lbl">com estes critérios</span>
      <strong>${r.pass}</strong> de ${r.total} ofertas passariam (${r.fail} ficariam de fora)
      ${r.examples_pass.length ? `<span class="muted small">passam: ${esc(r.examples_pass.join(' · '))}</span>` : ''}
      ${r.examples_fail.length ? `<span class="muted small">fora: ${esc(r.examples_fail.map(x => x[0] + ' (' + x[1].join(', ') + ')').join(' · '))}</span>` : ''}
    </div>`;
  } catch (e) { toast(e.message, 'bad'); }
}

async function saveCriteria() {
  try {
    await api('/api/criteria', {method: 'POST', body: JSON.stringify(criteriaBody())});
    toast('Critérios salvos', 'ok');
    loadCriteria(); loadOffers(); loadDashboard();
  } catch (e) { toast(e.message, 'bad'); }
}

async function loadEvents() {
  const {events, locked} = await api('/api/security/events');
  if (locked) showLock('Sistema desligado por segurança.');
  $('#secCards').innerHTML = `<div class="card"><div class="n">${events.length}</div><div class="l">eventos recentes</div></div>
    <div class="card"><div class="n">${locked ? 'OFF' : 'ON'}</div><div class="l">estado do sistema</div></div>`;
  $('#eventsList').innerHTML = events.map(e => `
    <div class="event ${esc(e.severity)}"><span class="k">${esc(e.kind)}</span>
      <span class="muted">${esc(e.created_at)}</span>
      <span>${esc(e.detail || '')}</span>
      ${e.ip ? `<span class="muted small">${esc(e.ip)}</span>` : ''}</div>`).join('');
}

boot();

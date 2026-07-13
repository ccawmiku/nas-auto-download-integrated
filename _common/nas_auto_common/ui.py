from __future__ import annotations


COMMON_APP_CSS = """
:root {
  color-scheme: light;
  --bg:#f4f7f7;
  --panel:#ffffff;
  --panel-soft:#f7faf9;
  --panel-strong:#eef4f3;
  --line:#dbe4e2;
  --line-strong:#bdcbc8;
  --text:#17211f;
  --muted:#64716e;
  --accent:#087f78;
  --accent-strong:#05645f;
  --accent-soft:#e6f5f2;
  --ink:#082f32;
  --ok:#087a4e;
  --ok-bg:#eaf8f1;
  --ok-line:#bde8d1;
  --warn:#a45a04;
  --warn-bg:#fff6e8;
  --warn-line:#f5d7a7;
  --danger:#c12d2d;
  --danger-bg:#fff0f0;
  --danger-line:#f3c4c4;
  --info:#2563a6;
  --info-bg:#edf5ff;
  --shadow:0 18px 48px rgba(8,47,50,.08);
  --shadow-soft:0 6px 22px rgba(8,47,50,.055);
  --radius:14px;
  --radius-sm:9px;
}
* { box-sizing:border-box; }
html { min-width:320px; background:var(--bg); }
body {
  margin:0;
  font-family:Inter,"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,-apple-system,Segoe UI,sans-serif;
  background:var(--bg);
  color:var(--text);
  line-height:1.55;
  font-size:14px;
  -webkit-font-smoothing:antialiased;
}
header {
  min-height:72px;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:16px;
  padding:0 28px;
  background:rgba(255,255,255,.96);
  color:var(--text);
  border-bottom:1px solid var(--line);
}
main {
  width:min(1240px,100%);
  margin:0 auto;
  padding:24px;
  display:grid;
  gap:18px;
}
section,
.card {
  min-width:0;
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:var(--radius);
  padding:20px;
  box-shadow:var(--shadow-soft);
}
section > :first-child,
.card > :first-child { margin-top:0; }
section > :last-child,
.card > :last-child { margin-bottom:0; }
h1,h2,h3,strong { letter-spacing:-.015em; }
h1 { font-size:20px; line-height:1.25; margin:0; font-weight:760; }
h2 { font-size:17px; line-height:1.35; margin:0 0 14px; font-weight:740; }
h3 { font-size:14px; margin:0 0 10px; }
.eyebrow { display:block; color:var(--accent); font-size:11px; font-weight:800; letter-spacing:.09em; text-transform:uppercase; margin-bottom:4px; }
.page-summary { color:var(--muted); font-size:13px; margin:4px 0 0; }
.section-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin-bottom:14px; }
.section-heading h2 { margin:0; }
p { margin:8px 0; }
a { color:var(--accent-strong); text-underline-offset:3px; }
code { color:var(--accent-strong); background:var(--accent-soft); border-radius:6px; padding:2px 6px; }
form { margin:0; }
label { display:block; color:#42504d; font-size:13px; font-weight:650; margin:12px 0 6px; }
input,
textarea,
select {
  width:100%;
  border:1px solid var(--line-strong);
  border-radius:var(--radius-sm);
  padding:10px 12px;
  font:inherit;
  background:#fff;
  color:var(--text);
  transition:border-color .15s, box-shadow .15s, background .15s;
}
input,select { min-height:42px; }
textarea { min-height:124px; resize:vertical; }
textarea[data-sensitive]:not(.revealed) { -webkit-text-security:disc; }
input:hover,textarea:hover,select:hover { border-color:#9badaa; }
input:focus,
textarea:focus,
select:focus {
  outline:0;
  border-color:var(--accent);
  box-shadow:0 0 0 4px rgba(8,127,120,.14);
}
button,
.button {
  min-height:40px;
  border:1px solid transparent;
  background:var(--accent);
  color:#fff;
  border-radius:var(--radius-sm);
  padding:9px 15px;
  cursor:pointer;
  font:inherit;
  font-weight:700;
  line-height:1.2;
  text-decoration:none;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:7px;
  transition:background .15s, border-color .15s, box-shadow .15s, transform .12s, opacity .15s;
}
button:hover,.button:hover { background:var(--accent-strong); box-shadow:0 8px 20px rgba(8,127,120,.18); }
button:active,.button:active { transform:translateY(1px); }
button:focus-visible,.button:focus-visible,a:focus-visible { outline:3px solid rgba(8,127,120,.32); outline-offset:2px; }
button.secondary,.button.secondary { background:#f2f6f5; color:var(--text); border-color:var(--line); }
button.secondary:hover,.button.secondary:hover { background:#e7efed; box-shadow:none; }
button.danger,.button.danger { background:var(--danger); }
button.danger:hover,.button.danger:hover { background:#9f2424; box-shadow:0 8px 20px rgba(193,45,45,.2); }
button:disabled,.button.disabled { opacity:.5; cursor:not-allowed; box-shadow:none; transform:none; }
.grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
.auto-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; }
.stats-grid > div { border:1px solid var(--line); border-radius:11px; padding:13px; background:var(--panel-soft); }
.stats-grid strong { display:block; margin-top:4px; font-size:17px; }
.actions { display:flex; align-items:center; gap:9px; flex-wrap:wrap; margin-top:14px; }
.actions form { display:inline-flex; }
.status { display:flex; gap:8px; align-items:center; justify-content:flex-end; flex-wrap:wrap; }
.pill {
  display:inline-flex;
  align-items:center;
  gap:6px;
  min-height:28px;
  border-radius:999px;
  background:#eef3f2;
  color:#3d4a47;
  border:1px solid var(--line);
  padding:4px 10px;
  font-size:12px;
  font-weight:720;
  white-space:nowrap;
}
.pill::before { content:""; width:7px; height:7px; border-radius:50%; background:#879692; }
.pill.ok,.pill.ready { background:var(--ok-bg); color:var(--ok); border-color:var(--ok-line); }
.pill.ok::before,.pill.ready::before { background:var(--ok); }
.pill.warn,.pill.starting { background:var(--warn-bg); color:var(--warn); border-color:var(--warn-line); }
.pill.warn::before,.pill.starting::before { background:var(--warn); }
.pill.danger { background:var(--danger-bg); color:var(--danger); border-color:var(--danger-line); }
.pill.danger::before { background:var(--danger); }
.muted { color:var(--muted); }
.help { color:var(--muted); font-size:13px; line-height:1.7; max-width:88ch; }
.ok,.notice-success { background:var(--ok-bg); border-color:var(--ok-line); color:#075c3d; }
.notice-warning { background:var(--warn-bg); border-color:var(--warn-line); color:#73420a; }
.notice-danger { background:var(--danger-bg); border-color:var(--danger-line); color:#8c2020; }
.card {
  display:grid;
  grid-template-columns:1fr auto;
  gap:7px 12px;
  text-decoration:none;
  color:inherit;
  transition:border-color .15s, box-shadow .15s, transform .12s;
}
.card:hover { border-color:var(--line-strong); box-shadow:var(--shadow); transform:translateY(-1px); }
.card strong { font-size:17px; }
.card span { color:var(--muted); grid-column:1/-1; }
.card em { font-style:normal; border-radius:999px; padding:3px 9px; background:#eef3f2; color:var(--muted); font-size:12px; }
.card.ready em { background:var(--ok-bg); color:var(--ok); }
.card.starting em { background:var(--warn-bg); color:var(--warn); }
table { width:100%; border-collapse:separate; border-spacing:0; font-size:13px; }
th,td { border-bottom:1px solid var(--line); padding:11px 10px; text-align:left; vertical-align:top; }
th { color:#596663; font-weight:720; background:var(--panel-soft); white-space:nowrap; }
thead th:first-child { border-radius:8px 0 0 8px; }
thead th:last-child { border-radius:0 8px 8px 0; }
tbody tr:last-child td { border-bottom:0; }
tbody tr:hover td { background:#fbfdfc; }
.wide-table,.table-scroll { width:100%; overflow:auto; border-radius:10px; }
pre {
  margin:0;
  background:#102326;
  color:#dceae7;
  padding:15px;
  border-radius:10px;
  overflow:auto;
  max-height:520px;
  min-height:68px;
  white-space:pre-wrap;
  overflow-wrap:anywhere;
  word-break:break-word;
  font-size:12px;
  line-height:1.65;
}
progress { width:100%; height:10px; border:0; border-radius:999px; overflow:hidden; accent-color:var(--accent); }
.progress-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-top:14px; }
.metric { border:1px solid var(--line); border-radius:12px; padding:14px; background:var(--panel-soft); }
.metric strong { display:block; font-size:20px; margin-top:5px; }
.metric .label { color:var(--muted); font-size:12px; font-weight:650; }
.metric .value { font-size:21px; font-weight:780; overflow-wrap:anywhere; }
.empty-state { color:var(--muted); text-align:center; padding:28px 18px; border:1px dashed var(--line-strong); border-radius:10px; background:var(--panel-soft); }
details { margin:12px 0; border:1px solid var(--line); border-radius:10px; padding:10px 12px; background:var(--panel-soft); }
summary { cursor:pointer; font-weight:700; color:#3d4a47; }
details[open] summary { margin-bottom:8px; }
.sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
@media (max-width:760px) {
  header { min-height:auto; padding:15px; align-items:flex-start; flex-direction:column; }
  header .status { justify-content:flex-start; }
  main { padding:14px; gap:14px; }
  section,.card { padding:16px; border-radius:12px; }
  .grid,.progress-grid { grid-template-columns:1fr; }
  .actions { align-items:stretch; }
  .actions form,.actions button,.actions .button { width:100%; }
  table { min-width:680px; }
  section:has(> table) { overflow-x:auto; }
}
""".strip()


COMMON_APP_SCRIPT = """
(() => {
  const controls = [...document.querySelectorAll('input, textarea, select')];
  controls.forEach((control, index) => {
    if (!control.id) control.id = `field-${index + 1}`;
    const parent = control.parentElement;
    const label = parent?.querySelector(':scope > label:not([for])') || control.previousElementSibling;
    if (label instanceof HTMLLabelElement && !label.htmlFor) label.htmlFor = control.id;
  });
  document.querySelectorAll('[data-live]').forEach((node) => {
    node.setAttribute('role', 'status');
    node.setAttribute('aria-live', 'polite');
  });
  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      const message = form.getAttribute('data-confirm') || '确认继续执行此操作？';
      if (!window.confirm(message)) event.preventDefault();
    });
  });
  document.querySelectorAll('form').forEach((form) => {
    form.addEventListener('submit', () => {
      const button = form.querySelector('button[type="submit"]');
      if (!button || form.dataset.keepEnabled === 'true') return;
      window.setTimeout(() => {
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
      }, 0);
    });
  });
  document.querySelectorAll('textarea[data-sensitive]').forEach((field) => {
    const wrap = document.createElement('div');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary';
    button.textContent = '显示敏感内容';
    button.setAttribute('aria-pressed', 'false');
    button.addEventListener('click', () => {
      const revealed = field.classList.toggle('revealed');
      button.textContent = revealed ? '隐藏敏感内容' : '显示敏感内容';
      button.setAttribute('aria-pressed', String(revealed));
    });
    wrap.className = 'actions';
    wrap.appendChild(button);
    field.insertAdjacentElement('afterend', wrap);
  });
})();
""".strip()


def app_css(extra: str = "") -> str:
    parts = [COMMON_APP_CSS]
    if extra.strip():
        parts.append(extra.strip())
    return "\n".join(parts)


def app_script(extra: str = "") -> str:
    parts = [COMMON_APP_SCRIPT]
    if extra.strip():
        parts.append(extra.strip())
    return "\n".join(parts)

from __future__ import annotations

COMMON_APP_CSS = """
:root {
  color-scheme: light;
  --bg:#f6f7f9;
  --panel:#fff;
  --panel-soft:#fbfcfe;
  --line:#d9dde5;
  --text:#1d2433;
  --muted:#657084;
  --accent:#111827;
  --accent-soft:#475569;
  --ok:#047857;
  --ok-bg:#ecfdf5;
  --ok-line:#bbf7d0;
  --warn:#b45309;
  --warn-bg:#fff7ed;
}
body {
  margin:0;
  font-family:system-ui,-apple-system,Segoe UI,sans-serif;
  background:var(--bg);
  color:var(--text);
}
header {
  min-height:60px;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  padding:0 24px;
  background:var(--accent);
  color:white;
}
main {
  max-width:1180px;
  margin:0 auto;
  padding:20px;
  display:grid;
  gap:16px;
}
section,
.card {
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:8px;
  padding:16px;
}
h1 { font-size:18px; margin:0; }
h2 { font-size:16px; margin:0 0 12px; }
label { display:block; color:var(--muted); font-size:13px; margin:10px 0 5px; }
input,
textarea,
select {
  width:100%;
  box-sizing:border-box;
  border:1px solid var(--line);
  border-radius:6px;
  padding:9px 10px;
  font:inherit;
  background:white;
}
textarea { min-height:120px; resize:vertical; }
button {
  border:0;
  background:var(--accent);
  color:white;
  border-radius:6px;
  padding:9px 14px;
  cursor:pointer;
  font:inherit;
}
button.secondary { background:var(--accent-soft); }
button:disabled { opacity:.55; cursor:not-allowed; }
.grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.auto-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }
.actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
.status { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.pill {
  display:inline-flex;
  align-items:center;
  border-radius:999px;
  background:#e6edf6;
  color:#334155;
  padding:3px 8px;
  font-size:12px;
}
.pill.ok { background:var(--ok-bg); color:var(--ok); }
.pill.warn { background:var(--warn-bg); color:var(--warn); }
.muted { color:var(--muted); }
.help { color:var(--muted); font-size:13px; line-height:1.65; }
.ok { background:var(--ok-bg); border-color:var(--ok-line); }
.card {
  display:grid;
  grid-template-columns:1fr auto;
  gap:5px 12px;
  text-decoration:none;
  color:inherit;
  transition:border-color .15s, box-shadow .15s;
}
.card:hover { border-color:#9aa7b7; box-shadow:0 1px 5px rgba(15,23,42,.08); }
.card strong { font-size:17px; }
.card span { color:var(--muted); grid-column:1/-1; }
.card em {
  font-style:normal;
  border-radius:999px;
  padding:2px 8px;
  background:#eef2f7;
  color:var(--muted);
  font-size:12px;
}
.card.ready em { background:var(--ok-bg); color:var(--ok); }
.card.starting em { background:var(--warn-bg); color:var(--warn); }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,
td { border-bottom:1px solid var(--line); padding:8px; text-align:left; vertical-align:top; }
pre {
  margin:0;
  background:#0f172a;
  color:#dbeafe;
  padding:12px;
  border-radius:6px;
  overflow:auto;
  max-height:520px;
  white-space:pre-wrap;
  overflow-wrap:anywhere;
  word-break:break-word;
}
progress { width:100%; height:16px; accent-color:var(--accent); }
.progress-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-top:12px; }
.metric { border:1px solid var(--line); border-radius:8px; padding:10px; background:var(--panel-soft); }
.metric strong { display:block; font-size:18px; margin-top:4px; }
@media (max-width:760px) {
  header { padding:10px 14px; align-items:flex-start; flex-direction:column; }
  main { padding:12px; }
  .grid,
  .progress-grid { grid-template-columns:1fr; }
}
""".strip()


def app_css(extra: str = "") -> str:
    parts = [COMMON_APP_CSS]
    if extra.strip():
        parts.append(extra.strip())
    return "\n".join(parts)

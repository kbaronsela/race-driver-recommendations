#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Embed data/restaurants.json into view_restaurants.html for local file:// viewing."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "restaurants.json"
OUT = ROOT / "view_restaurants.html"

JS_TEMPLATE = r"""
    const data = __JSON__;
    const tbody = document.getElementById('tbody');
    const searchEl = document.getElementById('search');
    const typeFilter = document.getElementById('typeFilter');
    const countEl = document.getElementById('count');

    const types = [...new Set(data.map(r => (r.restaurant_type || '').trim()).filter(Boolean))].sort((a,b) => a.localeCompare(b, 'he'));
    const noTypeOpt = document.createElement('option');
    noTypeOpt.value = '__no_type__';
    noTypeOpt.textContent = 'ללא סוג';
    typeFilter.appendChild(noTypeOpt);
    types.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t;
      typeFilter.appendChild(opt);
    });

    function render(rows) {
      tbody.innerHTML = rows.map(r => {
        const name = escapeHtml(r.name || '');
        const typ = escapeHtml((r.restaurant_type || '').trim());
        const loc = escapeHtml((r.location || '').trim());
        const web = (r.website || '').trim();
        const webCell = web
          ? '<a href="' + escapeAttr(web) + '" rel="noopener noreferrer" target="_blank">' + escapeHtml(web) + '</a>'
          : '<span class="empty">—</span>';
        const note = escapeHtml((r.note || '').slice(0, 300)) + ((r.note || '').length > 300 ? '…' : '');
        const extra = escapeHtml((r.extra_info || '').slice(0, 500)) + ((r.extra_info || '').length > 500 ? '…' : '');
        return '<tr>' +
          '<td>' + (name || '—') + '</td>' +
          '<td class="type' + (!typ ? ' empty' : '') + '">' + (typ || '—') + '</td>' +
          '<td class="loc' + (!loc ? ' empty' : '') + '">' + (loc || '—') + '</td>' +
          '<td class="web">' + webCell + '</td>' +
          '<td class="note">' + (extra || '—') + '</td>' +
          '<td class="note">' + (note || '—') + '</td>' +
          '</tr>';
      }).join('');
      countEl.textContent = rows.length + ' מתוך ' + data.length;
    }

    function escapeHtml(s) {
      const div = document.createElement('div');
      div.textContent = s;
      return div.innerHTML;
    }

    function escapeAttr(s) {
      return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
    }

    function filterRows() {
      const q = (searchEl.value || '').trim().toLowerCase();
      const typeVal = typeFilter.value;
      const rows = data.filter(r => {
        const rt = (r.restaurant_type || '').trim();
        const matchType = !typeVal ? true : (typeVal === '__no_type__' ? !rt : rt === typeVal);
        if (!matchType) return false;
        if (!q) return true;
        const haystack = [
          r.name || '',
          rt,
          r.location || '',
          r.note || '',
          String(r.extra_info ?? ''),
          String(r.website ?? '')
        ].join(' ').toLowerCase();
        return haystack.includes(q);
      });
      render(rows);
    }

    searchEl.addEventListener('input', filterRows);
    searchEl.addEventListener('keyup', filterRows);
    typeFilter.addEventListener('change', filterRows);
    filterRows();
"""

HTML_HEAD = """<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>מסעדות מומלצות</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: 'Segoe UI', Tahoma, sans-serif; margin: 0; padding: 1rem; background: #f5f5f5; }
    h1 { margin: 0 0 1rem; font-size: 1.5rem; }
    .toolbar { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; align-items: center; }
    #search { flex: 1; min-width: 200px; padding: 0.5rem 0.75rem; border: 1px solid #ccc; border-radius: 6px; font-size: 1rem; }
    #typeFilter { padding: 0.5rem 0.75rem; border: 1px solid #ccc; border-radius: 6px; font-size: 1rem; min-width: 160px; }
    .count { color: #666; font-size: 0.9rem; }
    table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
    th, td { padding: 0.6rem 0.75rem; text-align: right; border-bottom: 1px solid #eee; vertical-align: top; }
    th { background: #2c3e50; color: #fff; font-weight: 600; }
    tr:hover { background: #f8f9fa; }
    .note { max-width: 380px; font-size: 0.9rem; color: #444; white-space: pre-wrap; word-break: break-word; }
    .type { font-weight: 500; color: #2c3e50; }
    .loc { font-size: 0.95rem; color: #333; max-width: 220px; word-break: break-word; }
    .web { font-size: 0.85rem; max-width: 200px; word-break: break-all; }
    .web a { color: #1a5fb4; }
    .empty { color: #999; }
    .hint { color: #666; font-size: 0.85rem; margin-bottom: 1rem; }
  </style>
</head>
<body>
  <h1>מסעדות מומלצות (מקומי)</h1>
  <p class="hint">הנתונים מוטמעים בקובץ — אפשר לפתוח ישירות מהדיסק (כמו <code>view_recommendations.html</code>). לעדכון הקובץ אחרי שינוי JSON: <code>python scripts/build_view_restaurants.py</code></p>
  <div class="toolbar">
    <input type="text" id="search" placeholder="חיפוש בשם, סוג, מיקום, הערה או מידע נוסף..." aria-label="חיפוש">
    <select id="typeFilter">
      <option value="">כל הסוגים</option>
    </select>
    <span class="count" id="count"></span>
  </div>
  <div style="overflow-x: auto;">
    <table>
      <thead>
        <tr>
          <th>שם</th>
          <th>סוג</th>
          <th>מיקום</th>
          <th>אתר</th>
          <th>הערה</th>
          <th>מידע נוסף</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
  <script>
"""

HTML_TAIL = """
  </script>
</body>
</html>
"""


def main():
    rows = json.loads(DATA.read_text(encoding="utf-8"))
    json_str = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    js = JS_TEMPLATE.replace("__JSON__", json_str)
    OUT.write_text(HTML_HEAD + js + HTML_TAIL, encoding="utf-8")
    print(f"Wrote {OUT} ({len(rows)} restaurants)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

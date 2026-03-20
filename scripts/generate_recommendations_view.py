#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a standalone HTML file to view entries.json (recommended contacts)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "data" / "entries.json"
OUT_PATH = ROOT / "view_recommendations.html"


def main():
    if not JSON_PATH.exists():
        print(f"Missing {JSON_PATH}. Run whatsapp_to_recommendations.py first.")
        return 1
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Escape for embedding in HTML/JS
    data_js = json.dumps(data, ensure_ascii=False)
    data_js_escaped = data_js.replace("</script>", "<\\/script>")

    html = """<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>אנשי קשר מומלצים</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: 'Segoe UI', Tahoma, sans-serif; margin: 0; padding: 1rem; background: #f5f5f5; }
    h1 { margin: 0 0 1rem; font-size: 1.5rem; }
    .toolbar { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; align-items: center; }
    #search { flex: 1; min-width: 200px; padding: 0.5rem 0.75rem; border: 1px solid #ccc; border-radius: 6px; font-size: 1rem; }
    #fieldFilter { padding: 0.5rem 0.75rem; border: 1px solid #ccc; border-radius: 6px; font-size: 1rem; min-width: 140px; }
    .count { color: #666; font-size: 0.9rem; }
    table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
    th, td { padding: 0.6rem 0.75rem; text-align: right; border-bottom: 1px solid #eee; }
    th { background: #2c3e50; color: #fff; font-weight: 600; }
    tr:hover { background: #f8f9fa; }
    .phone a { color: #2980b9; text-decoration: none; }
    .phone a:hover { text-decoration: underline; }
    .moshav { background: #d4edda; color: #155724; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.85rem; }
    .note { max-width: 320px; font-size: 0.9rem; color: #444; white-space: pre-wrap; word-break: break-word; }
    .field { font-weight: 500; color: #2c3e50; }
    .empty { color: #999; }
  </style>
</head>
<body>
  <h1>אנשי קשר מומלצים (וואטסאפ)</h1>
  <div class="toolbar">
    <input type="text" id="search" placeholder="חיפוש בשם, טלפון, תחום, מידע נוסף או הערה..." aria-label="חיפוש">
    <select id="fieldFilter">
      <option value="">כל התחומים</option>
    </select>
    <span class="count" id="count"></span>
  </div>
  <div style="overflow-x: auto;">
    <table>
      <thead>
        <tr>
          <th>שם</th>
          <th>טלפון</th>
          <th>תחום</th>
          <th>מידע נוסף</th>
          <th>מהמושב</th>
          <th>הערה</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
  <script>
    const data = """ + data_js_escaped + """;
    const tbody = document.getElementById('tbody');
    const searchEl = document.getElementById('search');
    const fieldFilter = document.getElementById('fieldFilter');
    const countEl = document.getElementById('count');

    const fields = [...new Set(data.map(r => r.field || '').filter(Boolean))].sort();
    const noFieldOpt = document.createElement('option');
    noFieldOpt.value = '__no_field__';
    noFieldOpt.textContent = 'ללא תחום';
    fieldFilter.appendChild(noFieldOpt);
    fields.forEach(f => {
      const opt = document.createElement('option');
      opt.value = f;
      opt.textContent = f;
      fieldFilter.appendChild(opt);
    });

    function render(rows) {
      tbody.innerHTML = rows.map(r => {
        const phone = (r.phone || '').replace(/\\D/g, '');
        const tel = phone ? 'tel:+972' + (phone.startsWith('0') ? phone.slice(1) : phone) : '';
        const name = escapeHtml(r.name || '');
        const field = escapeHtml(r.field || '');
        const extra = escapeHtml(r['extra_info'] || '');
        const note = escapeHtml((r.note || '').slice(0, 400)) + ((r.note || '').length > 400 ? '…' : '');
        const moshav = r.from_moshav ? '<span class="moshav">מהמושב</span>' : '';
        return `<tr>
          <td>${name}</td>
          <td class="phone">${tel ? `<a href="${tel}">${escapeHtml(r.phone)}</a>` : escapeHtml(r.phone)}</td>
          <td class="field ${!r.field ? 'empty' : ''}">${field || '—'}</td>
          <td class="field ${!r['extra_info'] ? 'empty' : ''}">${extra || '—'}</td>
          <td>${moshav}</td>
          <td class="note">${note || '—'}</td>
        </tr>`;
      }).join('');
      countEl.textContent = rows.length + ' מתוך ' + data.length;
    }

    function escapeHtml(s) {
      const div = document.createElement('div');
      div.textContent = s;
      return div.innerHTML;
    }

    function filterRows() {
      const q = (searchEl.value || '').trim().toLowerCase();
      const fieldVal = fieldFilter.value;
      const rows = data.filter(r => {
        const matchField = !fieldVal ? true : (fieldVal === '__no_field__' ? !(r.field && r.field.trim()) : (r.field || '') === fieldVal);
        if (!matchField) return false;
        if (!q) return true;
        const haystack = [
          r.name || '',
          r.phone || '',
          r.field || '',
          String(r['extra_info'] ?? ''),
          r.note || ''
        ].join(' ').toLowerCase();
        return haystack.includes(q);
      });
      render(rows);
    }

    searchEl.addEventListener('input', filterRows);
    searchEl.addEventListener('keyup', filterRows);
    fieldFilter.addEventListener('change', filterRows);
    filterRows();
  </script>
</body>
</html>
"""
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {OUT_PATH} ({len(data)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

/* חיפוש חי: כל הקשה בשדה החיפוש מעדכנת את הרשימה במקום, בלי טעינת עמוד. */
(function () {
  var form = document.querySelector('.search');
  var input = form && form.querySelector('input[name="q"]');
  var results = document.getElementById('results');
  if (!form || !input || !results) return;

  var timer = null;
  var lastRequest = 0;

  function searchUrl() {
    // שומר על פרמטרים קיימים (כמו סינון תחום) ומחליף רק את החיפוש
    var params = new URLSearchParams(location.search);
    var value = input.value.trim();
    if (value) params.set('q', value);
    else params.delete('q');
    var query = params.toString();
    return '/' + (query ? '?' + query : '');
  }

  function update() {
    var url = searchUrl();
    var mine = ++lastRequest;
    fetch(url, { headers: { 'Accept': 'text/html' } })
      .then(function (res) {
        if (!res.ok) throw new Error('search failed');
        return res.text();
      })
      .then(function (html) {
        if (mine !== lastRequest) return;
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var fresh = doc.getElementById('results');
        if (fresh) results.innerHTML = fresh.innerHTML;
        try { history.replaceState(null, '', url); } catch (error) { /* לא קריטי */ }
      })
      .catch(function () {
        /* אין רשת — התוצאות הקיימות נשארות; שליחת הטופס עדיין עובדת */
      });
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    update();
  });

  input.addEventListener('input', function () {
    clearTimeout(timer);
    timer = setTimeout(update, 200);
  });
})();

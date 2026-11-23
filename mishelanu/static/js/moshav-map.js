/* מפת המושב: סמן לכל בעל מקצוע שסומן על המפה, עם קישור לעמוד שלו. */
(function () {
  var el = document.getElementById('moshavMap');
  if (!el) return;
  if (typeof L === 'undefined') {
    el.textContent = 'המפה לא נטענה — נדרש חיבור לאינטרנט.';
    return;
  }

  var points = JSON.parse(el.getAttribute('data-points') || '[]');
  var focusId = el.getAttribute('data-focus');
  var uploads = el.getAttribute('data-uploads') || '';

  var map = L.map(el);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  }).addTo(map);

  var markers = {};
  points.forEach(function (point) {
    var box = document.createElement('div');
    var link = document.createElement('a');
    link.href = point.url;
    link.textContent = point.name;
    box.appendChild(link);
    if (point.field) {
      var field = document.createElement('div');
      field.className = 'pop-field';
      field.textContent = point.field;
      box.appendChild(field);
    }
    if (point.thumb) {
      var img = document.createElement('img');
      img.className = 'pop-thumb';
      img.src = uploads + point.thumb;
      img.alt = '';
      box.appendChild(img);
    }
    markers[point.id] = L.marker([point.lat, point.lng]).addTo(map).bindPopup(box);
  });

  function applyView() {
    if (focusId && markers[focusId]) {
      map.setView(markers[focusId].getLatLng(), 17);
      markers[focusId].openPopup();
    } else if (points.length) {
      var bounds = L.latLngBounds(points.map(function (point) { return [point.lat, point.lng]; }));
      map.fitBounds(bounds, { maxZoom: 16, padding: [30, 30] });
    } else {
      map.setView(
        [parseFloat(el.getAttribute('data-home-lat')), parseFloat(el.getAttribute('data-home-lng'))],
        15
      );
    }
  }

  // המפה נבנית לפני שהדפדפן מסיים לסדר את הגדלים, ואז היא נשארת צרה.
  // מודדים מחדש אחרי התייצבות הדף, ורק אז קובעים את התצוגה; וכך גם בכל שינוי גודל.
  requestAnimationFrame(function () {
    setTimeout(function () {
      map.invalidateSize();
      applyView();
    }, 80);
  });
  window.addEventListener('resize', function () { map.invalidateSize(); });
})();

/* בחירת מיקום בטופס: לחיצה על המפה (או גרירת הסמן) שומרת קואורדינטות בשדות המוסתרים. */
(function () {
  var el = document.getElementById('picker');
  var latInput = document.getElementById('lat');
  var lngInput = document.getElementById('lng');
  if (!el || !latInput || !lngInput || typeof L === 'undefined') return;

  var hasStart = latInput.value && lngInput.value;
  var start = hasStart
    ? [parseFloat(latInput.value), parseFloat(lngInput.value)]
    : [parseFloat(el.getAttribute('data-home-lat')), parseFloat(el.getAttribute('data-home-lng'))];

  var map = L.map(el).setView(start, hasStart ? 17 : 15);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  }).addTo(map);

  var marker = null;

  function place(latlng) {
    if (!marker) {
      marker = L.marker(latlng, { draggable: true }).addTo(map);
      marker.on('dragend', function () { place(marker.getLatLng()); });
    } else {
      marker.setLatLng(latlng);
    }
    latInput.value = latlng.lat.toFixed(6);
    lngInput.value = latlng.lng.toFixed(6);
  }

  function clear() {
    if (marker) {
      map.removeLayer(marker);
      marker = null;
    }
    latInput.value = '';
    lngInput.value = '';
  }

  if (hasStart) place(start);
  map.on('click', function (event) { place(event.latlng); });

  var clearButton = document.getElementById('clearLocation');
  if (clearButton) clearButton.addEventListener('click', clear);
})();

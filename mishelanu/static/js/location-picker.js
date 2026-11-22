/* בחירת מיקום בטופס.
   לחיצה על המפה (או גרירת הסמן) שומרת קואורדינטות בשדות המוסתרים.
   כשנכתבת כתובת — המפה עוברת אוטומטית למקום שנמצא לפיה ב-OpenStreetMap, ואפשר לתקן בלחיצה. */
(function () {
  var el = document.getElementById('picker');
  var latInput = document.getElementById('lat');
  var lngInput = document.getElementById('lng');
  if (!el || !latInput || !lngInput || typeof L === 'undefined') return;

  var status = document.getElementById('locationStatus');
  var form = el.closest('form');
  var addressInput = document.querySelector('input[name="address"]');
  var lookup = window.AddressLookup;
  var SEARCH_URL = 'https://nominatim.openstreetmap.org/search';
  var VIEWBOX = '34.8912207,32.2140591,34.9166188,32.1991667'; // גבולות המושב: החיפוש לא יוצא מהם
  var cache = {};
  var runId = 0;          // מזהה החיפוש הנוכחי; תשובות של חיפושים ישנים נזרקות
  var pending = null;     // החיפוש שעוד לא הסתיים — הטופס ממתין לו בשליחה
  var lastAddress = null;
  var nextRequestAt = 0;  // שירות החיפוש מבקש לא יותר מבקשה אחת בשנייה
  var waiting = false;

  var hasStart = latInput.value && lngInput.value;
  var start = hasStart
    ? [parseFloat(latInput.value), parseFloat(lngInput.value)]
    : [parseFloat(el.getAttribute('data-home-lat')), parseFloat(el.getAttribute('data-home-lng'))];
  // מיקום שמור או שנבחר ביד נשאר גם כשחיפוש לפי כתובת לא מצליח
  var manualMarker = !!hasStart;

  var map = L.map(el).setView(start, hasStart ? 17 : 15);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  }).addTo(map);

  var marker = null;

  function say(text) {
    if (status) status.textContent = text || '';
  }

  function place(latlng) {
    if (!marker) {
      marker = L.marker(latlng, { draggable: true }).addTo(map);
      marker.on('dragend', function () { manual(marker.getLatLng()); });
    } else {
      marker.setLatLng(latlng);
    }
    latInput.value = latlng.lat.toFixed(6);
    lngInput.value = latlng.lng.toFixed(6);
  }

  function manual(latlng) {
    runId += 1;            // בחירה ידנית גוברת על חיפוש שעוד לא הסתיים
    pending = null;
    manualMarker = true;
    place(latlng);
    say('המיקום סומן ידנית.');
  }

  function removeMarker() {
    if (marker) {
      map.removeLayer(marker);
      marker = null;
    }
    latInput.value = '';
    lngInput.value = '';
  }

  function clear() {
    runId += 1;
    pending = null;
    manualMarker = false;
    removeMarker();
    say('');
  }

  function search(query) {
    if (cache[query]) return Promise.resolve(cache[query]);
    var wait = Math.max(0, nextRequestAt - Date.now());
    nextRequestAt = Date.now() + wait + 1100;
    var params = new URLSearchParams({
      q: query, format: 'jsonv2', limit: '1', addressdetails: '1',
      'accept-language': 'he', countrycodes: 'il', viewbox: VIEWBOX, bounded: '1'
    }).toString();
    return new Promise(function (resolve) { setTimeout(resolve, wait); })
      .then(function () { return fetch(SEARCH_URL + '?' + params); })
      .then(function (res) {
        if (!res.ok) throw new Error('lookup failed');
        return res.json();
      })
      .then(function (data) {
        cache[query] = data;
        return data;
      });
  }

  function lookupAddress(text) {
    var list = lookup ? lookup.candidates(text) : [];
    if (!list.length) return;
    var id = ++runId;
    say('מחפשים את הכתובת במפה…');

    function giveUp(message) {
      // לא להשאיר סמן אוטומטי של כתובת קודמת — הוא לא תואם לכתובת שנכתבה עכשיו
      if (!manualMarker) removeMarker();
      say(message);
    }

    var finished = new Promise(function (resolve) {
      function step(index) {
        if (id !== runId) { resolve(); return; }
        if (index >= list.length) {
          giveUp('לא נמצאה הכתובת במפה. נא לסמן את המיקום בלחיצה על המפה.');
          resolve();
          return;
        }
        search(list[index] + ', ' + lookup.TOWN)
          .then(function (data) {
            if (id !== runId) { resolve(); return; }
            if (!data.length) { step(index + 1); return; }
            var hit = data[0];
            var at = [parseFloat(hit.lat), parseFloat(hit.lon)];
            var details = hit.address || {};
            manualMarker = false;
            place({ lat: at[0], lng: at[1] });
            map.setView(at, 17);
            say(details.house_number
              ? 'המיקום סומן לפי הכתובת. אפשר לתקן בלחיצה על המפה.'
              : 'המפה עברה לרחוב ' + (details.road || 'שנמצא') + ' — המיקום משוער. כדאי להזיז את הסמן לנקודה המדויקת.');
            resolve();
          })
          .catch(function () {
            if (id !== runId) { resolve(); return; }
            giveUp('לא הצלחנו לחפש את הכתובת כרגע. נא לסמן את המיקום בלחיצה על המפה.');
            resolve();
          });
      }
      step(0);
    });

    var done = finished.then(function () {
      if (pending === done) pending = null;
    });
    pending = done;
    return done;
  }

  /* אם לוחצים על "שמירה" בזמן שהחיפוש עוד רץ — ממתינים לו (עד 5 שניות) כדי שהמיקום יישמר. */
  function waitForLookup(event) {
    if (!pending || waiting) return;
    event.preventDefault();
    waiting = true;
    var guard = new Promise(function (resolve) { setTimeout(resolve, 5000); });
    Promise.race([pending, guard]).then(function () {
      pending = null;
      waiting = false;
      if (form.requestSubmit) form.requestSubmit();
      else form.submit();
    });
  }

  function addressChanged() {
    var value = addressInput.value.trim();
    if (value === lastAddress) return;
    lastAddress = value;
    if (value) lookupAddress(value);
  }

  if (hasStart) place(start);
  map.on('click', function (event) { manual(event.latlng); });

  var clearButton = document.getElementById('clearLocation');
  if (clearButton) clearButton.addEventListener('click', clear);
  if (form) form.addEventListener('submit', waitForLookup);
  if (addressInput) {
    addressInput.addEventListener('change', addressChanged);
    // בטעינה: יש כתובת אבל אין מיקום שמור
    if (addressInput.value.trim() && !hasStart) addressChanged();
  }
})();

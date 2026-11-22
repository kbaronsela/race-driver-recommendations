/* ניקוי כתובת ובניית ניסוחים לחיפוש במפה. משמש את הדפדפן, וגם בדיקות ב-Node. */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.AddressLookup = api;
}(typeof self !== 'undefined' ? self : this, function () {
  var TOWN = 'שדה ורבורג';
  var NUMBER = /\d+[א-ת]?/;
  var NOISE = /(^|\s)(רחוב|רח|מושב|כפר|דואר|תיבה)(\s|$)/g;

  function clean(text) {
    return (text || '')
      .replace(/[׳״'"“”.,:;()\[\]-]/g, ' ')            // גרשיים, מרכאות וסימני פיסוק
      .replace(new RegExp('(^|\\s)' + TOWN + '(\\s|$)', 'g'), '$1')
      .replace(NOISE, '$1')
      .replace(/\s+/g, ' ')
      .trim();
  }

  /* ניסוחים לחיפוש, מהמדויק לרחב: הכתובת כולה, אחר כך רחוב ומספר, ולבסוף הרחוב בלבד. */
  function candidates(text) {
    var value = clean(text);
    var list = [];
    if (!value) return list;
    list.push(value);

    var words = value.split(' ');
    var numberIndex = -1;
    for (var i = 0; i < words.length; i += 1) {
      if (NUMBER.test(words[i])) { numberIndex = i; break; }
    }
    if (numberIndex > 0) {
      var street = words.slice(0, numberIndex).join(' ');
      list.push(street + ' ' + words[numberIndex]);
      list.push(street);
    } else if (numberIndex === 0 && words.length > 1) {
      var name = words.slice(1).join(' ');                  // המספר לפני שם הרחוב: "12 הזית"
      list.push(name + ' ' + words[0]);
      list.push(name);
    }

    return list.filter(function (item, index) {
      return item && list.indexOf(item) === index;
    });
  }

  return { candidates: candidates, clean: clean, TOWN: TOWN };
}));

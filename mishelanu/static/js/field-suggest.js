/* הצעות תחומים בטופס: מתחילים להקליד — ונפתחת רשימה של התחומים הקיימים באינדקס. */
(function () {
  var input = document.querySelector('input[name="field"]');
  var box = document.getElementById('fieldSuggest');
  if (!input || !box) return;

  var fields = [];
  try {
    fields = JSON.parse(input.getAttribute('data-fields') || '[]');
  } catch (error) {
    fields = [];
  }

  function matches(value) {
    var typed = (value || '').trim();
    if (!typed) return [];
    var seen = {};
    var out = [];
    fields.forEach(function (name) {
      if (name === typed || seen[name] || out.length >= 6) return;
      if (name.indexOf(typed) !== -1) {
        seen[name] = true;
        out.push(name);
      }
    });
    return out;
  }

  function hide() {
    box.hidden = true;
    box.innerHTML = '';
  }

  function render() {
    var list = matches(input.value);
    hide();
    if (!list.length) return;
    list.forEach(function (name) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'suggest-item';
      item.textContent = name;
      item.addEventListener('mousedown', function (event) {
        event.preventDefault(); // לא לגנוב את הפוקוס מהשדה לפני הלחיצה
      });
      item.addEventListener('click', function () {
        input.value = name;
        hide();
        input.focus();
      });
      box.appendChild(item);
    });
    box.hidden = false;
  }

  input.addEventListener('input', render);
  input.addEventListener('focus', render);
  input.addEventListener('blur', function () {
    setTimeout(hide, 150); // נותן ללחיצה על הצעה להספיק
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') hide();
  });
})();

/* רישום ה-Service Worker: מאפשר התקנה כאפליקציה ופתיחה ללא רשת. */
(function () {
  if (!('serviceWorker' in navigator)) return;
  var swUrl = document.body.getAttribute('data-sw');
  if (!swUrl) return;
  window.addEventListener('load', function () {
    navigator.serviceWorker.register(swUrl).catch(function () {});
  });
})();

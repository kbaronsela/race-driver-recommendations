(function () {
  if (!('serviceWorker' in navigator)) return;
  window.addEventListener('load', function () {
    navigator.serviceWorker
      .register('sw.js', { scope: './' })
      .catch(function () {
        /* HTTP ללא HTTPS, או שגיאה — האתר ימשיך בלי PWA */
      });
  });
})();

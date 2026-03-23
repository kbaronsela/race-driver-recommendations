(function () {
  var mq = window.matchMedia('(max-width: 768px)');

  function closePanel() {
    var btn = document.getElementById('site-sidebar-menu-btn');
    var panel = document.getElementById('site-sidebar-panel');
    if (!btn || !panel) return;
    btn.setAttribute('aria-expanded', 'false');
    panel.classList.remove('site-sidebar-panel-open');
  }

  function openPanel() {
    var btn = document.getElementById('site-sidebar-menu-btn');
    var panel = document.getElementById('site-sidebar-panel');
    if (!btn || !panel) return;
    btn.setAttribute('aria-expanded', 'true');
    panel.classList.add('site-sidebar-panel-open');
  }

  function togglePanel() {
    var btn = document.getElementById('site-sidebar-menu-btn');
    if (!btn) return;
    if (btn.getAttribute('aria-expanded') === 'true') closePanel();
    else openPanel();
  }

  function init() {
    var btn = document.getElementById('site-sidebar-menu-btn');
    var panel = document.getElementById('site-sidebar-panel');
    if (!btn || !panel) return;

    btn.addEventListener('click', togglePanel);

    panel.addEventListener('click', function (e) {
      if (e.target.closest('a') && mq.matches) closePanel();
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && mq.matches && btn.getAttribute('aria-expanded') === 'true') {
        closePanel();
        btn.focus();
      }
    });

    function onMq() {
      if (!mq.matches) closePanel();
    }
    if (mq.addEventListener) mq.addEventListener('change', onMq);
    else if (mq.addListener) mq.addListener(onMq);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();

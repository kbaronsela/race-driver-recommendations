(function () {
  var mq = window.matchMedia('(max-width: 768px)');

  function closePanel() {
    var btn = document.getElementById('site-sidebar-menu-btn');
    var panel = document.getElementById('site-sidebar-panel');
    if (!btn || !panel) return;
    btn.setAttribute('aria-expanded', 'false');
    panel.classList.remove('site-sidebar-panel-open');
    document.body.classList.remove('site-sidebar-menu-open');
  }

  function openPanel() {
    var btn = document.getElementById('site-sidebar-menu-btn');
    var panel = document.getElementById('site-sidebar-panel');
    if (!btn || !panel) return;
    btn.setAttribute('aria-expanded', 'true');
    panel.classList.add('site-sidebar-panel-open');
    if (mq.matches) document.body.classList.add('site-sidebar-menu-open');
  }

  function togglePanel() {
    var btn = document.getElementById('site-sidebar-menu-btn');
    if (!btn) return;
    if (btn.getAttribute('aria-expanded') === 'true') closePanel();
    else openPanel();
  }

  function ensureCloseButton(panel) {
    if (!panel || document.getElementById('site-sidebar-close-btn')) return;
    var closeBtn = document.createElement('button');
    closeBtn.id = 'site-sidebar-close-btn';
    closeBtn.type = 'button';
    closeBtn.className = 'site-sidebar-close';
    closeBtn.setAttribute('aria-label', 'סגור תפריט');
    closeBtn.innerHTML = '<span class="site-sidebar-close-icon" aria-hidden="true">×</span>';
    var header = document.createElement('div');
    header.className = 'site-sidebar-panel-header';
    header.appendChild(closeBtn);
    panel.insertBefore(header, panel.firstChild);
    closeBtn.addEventListener('click', function () {
      closePanel();
      var menuBtn = document.getElementById('site-sidebar-menu-btn');
      if (menuBtn) menuBtn.focus();
    });
  }

  function init() {
    var btn = document.getElementById('site-sidebar-menu-btn');
    var panel = document.getElementById('site-sidebar-panel');
    if (!btn || !panel) return;

    ensureCloseButton(panel);

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

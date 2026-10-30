/* SMASS 工作台脚本：侧边栏抽屉 + 工作台切换 + 表单防重复提交 */
(function () {
  'use strict';

  var body = document.body;
  var toggle = document.getElementById('ws-drawer-toggle');
  var backdrop = document.getElementById('ws-backdrop');
  var sidebar = document.getElementById('ws-sidebar');

  function closeDrawer() {
    body.classList.remove('ws-drawer-open');
    if (toggle) { toggle.setAttribute('aria-expanded', 'false'); }
  }

  if (toggle) {
    toggle.addEventListener('click', function () {
      var open = body.classList.toggle('ws-drawer-open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  if (backdrop) { backdrop.addEventListener('click', closeDrawer); }
  if (sidebar) {
    sidebar.addEventListener('click', function (event) {
      if (event.target.closest('a')) { closeDrawer(); }
    });
  }
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') { closeDrawer(); }
  });

  var switcher = document.getElementById('ws-switcher');
  var switcherToggle = document.getElementById('ws-switcher-toggle');
  if (switcher && switcherToggle) {
    switcherToggle.addEventListener('click', function (event) {
      event.stopPropagation();
      var open = switcher.classList.toggle('is-open');
      switcherToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('click', function () {
      switcher.classList.remove('is-open');
      switcherToggle.setAttribute('aria-expanded', 'false');
    });
  }

  // 提交后禁用按钮，避免重复提交；失败时由页面重新渲染恢复
  document.querySelectorAll('form[data-once]').forEach(function (form) {
    form.addEventListener('submit', function () {
      var button = form.querySelector('button[type="submit"]');
      if (button) {
        button.disabled = true;
        button.dataset.label = button.textContent;
        button.textContent = '处理中…';
      }
    });
  });
})();

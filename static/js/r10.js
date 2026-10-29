/* SMASS R10 交互脚本（U2）
 * 无框架依赖：抽屉、toast、确认弹窗、CSRF 提交、表单校验、异步加载。
 * 全部基于原生 DOM，供 Django 模板直接调用。
 */
(function () {
  'use strict';

  /* ---------- CSRF ---------- */
  function getCookie(name) {
    var match = document.cookie.match(new RegExp('(^|;\\s*)' + name + '=([^;]*)'));
    return match ? decodeURIComponent(match[2]) : '';
  }

  function csrfToken() {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : getCookie('csrftoken');
  }

  /* ---------- Toast ---------- */
  function toastHost() {
    var host = document.getElementById('sm-toast-host');
    if (!host) {
      host = document.createElement('div');
      host.id = 'sm-toast-host';
      host.className = 'sm-toast-host';
      host.setAttribute('role', 'status');
      host.setAttribute('aria-live', 'polite');
      document.body.appendChild(host);
    }
    return host;
  }

  function toast(message, kind) {
    var node = document.createElement('div');
    node.className = 'sm-toast' + (kind ? ' is-' + kind : '');
    node.textContent = message;
    toastHost().appendChild(node);
    setTimeout(function () {
      node.remove();
    }, 4000);
  }

  /* ---------- 抽屉 ---------- */
  var lastFocused = null;

  function drawer() {
    return document.getElementById('sm-sidebar');
  }

  function backdrop() {
    return document.getElementById('sm-backdrop');
  }

  function focusables(root) {
    return Array.prototype.slice.call(
      root.querySelectorAll('a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])')
    ).filter(function (el) { return el.offsetParent !== null; });
  }

  function openDrawer() {
    var side = drawer();
    var back = backdrop();
    if (!side) return;
    lastFocused = document.activeElement;
    side.classList.add('is-open');
    if (back) back.classList.add('is-open');
    side.setAttribute('aria-hidden', 'false');
    var toggle = document.getElementById('sm-drawer-toggle');
    if (toggle) toggle.setAttribute('aria-expanded', 'true');
    var items = focusables(side);
    if (items.length) items[0].focus();
  }

  function closeDrawer() {
    var side = drawer();
    var back = backdrop();
    if (!side) return;
    side.classList.remove('is-open');
    if (back) back.classList.remove('is-open');
    side.setAttribute('aria-hidden', 'true');
    var toggle = document.getElementById('sm-drawer-toggle');
    if (toggle) toggle.setAttribute('aria-expanded', 'false');
    if (lastFocused && typeof lastFocused.focus === 'function') lastFocused.focus();
    lastFocused = null;
  }

  function drawerOpen() {
    var side = drawer();
    return !!(side && side.classList.contains('is-open'));
  }

  /* ---------- 确认弹窗 ---------- */
  function confirmDialog(message, options) {
    options = options || {};
    return new Promise(function (resolve) {
      var overlay = document.createElement('div');
      overlay.className = 'sm-backdrop is-open';
      overlay.style.zIndex = '60';
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');

      var box = document.createElement('div');
      box.style.cssText = 'position:fixed;left:50%;top:30%;transform:translate(-50%,-50%);' +
        'background:#fff;border-radius:10px;padding:20px;max-width:420px;width:calc(100vw - 40px);' +
        'box-shadow:0 12px 32px rgba(0,0,0,.22);z-index:61;';

      var title = document.createElement('h3');
      title.style.cssText = 'margin:0 0 8px;font-size:16px;';
      title.textContent = options.title || '确认操作';

      var text = document.createElement('p');
      text.style.cssText = 'margin:0 0 16px;color:#4b5563;font-size:13.5px;line-height:1.6;';
      text.id = 'sm-confirm-message';
      text.textContent = message;

      var actions = document.createElement('div');
      actions.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;';

      var cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'sm-btn';
      cancel.textContent = options.cancelText || '取消';

      var ok = document.createElement('button');
      ok.type = 'button';
      ok.className = 'sm-btn ' + (options.danger ? 'is-danger' : 'is-primary');
      ok.textContent = options.okText || '确认';

      actions.appendChild(cancel);
      actions.appendChild(ok);
      box.appendChild(title);
      box.appendChild(text);
      box.appendChild(actions);
      overlay.appendChild(box);
      document.body.appendChild(overlay);

      ok.focus();

      function finish(result) {
        overlay.remove();
        resolve(result);
      }

      ok.addEventListener('click', function () { finish(true); });
      cancel.addEventListener('click', function () { finish(false); });
      overlay.addEventListener('click', function (event) {
        if (event.target === overlay) finish(false);
      });
      overlay.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') { event.preventDefault(); finish(false); }
        if (event.key === 'Tab') {
          var items = [cancel, ok];
          var index = items.indexOf(document.activeElement);
          event.preventDefault();
          items[(index + (event.shiftKey ? -1 : 1) + items.length) % items.length].focus();
        }
      });
    });
  }

  /* ---------- 异步请求 ---------- */
  function requestJSON(url, options) {
    options = options || {};
    var headers = {
      'X-Requested-With': 'XMLHttpRequest',
      'Accept': 'application/json'
    };
    if (options.body) headers['Content-Type'] = 'application/json';
    var token = csrfToken();
    if (token) headers['X-CSRFToken'] = token;
    if (options.headers) {
      Object.keys(options.headers).forEach(function (k) { headers[k] = options.headers[k]; });
    }

    return fetch(url, {
      method: options.method || 'GET',
      headers: headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
      credentials: 'same-origin'
    }).then(function (response) {
      return response.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        return { ok: response.ok, status: response.status, data: data, raw: text };
      });
    });
  }

  /* ---------- 表单：提交时禁用按钮 ---------- */
  function bindSubmitGuards(root) {
    root = root || document;
    var forms = root.querySelectorAll('form[data-sm-form]');
    Array.prototype.forEach.call(forms, function (form) {
      if (form.dataset.smBound === '1') return;
      form.dataset.smBound = '1';
      form.addEventListener('submit', function () {
        var buttons = form.querySelectorAll('button[type="submit"]');
        Array.prototype.forEach.call(buttons, function (btn) {
          btn.disabled = true;
          btn.dataset.smOriginal = btn.textContent;
          btn.innerHTML = '<span class="sm-spinner"></span> 处理中…';
        });
      });
    });
  }

  /* ---------- 危险操作确认 ---------- */
  function bindConfirmations(root) {
    root = root || document;
    var nodes = root.querySelectorAll('[data-sm-confirm]');
    Array.prototype.forEach.call(nodes, function (node) {
      if (node.dataset.smConfirmBound === '1') return;
      node.dataset.smConfirmBound = '1';
      node.addEventListener('click', function (event) {
        if (node.dataset.smConfirmed === '1') return;
        event.preventDefault();
        confirmDialog(node.dataset.smConfirm, {
          danger: node.dataset.smDanger === '1',
          okText: node.dataset.smOkText || '确认'
        }).then(function (ok) {
          if (!ok) return;
          node.dataset.smConfirmed = '1';
          if (node.tagName === 'A' && node.getAttribute('href')) {
            window.location.href = node.getAttribute('href');
          } else if (node.form) {
            node.form.submit();
          } else {
            node.click();
          }
        });
      });
    });
  }

  /* ---------- 全局键盘 ---------- */
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && drawerOpen()) {
      closeDrawer();
    }
  });

  /* ---------- 初始化 ---------- */
  function init() {
    var toggle = document.getElementById('sm-drawer-toggle');
    var back = document.getElementById('sm-backdrop');
    if (toggle) toggle.addEventListener('click', openDrawer);
    if (back) back.addEventListener('click', closeDrawer);

    // 点击侧边栏链接后关闭抽屉（移动端）
    var side = drawer();
    if (side) {
      side.addEventListener('click', function (event) {
        if (event.target.closest('a') && drawerOpen()) closeDrawer();
      });
    }

    // 关闭 alert
    Array.prototype.forEach.call(document.querySelectorAll('.sm-alert-close'), function (btn) {
      btn.addEventListener('click', function () {
        var alert = btn.closest('.sm-alert');
        if (alert) alert.remove();
      });
    });

    bindSubmitGuards(document);
    bindConfirmations(document);

    // 抽屉焦点陷阱
    if (side) {
      side.addEventListener('keydown', function (event) {
        if (event.key !== 'Tab' || !drawerOpen()) return;
        var items = focusables(side);
        if (!items.length) return;
        var first = items[0], last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault(); first.focus();
        }
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /* ---------- 导出 ---------- */
  window.SM = {
    toast: toast,
    confirm: confirmDialog,
    request: requestJSON,
    csrfToken: csrfToken,
    openDrawer: openDrawer,
    closeDrawer: closeDrawer,
    bindSubmitGuards: bindSubmitGuards,
    bindConfirmations: bindConfirmations
  };
})();

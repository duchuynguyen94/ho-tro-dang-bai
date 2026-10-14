"""Ghi lại thao tác trên trình duyệt -> các bước kịch bản (ưu tiên HTML selector)."""

# JS chèn vào trang: bắt click / nhập liệu / chọn file và tính selector tốt nhất.
RECORDER_JS = r"""
(() => {
  if (window.__wpRecorderInstalled) return;
  window.__wpRecorderInstalled = true;

  function esc(v){ return window.CSS && CSS.escape ? CSS.escape(v) : v.replace(/[^\w-]/g,'\\$&'); }

  function cssPath(el){
    const parts = [];
    while (el && el.nodeType === 1 && parts.length < 6){
      let sel = el.tagName.toLowerCase();
      if (el.id){ parts.unshift('#' + esc(el.id)); break; }
      const cls = (el.className || '').toString().trim().split(/\s+/).filter(Boolean).slice(0,2);
      if (cls.length) sel += '.' + cls.map(esc).join('.');
      const parent = el.parentElement;
      if (parent){
        const same = [...parent.children].filter(c => c.tagName === el.tagName);
        if (same.length > 1) sel += ':nth-child(' + (same.indexOf(el)+1) + ')';
      }
      parts.unshift(sel);
      el = el.parentElement;
    }
    return parts.join(' > ');
  }

  function candidates(el){
    const out = [];
    if (el.id) out.push('#' + esc(el.id));
    const name = el.getAttribute('name');
    if (name) out.push(`${el.tagName.toLowerCase()}[name="${name}"]`);
    for (const a of ['data-testid','data-test','data-qa','aria-label','placeholder']){
      const v = el.getAttribute(a);
      if (v) out.push(`${el.tagName.toLowerCase()}[${a}="${v}"]`);
    }
    if (el.type) out.push(`${el.tagName.toLowerCase()}[type="${el.type}"]`);
    const txt = (el.innerText || '').trim().slice(0, 30);
    if (txt) out.push(`text="${txt}"`);
    out.push(cssPath(el));
    return [...new Set(out.filter(Boolean))];
  }

  function send(step){
    try { window.__wpRecordStep(step); } catch(e){}
  }

  document.addEventListener('click', (e) => {
    const el = e.target.closest('a,button,input,label,select,textarea');
    if (!el) return;
    const c = candidates(el);
    const isLink = el.tagName === 'A';
    send({ action: isLink ? 'open' : 'click', selector: c[0], selectors: c,
           note: (el.innerText || el.getAttribute('aria-label') || el.tagName).trim().slice(0,60),
           source: 'recorded' });
  }, true);

  document.addEventListener('change', (e) => {
    const el = e.target;
    if (!el) return;
    const c = candidates(el);
    if (el.type === 'file'){
      send({ action: 'upload', selector: c[0], selectors: c, note: 'Upload file', source: 'recorded' });
    } else if (el.tagName === 'SELECT'){
      send({ action: 'select', selector: c[0], selectors: c, value: el.value, note: 'Chọn giá trị', source: 'recorded' });
    }
  }, true);

  document.addEventListener('blur', (e) => {
    const el = e.target;
    if (!el || !(el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return;
    if (el.type === 'file' || el.type === 'hidden') return;
    const c = candidates(el);
    send({ action: 'type', selector: c[0], selectors: c, value: el.value,
           note: (el.placeholder || el.name || 'Nhập dữ liệu').slice(0,60), source: 'recorded' });
  }, true);
})();
"""


def install(page) -> None:
    """Cài bộ ghi vào trang hiện tại."""
    page.evaluate(RECORDER_JS)

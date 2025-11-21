(() => {
  try {
    const BASE = (window.APP_BASE || '').replace(/\/$/, '') || '';

    const routes = [
      { href: BASE + '/', label: '🏠 Chat' },
      { href: BASE + '/overview', label: '📋 Overview' },
      { href: BASE + '/budget-health', label: '📊 Budget Health' },
      { href: BASE + '/transactions', label: '🧾 Transactions' },
      { href: BASE + '/commitments', label: '📑 Commitments' },
      { href: BASE + '/subscriptions-report', label: '🔄 Subscriptions' },
      { href: BASE + '/subscriptions-rest-of-month-report', label: '📅 Subs (Rest of Month)' },
      { href: BASE + '/uploads', label: '🗂️ Uploads' },
      { href: BASE + '/unmatched', label: '❓ Unmatched' },
      { href: BASE + '/admin', label: '⚙️ Admin' },
    ];

    // Insert back-to-chat link if missing on page, don't activate 'back to chat' on main chat page
    /*if (!document.querySelector('a.back') && window.location.href.split('/').length == 5) {
      const back = document.createElement('a');
      back.href = BASE + '/';
      back.textContent = '← Back to Chat';
      back.className = 'back';
      back.style.cssText = 'display:inline-block;padding:8px 12px;border-radius:6px;background:#3b82f6;color:#06142b;text-decoration:none;font-weight:600;position:fixed;right:12px;top:12px;z-index:1000';
      document.body.appendChild(back);
    }*/

    // Sidebar container
    const sb = document.createElement('nav');
    sb.setAttribute('aria-label', 'Main Navigation');
    sb.style.cssText = [
      'position:fixed',
      'top:0',
      'left:0',
      'bottom:0',
      'width:220px',
      'background:#0b1222',
      'border-right:1px solid #1f2937',
      'padding:14px 10px',
      'box-sizing:border-box',
      'z-index:999',
      'overflow:auto',
      'display:none',
    ].join(';');

    const title = document.createElement('div');
    title.textContent = 'Budget Buddy';
    title.style.cssText = 'font-weight:700;color:#e5e7eb;margin:6px 6px 10px 6px;';
    sb.appendChild(title);

    routes.forEach(r => {
      const a = document.createElement('a');
      a.href = r.href; a.textContent = r.label;
      a.style.cssText = 'display:block;color:#e5e7eb;text-decoration:none;padding:8px 10px;border-radius:6px;margin:2px 4px;';
      a.onmouseenter = () => a.style.background = '#111827';
      a.onmouseleave = () => a.style.background = 'transparent';
      sb.appendChild(a);
    });

    document.body.appendChild(sb);

    // Toggle button
    const btn = document.createElement('button');
    btn.textContent = '☰';
    btn.title = 'Menu';
    btn.style.cssText = 'position:fixed;left:12px;top:12px;z-index:1001;background:#2563eb;color:#fff;border:none;border-radius:6px;padding:8px 10px;cursor:pointer';
    btn.addEventListener('click', () => {
      const shown = sb.style.display !== 'none';
      sb.style.display = shown ? 'none' : 'block';
    });
    document.body.appendChild(btn);

    /*// Auto-show on large screens
    function syncSidebar() {
      if (window.innerWidth >= 1100) {
        sb.style.display = 'block';
      } else {
        sb.style.display = 'none';
      }
    }
    window.addEventListener('resize', syncSidebar);
    syncSidebar();*/

    // Add left margin to main container when sidebar is visible
    function adjustContentMargin() {
      const containers = document.querySelectorAll('.container');
      containers.forEach(el => {
        if (sb.style.display === 'block' && window.innerWidth >= 1100) {
          el.style.marginLeft = '240px';
        } else {
          el.style.marginLeft = '';
        }
      });
    }
    const ro = new ResizeObserver(adjustContentMargin);
    document.querySelectorAll('.container').forEach(el => ro.observe(el));
    window.addEventListener('resize', adjustContentMargin);
    adjustContentMargin();
  } catch (e) {
    // noop
  }
})();


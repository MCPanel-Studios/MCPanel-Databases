/* ═══════════════════════════════════════════════════════════════════════════
   MCPanel-Databases: the Databases page - the MySQL / MariaDB servers on the
   machine running the backend (this computer for MCPanel, the host for the
   WebUI): saved accounts, their databases, tables and rows.

   Runs inside MCPanel / MCPanel-WebUI as an addon script (`addon` and
   `MCPanelAddons` in scope). The table grid is the panel's own
   (window.MCPanelTableEditor, also used by its built-in SQLite editor); this
   file supplies the page around it and reads/writes through
   `mcpanel api databases …`.
   ═══════════════════════════════════════════════════════════════════════════ */

const A = window.MCPanelAddons;
const TE = window.MCPanelTableEditor;
const esc = s => A.escapeHtml(String(s ?? ''));
const cli = args => A.cli(['databases', ...args]);

const ICON_PAGE = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/></svg>';
const ICON_X = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>';
const ICON_REFRESH = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-2.64-6.36L21 8"/><path d="M21 3v5h-5"/></svg>';
const ICON_PLUS16 = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>';

// One MySQL database as a table-editor source.
function mysqlSource(conn, db) {
  const run = args => cli([...args, '-conn', conn, '-db', db]);
  return {
    key: `mysql:${conn}:${db}`,
    rows: (table, offset, limit) => run(['rows', '-table', table, '-offset', String(offset), '-limit', String(limit)]),
    update: (table, key, set) => run(['update', '-table', table, '-key', JSON.stringify(key), '-set', JSON.stringify(set)]),
    insert: (table, values) => run(['insert', '-table', table, '-values', JSON.stringify(values)]),
    delete: (table, key) => run(['delete', '-table', table, '-key', JSON.stringify(key)]),
  };
}

// ─── dialogs (added once, before the panel's confirm dialog so that one
//     stays on top when a delete is confirmed from inside them) ──────────────
function addDialogs() {
  const html = `
<div class="modal-overlay hidden" id="modal-dbx-database">
  <div class="modal small">
    <div class="modal-header">
      <div style="min-width:0"><h2 id="dbx-db-title">New Database</h2><div class="dbx-sub" id="dbx-db-sub"></div></div>
      <button class="modal-close" data-close="modal-dbx-database">${ICON_X}</button>
    </div>
    <div class="modal-body">
      <div class="form-grid">
        <div class="form-group full">
          <label>Name</label>
          <input type="text" id="dbx-db-name" class="input" placeholder="e.g. economy" autocomplete="off" spellcheck="false">
        </div>
        <div class="form-group">
          <label>Character set</label>
          <select id="dbx-db-charset" class="input">
            <option value="">Server default</option>
            <option value="utf8mb4">utf8mb4</option>
            <option value="utf8mb3">utf8mb3</option>
            <option value="latin1">latin1</option>
            <option value="ascii">ascii</option>
            <option value="binary">binary</option>
          </select>
        </div>
        <div class="form-group">
          <label>Collation <span class="label-hint">(optional)</span></label>
          <input type="text" id="dbx-db-collation" class="input" placeholder="charset default" autocomplete="off" spellcheck="false">
        </div>
      </div>
      <div class="field-hint" style="margin-top:8px">The character set only applies to tables created afterwards.</div>
      <div class="field-hint hidden" id="dbx-db-rename-hint" style="margin-top:4px">Renaming moves every table to a new database. Privileges granted on the old name don't carry over, and plugins must be pointed at the new name.</div>
    </div>
    <div class="modal-footer">
      <button class="btn-danger hidden" id="dbx-db-delete" style="margin-right:auto">Delete</button>
      <button class="btn-ghost" data-close="modal-dbx-database">Cancel</button>
      <button class="btn-primary" id="dbx-db-save">Create</button>
    </div>
  </div>
</div>
<div class="modal-overlay hidden" id="modal-dbx-account">
  <div class="modal small">
    <div class="modal-header">
      <h2 id="dbx-acc-title">Add Account</h2>
      <button class="modal-close" data-close="modal-dbx-account">${ICON_X}</button>
    </div>
    <div class="modal-body">
      <div class="info-box dbx-status" id="dbx-acc-status"></div>
      <div class="form-grid" style="margin-top:12px">
        <div class="form-group full">
          <label>Name <span class="label-hint">(optional)</span></label>
          <input type="text" id="dbx-acc-name" class="input" placeholder="e.g. Plugins, Network DB" autocomplete="off">
        </div>
        <div class="form-group"><label>Host</label><input type="text" id="dbx-acc-host" class="input" placeholder="127.0.0.1"></div>
        <div class="form-group"><label>Port</label><input type="number" id="dbx-acc-port" class="input" min="1" max="65535" placeholder="3306"></div>
        <div class="form-group"><label>User</label><input type="text" id="dbx-acc-user" class="input" autocomplete="off"></div>
        <div class="form-group"><label>Password</label><input type="password" id="dbx-acc-password" class="input" autocomplete="new-password"></div>
      </div>
      <div class="field-hint" style="margin-top:8px">MySQL / MariaDB login. Stored for this install only, in a file only your user can read.</div>
    </div>
    <div class="modal-footer">
      <button class="btn-ghost hidden" id="dbx-acc-remove" style="margin-right:auto">Remove</button>
      <button class="btn-ghost" data-close="modal-dbx-account">Cancel</button>
      <button class="btn-primary" id="dbx-acc-save">Save &amp; Connect</button>
    </div>
  </div>
</div>`;
  const box = document.createElement('div');
  box.innerHTML = html;
  const confirmEl = document.getElementById('modal-confirm');
  for (const modal of [...box.children]) {
    if (confirmEl) confirmEl.before(modal); else document.body.appendChild(modal);
  }
  document.querySelectorAll('[data-close]').forEach(b => {
    if (b.dataset.close.startsWith('modal-dbx-')) b.addEventListener('click', () => closeModal(b.dataset.close));
  });
  document.getElementById('dbx-db-save').addEventListener('click', saveDatabase);
  document.getElementById('dbx-db-delete').addEventListener('click', () => editingDb?.name && deleteDatabase(editingDb.conn, editingDb.name));
  document.getElementById('dbx-db-name').addEventListener('keydown', e => { if (e.key === 'Enter') saveDatabase(); });
  document.getElementById('dbx-acc-save').addEventListener('click', saveAccount);
  document.getElementById('dbx-acc-remove').addEventListener('click', removeAccount);
}

// ═══ Page state ══════════════════════════════════════════════════════════════
// Each account is its own group: databases are keyed by "<account id>/<db>"
// since two accounts can see the same database.
const page = {
  list: null,          // `databases list` result
  tables: {},          // "<conn>/<db>" → { loading, error, tables }
  open: new Set(),     // expanded "<conn>/<db>"
  sel: null,           // { conn, db } of the table in the editor
  editor: null,
  tree: null,
};
const dbKey = (conn, name) => `${conn}/${name}`;
const splitKey = k => { const i = k.indexOf('/'); return [k.slice(0, i), k.slice(i + 1)]; };
const connById = id => page.list?.mysql.connections.find(c => c.id === id);
const connLabel = c => {
  const who = `${c.user || '?'}@${c.host}:${c.port}`;
  return c.name ? `${c.name} (${who})` : who;
};

// Collapsed accounts, remembered per browser (a convenience - it's fine if
// storage is unavailable).
const COLLAPSED_KEY = 'mcpanel.db.collapsed';
const collapsed = (() => {
  try { return new Set(JSON.parse(localStorage.getItem(COLLAPSED_KEY) || '[]')); } catch { return new Set(); }
})();
function toggleCollapsed(id) {
  if (!collapsed.delete(id)) collapsed.add(id);
  try { localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...collapsed])); } catch { /* not persisted */ }
  renderTree();
}

async function refreshPage() {
  if (!page.list) page.tree.innerHTML = '<div class="db-muted">Looking for databases on this machine…</div>';
  const r = await cli(['list']);
  if (r.error) { page.tree.innerHTML = `<div class="db-muted error">${esc(r.error)}</div>`; return; }
  page.list = r;
  const alive = new Set(r.mysql.connections.flatMap(c => (c.databases || []).map(n => dbKey(c.id, n))));
  for (const k of [...page.open]) if (!alive.has(k)) page.open.delete(k);
  if (page.sel && !alive.has(dbKey(page.sel.conn, page.sel.db))) { page.editor.clear(); page.sel = null; }
  page.tables = {};
  renderTree();
  for (const k of page.open) loadTables(...splitKey(k));
}

// quiet: keep showing the current list while it refreshes (after a write),
// so the sidebar doesn't flicker under the user's cursor.
async function loadTables(conn, name, { quiet = false } = {}) {
  const k = dbKey(conn, name);
  if (!(quiet && page.tables[k]?.tables)) {
    page.tables[k] = { loading: true };
    renderTree();
  }
  const r = await cli(['tables', '-conn', conn, '-db', name]);
  page.tables[k] = r.error ? { error: r.error } : { tables: r.tables };
  renderTree();
}

// ─── tree ────────────────────────────────────────────────────────────────────
function connHtml(c) {
  const I = TE.icons;
  const edit = c.auto ? '<span class="db-tag">auto login</span>'
    : `<button class="db-icon-btn" data-act="edit-conn" data-conn="${esc(c.id)}" title="Edit account">${I.edit}</button>`;
  const open = !collapsed.has(c.id);
  let html = `<div class="db-group-title db-conn${open ? ' open' : ''}" data-act="toggle-conn" data-conn="${esc(c.id)}"
    role="button" tabindex="0" aria-expanded="${open}">
    ${I.chevron}${I.server}<span class="db-item-name">${esc(connLabel(c))}</span>${edit}</div>`;
  if (!open) return html;
  if (c.error) return html + `<div class="db-muted error">${esc(c.error)}</div>`;
  if (c.databases === null) return html + `<div class="db-muted">No server answers on ${esc(c.host)}:${esc(c.port)}.</div>`;
  html += `<button class="db-item db-add" data-act="new-db" data-conn="${esc(c.id)}">
    <span class="db-add-icon">${I.plus}</span><span class="db-item-name">New database</span></button>`;
  if (!c.databases.length) return html + '<div class="db-muted">No databases.</div>';
  for (const name of c.databases) {
    const k = dbKey(c.id, name);
    const isOpen = page.open.has(k);
    const data = `data-conn="${esc(c.id)}" data-db="${esc(name)}"`;
    html += `<div class="db-row" data-dbrow ${data}>
      <button class="db-item${isOpen ? ' open' : ''}" data-act="toggle" ${data}>
        ${I.chevron}${I.db}<span class="db-item-name">${esc(name)}</span></button>
      <button class="db-icon-btn db-row-edit" data-act="edit-db" ${data} title="Edit database">${I.edit}</button>
    </div>`;
    if (!isOpen) continue;
    const t = page.tables[k];
    if (!t || t.loading) html += '<div class="db-muted db-indent">Loading tables…</div>';
    else if (t.error) html += `<div class="db-muted db-indent error">${esc(t.error)}</div>`;
    else if (!t.tables.length) html += '<div class="db-muted db-indent">No tables</div>';
    else {
      const active = page.sel && page.sel.conn === c.id && page.sel.db === name ? page.editor.ed.table : null;
      html += TE.tableListHtml(t.tables, active, `data-act="table" ${data}`);
    }
  }
  return html;
}

function mysqlTreeHtml(m) {
  if (!m.client) {
    return `<div class="db-muted">No MySQL / MariaDB client on this machine${m.listening
      ? ', although a server answers on port 3306. Install the MariaDB or MySQL client to browse it.' : '.'}</div>`;
  }
  // A divider between accounts - except between two collapsed ones, which
  // read as one compact list - and one above "Add account".
  const divider = '<div class="db-divider"></div>';
  let html = m.connections.map((c, i) => {
    const prev = m.connections[i - 1];
    return (prev && !(collapsed.has(prev.id) && collapsed.has(c.id)) ? divider : '') + connHtml(c);
  }).join('');
  if (m.connections.length) html += divider;
  if (m.needsLogin) html += '<div class="db-muted">A server is running on this machine but needs a login.</div>';
  else if (!m.connections.length) html += '<div class="db-muted">No accounts yet.</div>';
  return html + `<button class="db-item db-add" data-act="add-conn">${TE.icons.plus}<span class="db-item-name">Add account</span></button>`;
}

function renderTree() {
  const { mysql, engines } = page.list;
  let html = '<div class="db-section-title"><span>MySQL / MariaDB</span></div>' + mysqlTreeHtml(mysql);
  if (engines.length) {
    html += '<div class="db-section-title" style="margin-top:8px"><span>Also on this machine</span></div>';
    for (const e of engines) {
      html += `<div class="db-engine">${TE.icons.db}<span class="db-item-name">${esc(e.name)}</span>
        <span class="db-item-meta">${e.listening ? `port ${esc(e.port)}` : 'not running'}</span></div>`;
    }
    html += '<div class="db-muted">Browsing these isn\'t supported yet.</div>';
  }
  page.tree.innerHTML = html;
}

function onTreeClick(e) {
  const el = e.target.closest('[data-act]');
  if (!el) return;
  e.preventDefault();
  const { act, conn, db: name } = el.dataset;
  if (act === 'add-conn') openAccountModal(null);
  else if (act === 'edit-conn') openAccountModal(connById(conn));
  else if (act === 'toggle-conn') toggleCollapsed(conn);
  else if (act === 'new-db') openDatabaseModal(conn, null);
  else if (act === 'edit-db') openDatabaseModal(conn, name);
  else if (act === 'toggle') {
    const k = dbKey(conn, name);
    if (page.open.has(k)) { page.open.delete(k); renderTree(); return; }
    page.open.add(k);
    if (!page.tables[k] || page.tables[k].error) loadTables(conn, name);
    else renderTree();
  } else if (act === 'table') {
    const c = connById(conn);
    const label = page.list.mysql.connections.length > 1 && c ? `${c.name || c.user} › ${name}` : name;
    page.sel = { conn, db: name };
    page.editor.open(mysqlSource(conn, name), el.dataset.table, { label });
    renderTree();
  }
}

function onTreeKeydown(e) {
  const head = e.target.closest('[data-act="toggle-conn"]');
  if (head && e.target === head && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); toggleCollapsed(head.dataset.conn); }
}

function onTreeContextMenu(e) {
  const row = e.target.closest('[data-dbrow]');
  if (!row || typeof showContextMenu !== 'function') return;
  const { conn, db: name } = row.dataset;
  showContextMenu(e, [
    { label: 'Edit…', icon: CTX_ICON.rename, onClick: () => openDatabaseModal(conn, name) },
    'sep',
    { label: 'Delete', icon: CTX_ICON.delete, danger: true, onClick: () => deleteDatabase(conn, name) },
  ], { title: name });
}

// ─── database dialog (create / edit) ─────────────────────────────────────────
let editingDb = null;   // { conn, name, charset, collation } when editing, { conn } when creating

async function openDatabaseModal(conn, name) {
  editingDb = { conn, name };
  const c = connById(conn);
  document.getElementById('dbx-db-title').textContent = name ? 'Edit Database' : 'New Database';
  document.getElementById('dbx-db-sub').textContent = c ? connLabel(c) : '';
  document.getElementById('dbx-db-name').value = name || '';
  document.getElementById('dbx-db-charset').value = name ? '' : 'utf8mb4';
  document.getElementById('dbx-db-collation').value = '';
  document.getElementById('dbx-db-rename-hint').classList.toggle('hidden', !name);
  document.getElementById('dbx-db-delete').classList.toggle('hidden', !name);
  document.getElementById('dbx-db-save').textContent = name ? 'Save' : 'Create';
  openModal('modal-dbx-database');
  if (!name) return;
  // Current defaults, so "Save" without touching them changes nothing.
  const r = await cli(['tables', '-conn', conn, '-db', name]);
  if (r.error || editingDb?.name !== name) return;
  Object.assign(editingDb, { charset: r.charset, collation: r.collation });
  const sel = document.getElementById('dbx-db-charset');
  if (r.charset && ![...sel.options].some(o => o.value === r.charset)) sel.add(new Option(r.charset, r.charset));
  sel.value = r.charset || '';
  document.getElementById('dbx-db-collation').value = r.collation || '';
}

async function saveDatabase() {
  if (!editingDb) return;
  const { conn, name } = editingDb;
  const newName = document.getElementById('dbx-db-name').value.trim();
  const charset = document.getElementById('dbx-db-charset').value;
  const collation = document.getElementById('dbx-db-collation').value.trim();
  if (!newName) { A.toast('Enter a name', 'error'); return; }
  let args;
  if (!name) {
    args = ['create', '-conn', conn, '-name', newName];
    if (charset) args.push('-charset', charset);
    if (collation) args.push('-collation', collation);
  } else {
    args = ['alter', '-conn', conn, '-db', name];
    if (newName !== name) args.push('-rename', newName);
    if (charset && charset !== editingDb.charset) args.push('-charset', charset);
    if (collation && collation !== editingDb.collation) args.push('-collation', collation);
    if (args.length === 5) { closeModal('modal-dbx-database'); return; } // nothing changed
  }
  const btn = document.getElementById('dbx-db-save');
  btn.disabled = true;
  const r = await cli(args);
  btn.disabled = false;
  if (r.error) { A.toast(r.error, 'error'); return; }
  closeModal('modal-dbx-database');
  A.toast(r.message, 'success');
  if (r.warning) A.toast(r.warning, 'info');
  // A renamed database: follow it in the tree; the open table is gone.
  if (name && newName !== name) {
    if (page.open.delete(dbKey(conn, name))) page.open.add(dbKey(conn, newName));
    if (page.sel && page.sel.conn === conn && page.sel.db === name) { page.editor.clear(); page.sel = null; }
  } else if (!name) {
    page.open.add(dbKey(conn, newName));
  }
  refreshPage();
}

async function deleteDatabase(conn, name) {
  const r = await cli(['tables', '-conn', conn, '-db', name]);
  const n = r.error ? null : r.tables.length;
  const what = n === null ? 'all its tables' : `its ${n} table${n === 1 ? '' : 's'}`;
  const ok = await confirmDialog({
    title: 'Delete Database',
    message: `Delete the database "${name}" and ${what}?\n\nEvery plugin using it will lose its data. This can't be undone.`,
    confirmLabel: 'Delete Database',
  });
  if (!ok) return;
  const res = await cli(['drop', '-conn', conn, '-db', name]);
  if (res.error) { A.toast(res.error, 'error'); return; }
  closeModal('modal-dbx-database');
  if (page.sel && page.sel.conn === conn && page.sel.db === name) { page.editor.clear(); page.sel = null; }
  page.open.delete(dbKey(conn, name));
  A.toast(res.message, 'success');
  refreshPage();
}

// ─── account dialog (add / edit) ─────────────────────────────────────────────
let editingConn = null;   // the account being edited, null when adding

function accountStatusHtml(c) {
  const client = page.list?.mysql.client;
  if (!client) {
    return 'No <code>mariadb</code> / <code>mysql</code> client was found on this machine. Install the MariaDB or MySQL client to use this.';
  }
  let html = `Client: <code>${esc(client)}</code>`;
  if (!c) {
    const m = page.list.mysql;
    if (m.needsLogin) html += `<div class="db-status-err">Automatic login failed: ${esc(m.loginError || '')}</div>`;
    return html;
  }
  html += `<br>${c.listening ? 'Something is' : 'Nothing is'} answering on ${esc(c.host)}:${esc(c.port)}.`;
  if (c.error) html += `<div class="db-status-err">${esc(c.error)}</div>`;
  else if (c.databases) html += `<div class="db-status-ok">Connected as ${esc(c.user)} - ${c.databases.length} database(s).</div>`;
  return html;
}

function openAccountModal(c) {
  editingConn = c || null;
  document.getElementById('dbx-acc-title').textContent = c ? 'Edit Account' : 'Add Account';
  document.getElementById('dbx-acc-name').value = c?.name || '';
  document.getElementById('dbx-acc-host').value = c?.host || '127.0.0.1';
  document.getElementById('dbx-acc-port').value = c?.port || 3306;
  document.getElementById('dbx-acc-user').value = c?.user || '';
  const pw = document.getElementById('dbx-acc-password');
  pw.value = '';
  pw.placeholder = c ? '(unchanged)' : '';
  document.getElementById('dbx-acc-status').innerHTML = accountStatusHtml(c);
  document.getElementById('dbx-acc-remove').classList.toggle('hidden', !c);
  openModal('modal-dbx-account');
}

async function saveAccount() {
  const name = document.getElementById('dbx-acc-name').value.trim();
  const host = document.getElementById('dbx-acc-host').value.trim() || '127.0.0.1';
  const port = document.getElementById('dbx-acc-port').value.trim() || '3306';
  const user = document.getElementById('dbx-acc-user').value.trim();
  const pw = document.getElementById('dbx-acc-password').value;
  if (!user) { A.toast('Enter a user', 'error'); return; }
  const args = editingConn ? ['account', 'edit', '-conn', editingConn.id] : ['account', 'add'];
  args.push('-name', name, '-host', host, '-port', port, '-user', user);
  if (pw || !editingConn) args.push('-password', pw);
  const btn = document.getElementById('dbx-acc-save');
  btn.disabled = true;
  const r = await cli(args);
  btn.disabled = false;
  if (r.error) { A.toast(r.error, 'error'); return; }
  editingConn = r.connection;
  document.getElementById('dbx-acc-title').textContent = 'Edit Account';
  document.getElementById('dbx-acc-remove').classList.remove('hidden');
  document.getElementById('dbx-acc-password').placeholder = '(unchanged)';
  document.getElementById('dbx-acc-password').value = '';
  document.getElementById('dbx-acc-status').innerHTML = accountStatusHtml(r.connection);
  refreshPage();
  // Kept open on failure so the details can be corrected right away.
  if (r.connection.error) { A.toast(`Saved, but logging in failed: ${r.connection.error}`, 'error'); return; }
  closeModal('modal-dbx-account');
  A.toast(`Connected as ${r.connection.user}`, 'success');
}

async function removeAccount() {
  if (!editingConn) return;
  const r = await cli(['account', 'remove', '-conn', editingConn.id]);
  if (r.error) { A.toast(r.error, 'error'); return; }
  closeModal('modal-dbx-account');
  A.toast('Account removed', 'success');
  refreshPage();
}

// ═══ Registration ════════════════════════════════════════════════════════════
const view = A.registerPage({
  id: 'databases',
  label: 'Databases',
  title: 'Databases',
  subtitle: 'Database servers on this machine',
  icon: ICON_PAGE,
  render(body) {
    if (!TE) {
      body.innerHTML = '<div class="card" style="padding:18px">This version of MCPanel is too old for the Databases addon - update MCPanel.</div>';
      return;
    }
    body.innerHTML = `
      <div class="db-layout">
        <div class="card db-sidebar"><div class="db-tree"></div></div>
        <div class="card db-main"></div>
      </div>`;
    page.tree = body.querySelector('.db-tree');
    page.tree.addEventListener('click', onTreeClick);
    page.tree.addEventListener('keydown', onTreeKeydown);
    page.tree.addEventListener('contextmenu', onTreeContextMenu);
    page.editor = TE.create(body.querySelector('.db-main'), {
      emptyTitle: 'Pick a table',
      emptyText: 'Open a database on the left and choose a table to browse and edit its rows.',
      onWrite: () => { if (page.sel) loadTables(page.sel.conn, page.sel.db, { quiet: true }); },
    });
  },
  // Re-scanned on every visit: database servers come and go.
  onShow() {
    if (!TE) return;
    if (page.list) renderTree();
    refreshPage();
  },
}, { beforeSettings: true });

view.actions.innerHTML = `
  <button class="btn-ghost" data-act="refresh">${ICON_REFRESH} Refresh</button>
  <button class="btn-primary" data-act="add-account">${ICON_PLUS16} Add Account</button>`;
view.actions.addEventListener('click', e => {
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (act === 'refresh') refreshPage();
  else if (act === 'add-account' && TE) openAccountModal(null);
});

if (TE) addDialogs();

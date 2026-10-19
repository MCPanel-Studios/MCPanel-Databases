# MCPanel-Databases

A **Databases** page for [MCPanel](https://github.com/DippyCoder/MCPanel) and
MCPanel-WebUI: the MySQL / MariaDB servers on the machine running the panel —
saved accounts, their databases, tables and rows — as an
[MCPanel-CLI](https://github.com/DippyCoder/MCPanel-CLI) addon.

The built-in **SQLite editor** (double-click a `.db` file in a server's Files
tab) is part of MCPanel itself and works without this addon.

## What it does

- **Finds what's on the machine.** It looks for a `mariadb` / `mysql` client
  (PATH, plus the usual Windows and macOS install folders) and for servers on
  their default ports. PostgreSQL, MongoDB, Redis and SQL Server are listed
  when found, but only MySQL / MariaDB can be browsed so far.
- **Accounts.** The client's own login (OS-user socket login, `~/.my.cnf`) is
  tried automatically. Add any number of further accounts (host, port, user,
  password, optional name); each is its own collapsible group on the page.
- **Databases.** Create, rename (moves every table; refused if the database has
  views, triggers, stored procedures or events) and delete databases, and set
  their default character set / collation. The server's own schemas (`mysql`,
  `information_schema`, `performance_schema`, `sys`) are hidden and protected.
- **Tables and rows.** Browse 100 rows at a time with exact row counts, edit
  cells (NULL included), add and delete rows. Binary columns show their size.

## Requirements

- MCPanel-CLI **1.5.0** or newer, and MCPanel / MCPanel-WebUI from the same
  release (the page uses the panel's table editor, `window.MCPanelTableEditor`).
- The `mariadb` or `mysql` command-line client on the machine running the panel.
  No Python packages: queries go through that client.

## Install

```bash
mcpanel addons install /path/to/MCPanel-Databases/databases
```

or as a package:

```bash
pip install /path/to/MCPanel-Databases
```

Then restart (or reload) MCPanel / the WebUI — the **Databases** page appears in
the sidebar. `mcpanel addons disable databases` hides it again.

## Security notes

- Saved accounts live in `<userData>/addon-data/databases/accounts.json`,
  created readable only by your user. Passwords are never put on a command
  line: each query gets a private option file that is deleted right after.
  The panel's logs mask `-user` / `-password`.
- Values are sent as hex literals with a charset introducer, so nothing typed
  into a cell can be run as SQL.
- In MCPanel-WebUI the page is gated by the MCPanel-Accounts permissions
  `databases.view` (see), `databases.edit` (change rows), `databases.manage`
  (create / rename / delete databases) and `settings.manage` (saved accounts).

## Commands

These back the page and only exist under `mcpanel api` (JSON); they are not
meant to be typed. See `databases/__init__.py` for the full list.

Upgrading from an MCPanel build that had the Databases page built in: the
saved accounts in `<userData>/databases.json` are moved to the addon's data
folder automatically the first time the addon loads.
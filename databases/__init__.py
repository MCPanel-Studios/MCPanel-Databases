"""Databases page for MCPanel and MCPanel-WebUI — the MySQL / MariaDB servers
on this machine: accounts, databases, tables and rows.

Everything is detected at runtime on whatever machine the CLI runs on; see
``mysql.py`` for how the client is found and driven. The built-in SQLite
editor (opening a .db file from a server's Files tab) is part of MCPanel
itself, not this addon — this addon reuses its table grid
(``window.MCPanelTableEditor``) for the page.

The commands only exist under ``mcpanel api`` - they back the page, they are
not meant to be typed::

    mcpanel api databases list
    mcpanel api databases tables  [-conn <id|auto>] -db <database>
    mcpanel api databases rows    [-conn …] -db <db> -table <t> [-offset n] [-limit n]
    mcpanel api databases update  [-conn …] -db <db> -table <t> -key <json> -set <json>
    mcpanel api databases insert  [-conn …] -db <db> -table <t> [-values <json>]
    mcpanel api databases delete  [-conn …] -db <db> -table <t> -key <json>
    mcpanel api databases create  [-conn …] -name <db> [-charset cs] [-collation co]
    mcpanel api databases alter   [-conn …] -db <db> [-rename <new>] [-charset cs] [-collation co]
    mcpanel api databases drop    [-conn …] -db <db>
    mcpanel api databases account add    -user <u> [-password <p>] [-host h] [-port n] [-name label]
    mcpanel api databases account edit   -conn <id> [same flags]
    mcpanel api databases account remove -conn <id>
"""

import os

from . import mysql

ADDON = {
    "name": "databases",
    "version": "1.0.0",
    "description": "Databases page: MySQL / MariaDB accounts, databases, tables and rows",
    "author": "DippyCoder",
    "url": "https://github.com/DippyCoder/MCPanel-Databases",
    "api_version": 1,
    "ui": {
        "scripts": ["ui/databases.js"],
        "styles": ["ui/databases.css"],
    },
}


def _init_storage(api):
    """Point mysql.py at accounts.json in this addon's data folder - moving
    the file MCPanel itself used before the page became an addon."""
    if mysql.STATE_FILE:
        return
    path = os.path.join(api.data_dir(), "accounts.json")
    legacy = os.path.join(api.helpers.paths.USER_DATA, "databases.json")
    if not os.path.exists(path) and os.path.exists(legacy):
        try:
            os.replace(legacy, path)
            os.chmod(path, 0o600)
        except OSError:
            pass
    mysql.STATE_FILE = path


def _guard(fn):
    """Command handler wrapper: resolves -conn and turns client failures into
    the CLI's {"error", "code"} document."""
    def handler(args, progress=None):
        conf, err = mysql.resolve_conn(getattr(args, "conn", None))
        if err:
            return err
        try:
            return fn(args, conf)
        except mysql.MySQLError as e:
            return mysql.fail(e.code, str(e))
    return handler


def _list(args, progress=None):
    return {"mysql": mysql.state(), "engines": mysql.engines()}


def _account_add(args, progress=None):
    fields, err = mysql.account_fields(args, {})
    if err:
        return err
    conf = mysql.add_account(fields)
    return {"success": True, "connection": mysql.conn_status(conf, mysql.find_client())}


def _account_edit(args, progress=None):
    old = next((c for c in mysql.connections() if c["id"] == args.conn), None)
    if not old:
        return mysql.fail("invalid_arguments", f"No saved MySQL/MariaDB account with id {args.conn!r}")
    fields, err = mysql.account_fields(args, old)
    if err:
        return err
    conf = {**old, **fields}
    mysql.replace_account(conf)
    return {"success": True, "connection": mysql.conn_status(conf, mysql.find_client())}


def _account_remove(args, progress=None):
    if not mysql.remove_account(args.conn):
        return mysql.fail("invalid_arguments", f"No saved MySQL/MariaDB account with id {args.conn!r}")
    return {"success": True}


def register(api):
    _init_storage(api)
    # Backs the Databases page only: keep it out of the commands people type.
    if not getattr(api, "machine", True):
        return

    grp = api.group("databases", help="(for the Databases page) MySQL / MariaDB on this machine")

    def conn(p):
        p.add_argument("-conn", "--conn", dest="conn", default=None, metavar="<id|auto>",
                       help="saved account to use (see `databases list`); 'auto' = the client's own login")

    def table(p):
        conn(p)
        p.add_argument("-db", "--db", dest="db", required=True, metavar="<database>")
        p.add_argument("-table", "--table", dest="table", required=True, metavar="<table>")

    def charset(p):
        p.add_argument("-charset", "--charset", dest="charset", default=None, help="e.g. utf8mb4")
        p.add_argument("-collation", "--collation", dest="collation", default=None,
                       help="e.g. utf8mb4_unicode_ci (default: the charset's default)")

    api.command(grp, "list", _list, "databases-list",
                help="database servers on this machine + the databases each account can see")

    p = api.command(grp, "tables", _guard(lambda a, c: mysql.tables(a.db, c)), "databases-tables",
                    help="a database's tables, row counts and charset")
    conn(p)
    p.add_argument("-db", "--db", dest="db", required=True, metavar="<database>")

    p = api.command(grp, "rows", _guard(lambda a, c: mysql.rows(a.db, a.table, c, a.offset, a.limit)),
                    "databases-rows", help="one page of a table's rows")
    table(p)
    p.add_argument("-offset", "--offset", dest="offset", type=int, default=0)
    p.add_argument("-limit", "--limit", dest="limit", type=int, default=100, help=f"max {mysql.MAX_PAGE}")

    p = api.command(grp, "update", _guard(lambda a, c: mysql.write(a.db, a.table, c, "update", key=a.key, set_=a.set)),
                    "databases-write", help="change cells of one row")
    table(p)
    p.add_argument("-key", "--key", dest="key", required=True, metavar="<json>")
    p.add_argument("-set", "--set", dest="set", required=True, metavar="<json>")

    p = api.command(grp, "insert", _guard(lambda a, c: mysql.write(a.db, a.table, c, "insert", values=a.values)),
                    "databases-write", help="add a row (omitted columns get their default)")
    table(p)
    p.add_argument("-values", "--values", dest="values", default="{}", metavar="<json>")

    p = api.command(grp, "delete", _guard(lambda a, c: mysql.write(a.db, a.table, c, "delete", key=a.key)),
                    "databases-write", help="delete one row")
    table(p)
    p.add_argument("-key", "--key", dest="key", required=True, metavar="<json>")

    p = api.command(grp, "create", _guard(lambda a, c: mysql.create_db(a.name, c, a.charset, a.collation)),
                    "databases-write", help="create a database")
    conn(p)
    p.add_argument("-name", "--name", dest="name", required=True, metavar="<database>")
    charset(p)

    p = api.command(grp, "alter",
                    _guard(lambda a, c: mysql.alter_db(a.db, c, a.rename, a.charset, a.collation)),
                    "databases-write", help="rename a database and/or change its default charset")
    conn(p)
    p.add_argument("-db", "--db", dest="db", required=True, metavar="<database>")
    p.add_argument("-rename", "--rename", dest="rename", default=None, metavar="<new name>")
    charset(p)

    p = api.command(grp, "drop", _guard(lambda a, c: mysql.drop_db(a.db, c)), "databases-write",
                    help="delete a database and everything in it")
    conn(p)
    p.add_argument("-db", "--db", dest="db", required=True, metavar="<database>")

    acc = api.group("account", help="saved MySQL / MariaDB accounts", parent=grp)

    def account(p, required):
        p.add_argument("-name", "--name", dest="name", default=None, help="optional label")
        p.add_argument("-host", "--host", dest="host", default=None, help="default 127.0.0.1")
        p.add_argument("-port", "--port", dest="port", type=int, default=None, help="default 3306")
        p.add_argument("-user", "--user", dest="user", required=required, default=None)
        p.add_argument("-password", "--password", dest="password", default=None,
                       help="omit on edit to keep the stored password")

    p = api.command(acc, "add", _account_add, "databases-account", help="save an account (and test it)")
    account(p, True)
    p = api.command(acc, "edit", _account_edit, "databases-account", help="change a saved account (and test it)")
    p.add_argument("-conn", "--conn", dest="conn", required=True, metavar="<id>")
    account(p, False)
    p = api.command(acc, "remove", _account_remove, "databases-account", help="forget a saved account")
    p.add_argument("-conn", "--conn", dest="conn", required=True, metavar="<id>")

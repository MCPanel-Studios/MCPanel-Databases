"""MySQL / MariaDB through the `mariadb` / `mysql` command-line client.

Nothing here knows about any particular install; everything is detected at
runtime on whatever machine the CLI runs on. No driver is needed: queries go
through the client's --xml output, which (unlike the tab-separated mode) tells
a NULL apart from the string "NULL".

Accounts: the client's own login (OS-user socket login, ~/.my.cnf) is tried
automatically; any number of further accounts (host / user / password) are
saved in this addon's data folder as accounts.json, readable only by the user.
The password never reaches a command line: each query gets a private option
file that is deleted right after.

Rows are addressed by a `key` dict the `rows` command hands out with each row:
the table's primary key, else every non-binary column (and writes are LIMIT 1).
"""

import glob
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

MYSQL_SYSTEM_DBS = {"information_schema", "performance_schema", "mysql", "sys"}
MAX_PAGE = 500
# Above this many (estimated) rows a table shows InnoDB's estimate instead of
# an exact COUNT(*), which has to scan the table.
EXACT_COUNT_LIMIT = 500_000

# Set by the addon's register(): <userData>/addon-data/databases/accounts.json
STATE_FILE = None


def fail(code, message):
    return {"error": message, "code": code}


class MySQLError(Exception):
    code = "db_error"


# ─── saved accounts ──────────────────────────────────────────────────────────
def _load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_state(data):
    tmp = STATE_FILE + ".tmp"
    # Created 0600 from the start: it holds database passwords.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, STATE_FILE)


def connections(state=None):
    """Saved accounts. A single {host, user, …} object - the format from before
    multiple accounts existed - is read as a one-item list."""
    saved = (state if state is not None else _load_state()).get("mysql")
    if isinstance(saved, dict):
        saved = [{**saved, "id": saved.get("id") or "c1"}]
    return [c for c in saved or [] if isinstance(c, dict) and c.get("id") and c.get("user")]


def resolve_conn(want):
    """The account to run as: a saved account's id, 'auto' for the client's
    own login, or - when left out - the only saved account, else the automatic
    login. Returns (conf or None for auto, error)."""
    conns = connections()
    if want == "auto" or (not want and not conns):
        return None, None
    if not want:
        if len(conns) == 1:
            return conns[0], None
        return None, fail("invalid_arguments",
                          "Several MySQL/MariaDB accounts are saved - pick one with -conn <id> "
                          f"({', '.join(c['id'] for c in conns)})")
    conf = next((c for c in conns if c["id"] == want), None)
    if not conf:
        return None, fail("invalid_arguments", f"No saved MySQL/MariaDB account with id {want!r}")
    return conf, None


# ─── the client ──────────────────────────────────────────────────────────────
def find_client():
    """The mariadb/mysql client on THIS machine: PATH first, then the usual
    install folders on Windows and macOS, which installers don't always add
    to PATH."""
    for name in ("mariadb", "mysql"):
        found = shutil.which(name)
        if found:
            return found
    patterns = []
    if sys.platform == "win32":
        for base in filter(None, (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"))):
            patterns += [os.path.join(base, "MariaDB*", "bin", "mariadb.exe"),
                         os.path.join(base, "MariaDB*", "bin", "mysql.exe"),
                         os.path.join(base, "MySQL", "MySQL Server*", "bin", "mysql.exe")]
        patterns.append(r"C:\xampp\mysql\bin\mysql.exe")
    elif sys.platform == "darwin":
        patterns += ["/opt/homebrew/bin/mariadb", "/opt/homebrew/bin/mysql",
                     "/usr/local/bin/mariadb", "/usr/local/bin/mysql", "/usr/local/mysql/bin/mysql",
                     "/opt/homebrew/opt/mysql-client/bin/mysql", "/usr/local/opt/mysql-client/bin/mysql",
                     "/Applications/MAMP/Library/bin/mysql"]
    for pattern in patterns:
        hits = sorted(glob.glob(pattern), reverse=True)  # newest version folder first
        if hits:
            return hits[0]
    return None


def port_open(host, port, timeout=0.5):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def _opt_value(v):
    # Option-file values: quoted, with backslashes and quotes escaped.
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def run(sql, database=None, conf=None):
    """Runs `sql` through the client as account `conf` (None: the client's own
    login) and returns the rows of the LAST result set as a list of
    {column: str|None} dicts, in column order."""
    client = find_client()
    if not client:
        raise MySQLError("No MySQL/MariaDB client (mariadb or mysql) was found on this machine")
    opt_path = None
    try:
        argv = [client]
        if conf:
            fd, opt_path = tempfile.mkstemp(prefix="mcpanel-my-", suffix=".cnf")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("[client]\n")
                f.write(f"host={_opt_value(conf.get('host') or '127.0.0.1')}\n")
                f.write(f"port={int(conf.get('port') or 3306)}\n")
                f.write(f"user={_opt_value(conf['user'])}\n")
                if conf.get("password"):
                    f.write(f"password={_opt_value(conf['password'])}\n")
            argv.append(f"--defaults-extra-file={opt_path}")
        argv += ["--xml", "--batch", "--default-character-set=utf8mb4", "--connect-timeout=5"]
        if database:
            argv += ["--database", database]
        try:
            out = subprocess.run(argv, input=sql.encode("utf-8"), capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            raise MySQLError("The database didn't answer within 60 seconds")
    finally:
        if opt_path:
            try:
                os.remove(opt_path)
            except OSError:
                pass
    if out.returncode != 0:
        msg = out.stderr.decode("utf-8", "replace").strip().splitlines()
        raise MySQLError(msg[-1] if msg else f"{os.path.basename(client)} exited with code {out.returncode}")
    text = out.stdout.decode("utf-8", "replace")
    docs = [d for d in re.split(r"(?=<\?xml)", text) if d.strip()]
    if not docs:
        return []
    try:
        root = ET.fromstring(docs[-1].encode("utf-8"))
    except ET.ParseError as e:
        raise MySQLError(f"Could not read the client's output: {e}")
    nil = "{http://www.w3.org/2001/XMLSchema-instance}nil"
    return [{fld.get("name"): (None if fld.get(nil) == "true" else (fld.text or ""))
             for fld in row.findall("field")}
            for row in root.findall("row")]


# ─── SQL building ────────────────────────────────────────────────────────────
def mq(name):
    return "`" + str(name).replace("`", "``") + "`"


def mstr(v):
    """A string literal that needs no escaping at all: hex with a charset
    introducer, so no value can break out of it."""
    return "_utf8mb4 X'" + str(v).encode("utf-8").hex() + "'"


_INT_TYPES = {"tinyint", "smallint", "mediumint", "int", "integer", "bigint"}
_BLOB_TYPES = {"binary", "varbinary", "tinyblob", "blob", "mediumblob", "longblob",
               "geometry", "point", "linestring", "polygon", "multipoint",
               "multilinestring", "multipolygon", "geometrycollection"}


def _lit(v, col):
    """Literal for a value compared to / written into `col`. Integer and
    decimal values are written bare so a BIGINT key is matched exactly rather
    than through a lossy string→double conversion."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    s = str(v)
    if col["dataType"] in _INT_TYPES and re.fullmatch(r"-?\d+", s):
        return s
    if col["dataType"] in ("decimal", "numeric") and re.fullmatch(r"-?\d+(\.\d+)?", s):
        return s
    return mstr(s)


def _json_arg(raw, what):
    try:
        val = json.loads(raw or "{}")
    except ValueError:
        return None, fail("invalid_arguments", f"{what} must be a JSON object")
    if not isinstance(val, dict):
        return None, fail("invalid_arguments", f"{what} must be a JSON object")
    return val, None


def _page(offset, limit):
    try:
        return max(0, int(offset or 0)), min(MAX_PAGE, max(1, int(limit or 100))), None
    except (TypeError, ValueError):
        return None, None, fail("invalid_arguments", "offset/limit must be numbers")


# ─── tables and rows ─────────────────────────────────────────────────────────
def _columns(db, table, conf):
    rows = run(
        "SELECT COLUMN_NAME, COLUMN_TYPE, DATA_TYPE, COLUMN_KEY, IS_NULLABLE, COLUMN_DEFAULT, EXTRA "
        f"FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = {mstr(db)} AND TABLE_NAME = {mstr(table)} "
        "ORDER BY ORDINAL_POSITION;", conf=conf)
    return [{"name": r["COLUMN_NAME"], "type": r["COLUMN_TYPE"], "dataType": (r["DATA_TYPE"] or "").lower(),
             "pk": r["COLUMN_KEY"] == "PRI", "notnull": r["IS_NULLABLE"] == "NO",
             "default": r["COLUMN_DEFAULT"], "autoIncrement": "auto_increment" in (r["EXTRA"] or ""),
             "blob": (r["DATA_TYPE"] or "").lower() in _BLOB_TYPES}
            for r in rows]


def _key_cols(cols):
    pk = [c for c in cols if c["pk"]]
    return (pk, "pk") if pk else ([c for c in cols if not c["blob"]], "all")


def _where(key, cols):
    key_cols, mode = _key_cols(cols)
    if not key_cols or any(c["name"] not in key for c in key_cols):
        return None, mode
    # <=> is MySQL's NULL-safe equality.
    return " AND ".join(f"{mq(c['name'])} <=> {_lit(key[c['name']], c)}" for c in key_cols), mode


def existing_db(db, conf):
    if db not in {r["Database"] for r in run("SHOW DATABASES;", conf=conf)}:
        raise MySQLError(f"Database not found: {db}")
    return db


def tables(db, conf):
    db = existing_db(db, conf)
    rows = run("SELECT TABLE_NAME, TABLE_ROWS FROM information_schema.TABLES "
               f"WHERE TABLE_SCHEMA = {mstr(db)} AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME;", conf=conf)
    info = run("SELECT DEFAULT_CHARACTER_SET_NAME AS cs, DEFAULT_COLLATION_NAME AS co "
               f"FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = {mstr(db)};", conf=conf)
    # TABLE_ROWS is only InnoDB's statistics estimate - often 0 for tables that
    # have rows - so tables are counted exactly, in one query. Only very large
    # tables keep the estimate, where COUNT(*) would make opening the database slow.
    est = {r["TABLE_NAME"]: int(r["TABLE_ROWS"]) if (r["TABLE_ROWS"] or "").isdigit() else None for r in rows}
    exact = [n for n, e in est.items() if e is None or e <= EXACT_COUNT_LIMIT]
    counts = {}
    if exact:
        union = " UNION ALL ".join(f"SELECT {mstr(n)} AS t, COUNT(*) AS n FROM {mq(n)}" for n in exact)
        counts = {r["t"]: int(r["n"]) for r in run(union + ";", db, conf)}
    return {"database": db,
            "charset": info[0]["cs"] if info else None, "collation": info[0]["co"] if info else None,
            "tables": [{"name": n, "rows": counts.get(n, est[n]), "estimate": n not in counts} for n in est]}


def _table_cols(db, table, conf):
    db = existing_db(db, conf)
    cols = _columns(db, table, conf)
    if not cols:
        raise MySQLError(f"Table not found: {table}")
    return db, cols


def rows(db, table, conf, offset, limit):
    offset, limit, err = _page(offset, limit)
    if err:
        return err
    db, cols = _table_cols(db, table, conf)
    key_cols, mode = _key_cols(cols)
    # Binary columns would break the XML output; their size is all the grid shows.
    sel = ", ".join(f"LENGTH({mq(c['name'])}) AS {mq(c['name'])}" if c["blob"] else mq(c["name"]) for c in cols)
    order = f" ORDER BY {', '.join(mq(c['name']) for c in key_cols)}" if mode == "pk" else ""
    data = run(f"SELECT {sel} FROM {mq(table)}{order} LIMIT {limit} OFFSET {offset};", db, conf)
    total = run(f"SELECT COUNT(*) AS n FROM {mq(table)};", db, conf)
    out = []
    for r in data:
        values = [({"$blob": int(r[c["name"]])} if c["blob"] and r[c["name"]] is not None else r[c["name"]])
                  for c in cols]
        out.append({"key": {c["name"]: r[c["name"]] for c in key_cols}, "values": values})
    return {"database": db, "table": table,
            "columns": [{k: c[k] for k in ("name", "type", "pk", "notnull", "default", "autoIncrement", "blob")}
                        for c in cols],
            "keyMode": mode, "rows": out, "total": int(total[0]["n"]) if total else len(out),
            "offset": offset, "limit": limit}


def write(db, table, conf, op, key=None, set_=None, values=None):
    db, cols = _table_cols(db, table, conf)
    by_name = {c["name"]: c for c in cols}
    t = mq(table)
    if op == "insert":
        vals, err = _json_arg(values, "-values")
        if err:
            return err
        unknown = [k for k in vals if k not in by_name]
        if unknown:
            return fail("invalid_arguments", f"Unknown column(s): {', '.join(unknown)}")
        cols_sql = ", ".join(mq(k) for k in vals)
        vals_sql = ", ".join(_lit(v, by_name[k]) for k, v in vals.items())
        stmt = f"INSERT INTO {t} ({cols_sql}) VALUES ({vals_sql})" if vals else f"INSERT INTO {t} () VALUES ()"
    else:
        k, err = _json_arg(key, "-key")
        if err:
            return err
        where, mode = _where(k, cols)
        if not where:
            return fail("invalid_arguments", "-key doesn't identify a row of this table")
        limit = " LIMIT 1" if mode == "all" else ""
        if op == "update":
            changes, err = _json_arg(set_, "-set")
            if err:
                return err
            bad = [c for c in changes if c not in by_name or by_name[c]["blob"]]
            if bad or not changes:
                return fail("invalid_arguments", f"Can't set column(s): {', '.join(bad)}" if bad else "-set is empty")
            sets = ", ".join(f"{mq(c)} = {_lit(v, by_name[c])}" for c, v in changes.items())
            stmt = f"UPDATE {t} SET {sets} WHERE {where}{limit}"
        else:
            stmt = f"DELETE FROM {t} WHERE {where}{limit}"
    res = run(f"{stmt}; SELECT ROW_COUNT() AS n;", db, conf)
    changed = int(res[0]["n"]) if res and (res[0]["n"] or "").lstrip("-").isdigit() else None
    # ROW_COUNT() is 0 for an UPDATE that set a cell to the value it already
    # had, so only a DELETE can tell "no such row" from "nothing to change".
    if op == "delete" and changed == 0:
        return fail("row_not_found", "That row no longer exists - it may have been changed or deleted. Reload the table.")
    return {"success": True, "changed": changed}


# ─── accounts / machine overview ─────────────────────────────────────────────
def conn_status(conf, client):
    """One account's state + database list; `conf` None is the automatic
    login. Never contains the password."""
    conf = conf or {}
    host = conf.get("host") or "127.0.0.1"
    port = int(conf.get("port") or 3306)
    st = {"id": conf.get("id") or "auto", "name": conf.get("name") or "", "auto": not conf,
          "host": host, "port": port, "user": conf.get("user"),
          "listening": port_open(host, port), "databases": None}
    if not client or not (conf or st["listening"]):
        return st
    try:
        if not conf:
            who = run("SELECT CURRENT_USER() AS u;")
            st["user"] = who[0]["u"] if who else None
        names = [r["Database"] for r in run("SHOW DATABASES;", conf=conf or None)]
        st["databases"] = [n for n in names if n not in MYSQL_SYSTEM_DBS]
    except MySQLError as e:
        st["error"] = str(e)
    return st


def state():
    """Every saved account, plus the automatic login when it works. If the
    automatic login fails and nothing is saved, `needsLogin` tells the panel
    to ask for an account."""
    client = find_client()
    conns = [conn_status(c, client) for c in connections()]
    out = {"client": client, "connections": conns, "listening": port_open("127.0.0.1", 3306)}
    if client and out["listening"]:
        auto = conn_status(None, client)
        if auto.get("error"):
            if not conns:
                out["needsLogin"] = True
                out["loginError"] = auto["error"]
        # Already saved under its own name: don't list the same login twice.
        elif not any(c.get("user") == auto["user"] and c.get("databases") is not None for c in conns):
            conns.insert(0, auto)
    return out


# Database servers the overview looks for: (id, name, default port, client
# programs). Only MySQL/MariaDB can be browsed and edited so far; the others
# are reported so the page can show what's on the machine.
ENGINES = [
    ("postgresql", "PostgreSQL", 5432, ("psql",)),
    ("mongodb", "MongoDB", 27017, ("mongosh", "mongo")),
    ("redis", "Redis", 6379, ("redis-cli",)),
    ("mssql", "Microsoft SQL Server", 1433, ("sqlcmd",)),
]


def engines():
    out = []
    for eid, name, port, clients in ENGINES:
        client = next((c for c in map(shutil.which, clients) if c), None)
        listening = port_open("localhost", port, timeout=0.3)
        if client or listening:
            out.append({"id": eid, "name": name, "port": port, "client": client,
                        "listening": listening, "supported": False})
    return out


def account_fields(args, old):
    """Validated account fields from add/edit flags, on top of `old`."""
    user = args.user.strip() if args.user is not None else old.get("user", "")
    if not user:
        return None, fail("invalid_arguments", "A user is required (-user)")
    try:
        port = int(args.port if args.port is not None else old.get("port", 3306))
    except (TypeError, ValueError):
        port = 0
    if not 1 <= port <= 65535:
        return None, fail("invalid_port", "The port must be between 1 and 65535.")
    return {
        "name": (args.name if args.name is not None else old.get("name", "")).strip(),
        "host": (args.host if args.host is not None else old.get("host") or "127.0.0.1").strip() or "127.0.0.1",
        "port": port,
        "user": user,
        # Left out on edit: keep the stored password.
        "password": args.password if args.password is not None else old.get("password", ""),
    }, None


def add_account(fields):
    st = _load_state()
    conf = {"id": uuid.uuid4().hex[:8], **fields}
    st["mysql"] = connections(st) + [conf]
    _save_state(st)
    return conf


def replace_account(conf):
    st = _load_state()
    st["mysql"] = [conf if c["id"] == conf["id"] else c for c in connections(st)]
    _save_state(st)


def remove_account(conn_id):
    st = _load_state()
    conns = connections(st)
    if not any(c["id"] == conn_id for c in conns):
        return False
    st["mysql"] = [c for c in conns if c["id"] != conn_id]
    _save_state(st)
    return True


# ─── whole databases ─────────────────────────────────────────────────────────
# Names are limited to what plugins actually use, so a name never needs more
# than backtick quoting and can't collide with the server's own schemas.
_DB_NAME = re.compile(r"^[A-Za-z0-9_$-]{1,64}$")
_CHARSET_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def check_db_name(name):
    if not name or not _DB_NAME.match(name):
        return fail("invalid_name", "Database names may only use letters, digits, _ $ - (max 64)")
    if name.lower() in MYSQL_SYSTEM_DBS:
        return fail("invalid_name", f"{name} is one of the server's own databases")
    return None


def charset_sql(charset, collation):
    """ CHARACTER SET … COLLATE … for CREATE/ALTER DATABASE, or an error."""
    sql = ""
    for value, kw in ((charset, "CHARACTER SET"), (collation, "COLLATE")):
        if value:
            if not _CHARSET_NAME.match(value):
                return None, fail("invalid_arguments", f"Not a character set / collation name: {value}")
            sql += f" {kw} {value}"
    return sql, None


def create_db(name, conf, charset=None, collation=None):
    err = check_db_name(name)
    if err:
        return err
    opts, err = charset_sql(charset, collation)
    if err:
        return err
    if name in {r["Database"] for r in run("SHOW DATABASES;", conf=conf)}:
        return fail("invalid_name", f"A database named {name} already exists")
    run(f"CREATE DATABASE {mq(name)}{opts};", conf=conf)
    return {"success": True, "database": name, "message": f"Created database {name}"}


def alter_db(db, conf, rename=None, charset=None, collation=None):
    """Change a database's default character set / collation, and/or rename
    it. MySQL has no RENAME DATABASE: the rename creates the new database,
    moves every table in one atomic RENAME TABLE, then drops the emptied old
    one - so it is refused while views, triggers, routines or events exist,
    which that would leave behind or break."""
    err = check_db_name(db) or (rename and check_db_name(rename))
    if err:
        return err
    opts, err = charset_sql(charset, collation)
    if err:
        return err
    db = existing_db(db, conf)
    new = rename if rename and rename != db else None
    if not opts and not new:
        return fail("invalid_arguments", "Nothing to change - give -rename, -charset or -collation")
    if opts:
        run(f"ALTER DATABASE {mq(db)}{opts};", conf=conf)
    if not new:
        return {"success": True, "database": db, "message": f"Updated database {db}"}

    if new in {r["Database"] for r in run("SHOW DATABASES;", conf=conf)}:
        return fail("invalid_name", f"A database named {new} already exists")
    q = mstr(db)
    blockers = run(
        f"SELECT (SELECT COUNT(*) FROM information_schema.VIEWS WHERE TABLE_SCHEMA = {q}) AS views,"
        f" (SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = {q}) AS triggers,"
        f" (SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = {q}) AS routines,"
        f" (SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA = {q}) AS events;",
        conf=conf)[0]
    found = [f"{n} {k}" for k, n in blockers.items() if n and n != "0"]
    if found:
        return fail("db_error", f"Can't rename {db}: it has {', '.join(found)}, which a rename can't move")
    info = run("SELECT DEFAULT_CHARACTER_SET_NAME AS cs, DEFAULT_COLLATION_NAME AS co "
               f"FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = {q};", conf=conf)[0]
    names = [r["TABLE_NAME"] for r in run(
        f"SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = {q};", conf=conf)]
    run(f"CREATE DATABASE {mq(new)} CHARACTER SET {info['cs']} COLLATE {info['co']};", conf=conf)
    if names:
        moves = ", ".join(f"{mq(db)}.{mq(t)} TO {mq(new)}.{mq(t)}" for t in names)
        try:
            run(f"RENAME TABLE {moves};", conf=conf)
        except MySQLError:
            # RENAME TABLE is all-or-nothing, so the new database is still
            # empty: take it away again and report the original error.
            run(f"DROP DATABASE {mq(new)};", conf=conf)
            raise
    run(f"DROP DATABASE {mq(db)};", conf=conf)
    return {"success": True, "database": new,
            "message": f"Renamed {db} to {new}",
            "warning": f"Privileges granted on `{db}` don't move to `{new}` - update any GRANTs and plugin configs"}


def drop_db(db, conf):
    err = check_db_name(db)
    if err:
        return err
    db = existing_db(db, conf)
    run(f"DROP DATABASE {mq(db)};", conf=conf)
    return {"success": True, "message": f"Deleted database {db}"}

import pg8000.native
import os
from urllib.parse import urlparse
from flask import g

def parse_url():
    url = os.environ.get('DATABASE_URL', '')
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    p = urlparse(url)
    return {
        'host': p.hostname,
        'port': p.port or 5432,
        'database': p.path.lstrip('/'),
        'user': p.username,
        'password': p.password,
        'ssl_context': True
    }

def get_db():
    if 'db' not in g:
        g.db = pg8000.native.Connection(**parse_url())
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        try:
            db.close()
        except:
            pass

def q(conn, sql, params=None):
    try:
        rows = conn.run(sql, **params) if params else conn.run(sql)
        cols = [c['name'] for c in (conn.columns or [])]
        return [dict(zip(cols, row)) for row in (rows or [])]
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        raise e

def q1(conn, sql, params=None):
    rows = q(conn, sql, params)
    return rows[0] if rows else None

def init_db():
    print('[db] Conectando...')
    conn = pg8000.native.Connection(**parse_url())
    result = conn.run("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'")
    print(f'[db] {result[0][0]} tablas encontradas OK')
    conn.close()

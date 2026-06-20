import pg8000.dbapi
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
        params = parse_url()
        conn = pg8000.dbapi.connect(**params)
        conn.autocommit = False
        g.db = conn
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        try:
            db.close()
        except:
            pass

def q(conn, sql, params=None):
    """Execute query and return list of dicts."""
    try:
        cur = conn.cursor()
        if params:
            # Convert :name style to %s style for pg8000.dbapi
            # Ojo: NO tocar los :: de PostgreSQL (casts como ::text, ::date)
            import re
            keys = []
            def replace_param(m):
                keys.append(m.group(1))
                return '%s'
            # (?<!:) evita matchear el segundo : de un :: ; (?!:) evita el primero
            sql2 = re.sub(r'(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)', replace_param, sql)
            values = [params[k] for k in keys]
            cur.execute(sql2, values)
        else:
            cur.execute(sql)
        if cur.description:
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            return [dict(zip(cols, row)) for row in rows]
        return []
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
    params = parse_url()
    conn = pg8000.dbapi.connect(**params)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'")
    count = cur.fetchone()[0]
    # Auto-unir usuarios existentes a boliches activos (idempotente)
    try:
        cur.execute("""INSERT INTO boliche_usuarios (boliche_id, usuario_id)
            SELECT b.id, u.id FROM boliches b, usuarios u
            WHERE b.activo = TRUE ON CONFLICT DO NOTHING""")
        conn.commit()
        print('[db] Usuarios sincronizados con boliches OK')
    except Exception as e:
        print(f'[db] Sync warning: {e}')
        conn.rollback()
    # Migrar categorías de texto existentes a la tabla categorias (idempotente)
    try:
        cur.execute("""INSERT INTO categorias (boliche_id, nombre)
            SELECT boliche_id, categoria FROM premios
            WHERE categoria IS NOT NULL AND categoria != ''
            GROUP BY boliche_id, categoria
            ON CONFLICT DO NOTHING""")
        conn.commit()
        print('[db] Categorías migradas OK')
    except Exception as e:
        print(f'[db] Categorías warning: {e}')
        conn.rollback()
    conn.close()
    print(f'[db] {count} tablas encontradas OK')

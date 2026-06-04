import pg8000.native
import os
from urllib.parse import urlparse
from flask import g

def parse_url():
    url = os.environ.get('DATABASE_URL', '')
    # pg8000 no acepta el prefijo postgres:// directamente
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
        g.db = pg8000.native.Connection(**params)
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        try:
            db.close()
        except:
            pass

class Row(dict):
    """Dict que permite acceso por índice como psycopg2.extras.RealDictRow"""
    def __getitem__(self, key):
        if isinstance(key, str):
            return super().__getitem__(key)
        return list(self.values())[key]

def execute(conn, query, params=None):
    """Ejecuta una query y devuelve lista de Row dicts."""
    # pg8000 usa %s pero necesitamos convertir parámetros None correctamente
    try:
        if params:
            result = conn.run(query, *params)
        else:
            result = conn.run(query)
        cols = [c['name'] for c in conn.columns] if conn.columns else []
        return [Row(zip(cols, row)) for row in (result or [])]
    except Exception as e:
        raise e

def execute_one(conn, query, params=None):
    rows = execute(conn, query, params)
    return rows[0] if rows else None

def init_db():
    params = parse_url()
    conn = pg8000.native.Connection(**params)

    conn.run("""
        CREATE EXTENSION IF NOT EXISTS "pgcrypto"
    """)

    conn.run("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            usuario TEXT UNIQUE NOT NULL,
            dni TEXT UNIQUE NOT NULL,
            nombre_display TEXT,
            puntos_total INTEGER DEFAULT 0,
            nivel INTEGER DEFAULT 1,
            avatar TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.run("""
        CREATE TABLE IF NOT EXISTS eventos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            fecha DATE NOT NULL,
            nombre TEXT,
            activo BOOLEAN DEFAULT FALSE,
            ganador TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.run("""
        CREATE TABLE IF NOT EXISTS visitas (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            usuario_id UUID REFERENCES usuarios(id),
            evento_id UUID REFERENCES eventos(id),
            puntos_asistencia INTEGER DEFAULT 0,
            puntos_consumo INTEGER DEFAULT 0,
            puntos_racha INTEGER DEFAULT 0,
            puntos_mesa INTEGER DEFAULT 0,
            consumo_pesos INTEGER DEFAULT 0,
            es_mesa BOOLEAN DEFAULT FALSE,
            origen TEXT DEFAULT 'caja',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.run("""
        CREATE TABLE IF NOT EXISTS ranking_noche (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            usuario_id UUID REFERENCES usuarios(id),
            evento_id UUID REFERENCES eventos(id),
            posicion INTEGER,
            consumo_pesos INTEGER DEFAULT 0,
            gano_botella BOOLEAN DEFAULT FALSE,
            puntos_bonus INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.run("""
        CREATE TABLE IF NOT EXISTS premios (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            nombre TEXT NOT NULL,
            categoria TEXT,
            precio_pesos INTEGER DEFAULT 0,
            puntos_necesarios INTEGER NOT NULL,
            activo BOOLEAN DEFAULT TRUE,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.run("""
        CREATE TABLE IF NOT EXISTS canjes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            usuario_id UUID REFERENCES usuarios(id),
            premio_id UUID REFERENCES premios(id),
            codigo_unico TEXT UNIQUE NOT NULL,
            usado BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            usado_at TIMESTAMP
        )
    """)

    conn.run("""
        CREATE TABLE IF NOT EXISTS config_puntos (
            clave TEXT PRIMARY KEY,
            valor INTEGER NOT NULL,
            descripcion TEXT
        )
    """)

    for clave, valor, desc in [
        ('puntos_asistencia',    20,  'Jaggercitos por ir al boliche'),
        ('puntos_mesa',          30,  'Jaggercitos extra por tener mesa'),
        ('puntos_racha_3',       50,  'Bonus por 3 semanas seguidas'),
        ('puntos_racha_mes',    150,  'Bonus por 1 mes seguido'),
        ('puntos_por_mil_pesos',  1,  'Jaggercitos por cada $1.000 gastados'),
        ('bonus_ganador_noche', 300,  'Jaggercitos bonus al ganador de la noche'),
        ('bonus_segundo',       150,  'Jaggercitos bonus al segundo puesto'),
        ('bonus_tercero',        75,  'Jaggercitos bonus al tercer puesto'),
    ]:
        conn.run(
            "INSERT INTO config_puntos (clave,valor,descripcion) VALUES (:c,:v,:d) ON CONFLICT (clave) DO NOTHING",
            c=clave, v=valor, d=desc
        )

    count = conn.run("SELECT COUNT(*) FROM premios")
    if count[0][0] == 0:
        premios = [
            ('Speed','Bebidas',7000,21),('Speed X6','Bebidas',35000,105),
            ('Jugo','Bebidas',7000,21),('Lata Coca','Bebidas',6500,20),
            ('Lata Tónica','Bebidas',7000,21),('Agua','Bebidas',5500,17),
            ('Budweiser','Bebidas',7000,21),('Budweiser X6','Bebidas',35000,105),
            ('Shot Hodlmoser','Shots',7000,21),('Shot Absolut','Shots',7000,21),
            ('Sernova trago','Tragos',8000,24),('Absolut trago','Tragos',9500,29),
            ('Hodlmoser trago','Tragos',9000,27),('Fernet trago','Tragos',8000,24),
            ('Gin trago','Tragos',9500,29),('Campari','Tragos',8000,24),
            ('Malibu trago','Tragos',8500,26),
            ('Sernova','Bottle Service',85000,255),('Absolut','Bottle Service',105000,315),
            ('Red Label','Bottle Service',120000,360),('Red Label Litro','Bottle Service',140000,420),
            ('Black Label','Bottle Service',170000,510),('Jagermeister','Bottle Service',120000,360),
            ('Beefeater','Bottle Service',120000,360),('Gin Blu','Bottle Service',100000,300),
            ('Malibu','Bottle Service',100000,300),('Fernet Branca','Bottle Service',90000,270),
            ('Ramazotti','Bottle Service',90000,270),
            ('Norton Cosecha Tardía','Champagne',50000,150),('Mumm','Champagne',60000,180),
            ('Chandon','Champagne',80000,240),('Baron B','Champagne',100000,300),
            ('Belvedere Luminous','Importados',180000,540),('Belvedere Luminous X2','Importados',340000,1020),
            ('Cliquot','Importados',220000,660),('Moet Néctar','Importados',240000,720),
            ('Moet Ice','Importados',250000,750),('Nuvo','Importados',180000,540),
            ('Nuvo X2','Importados',340000,1020),
            ('Entrada gratis','Beneficios',0,0),('Mesa gratis','Beneficios',0,0),
        ]
        for nombre, cat, precio, pts in premios:
            conn.run(
                "INSERT INTO premios (nombre,categoria,precio_pesos,puntos_necesarios) VALUES (:n,:c,:p,:pts)",
                n=nombre, c=cat, p=precio, pts=pts
            )

    conn.close()
    print('[db] Tablas verificadas OK')

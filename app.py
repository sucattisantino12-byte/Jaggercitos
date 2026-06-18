from flask import Flask, jsonify, request, session, send_from_directory
import os, hashlib, secrets, traceback
from datetime import timedelta
from db import get_db, init_db, close_db, q, q1

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clubpass_secret_2024')
app.permanent_session_lifetime = timedelta(hours=12)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
app.teardown_appcontext(close_db)

SUPER_ADMIN_PASSWORD = os.environ.get('SUPER_ADMIN_PASSWORD', 'superadmin2024')
EXTERNAL_API_KEY = os.environ.get('EXTERNAL_API_KEY', 'clubpass_ext_key')

with app.app_context():
    init_db()

# ── HELPERS ───────────────────────────────────────────────────────────────────

def hp(p): return hashlib.sha256(p.encode()).hexdigest()

def nivel(pts):
    if pts >= 3000: return 4
    if pts >= 1000: return 3
    if pts >= 300:  return 2
    return 1

def cfg(boliche_id):
    db = get_db()
    rows = q(db, 'SELECT clave, valor FROM config_puntos WHERE boliche_id=:bid', {'bid': boliche_id})
    return {r['clave']: r['valor'] for r in rows}

def safe(row):
    if not row: return None
    return {k: str(v) if hasattr(v, 'hex') or v.__class__.__name__ == 'UUID' else v
            for k, v in row.items()}

def get_admin_session():
    return session.get('admin_id'), session.get('admin_rol'), session.get('admin_boliche_id')

def require_admin(roles=None):
    admin_id, rol, boliche_id = get_admin_session()
    if not admin_id: return None
    if roles and rol not in roles: return None
    return {'id': admin_id, 'rol': rol, 'boliche_id': boliche_id}

def require_super():
    return session.get('super_admin')

@app.errorhandler(Exception)
def handle_error(e):
    traceback.print_exc()
    return jsonify({'ok': False, 'error': str(e)}), 500

# ── PÁGINAS ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    path = os.path.join(os.path.dirname(__file__), 'admin.html')
    with open(path, encoding='utf-8') as f:
        from flask import render_template_string
        return render_template_string(f.read())

@app.route('/cliente')
def cliente():
    path = os.path.join(os.path.dirname(__file__), 'client', 'index.html')
    with open(path, encoding='utf-8') as f:
        return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/superadmin')
def superadmin():
    path = os.path.join(os.path.dirname(__file__), 'superadmin.html')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}
    return '<h1>Super Admin - coming soon</h1>', 200

@app.route('/manifest.json')
def manifest():
    return jsonify({"name":"ClubPass","short_name":"ClubPass","start_url":"/cliente","display":"standalone","background_color":"#050505","theme_color":"#d4a829"})

@app.route('/sw.js')
def sw():
    return "self.addEventListener('install',e=>self.skipWaiting());self.addEventListener('activate',e=>self.clients.claim());", 200, {'Content-Type':'application/javascript'}

# ── AUTH SUPER ADMIN ───────────────────────────────────────────────────────────

@app.route('/api/superadmin/login', methods=['POST'])
def superadmin_login():
    body = request.get_json() or {}
    if body.get('password') == SUPER_ADMIN_PASSWORD:
        session.permanent = True
        session['super_admin'] = True
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Contraseña incorrecta'}), 401

@app.route('/api/superadmin/logout', methods=['POST'])
def superadmin_logout():
    session.pop('super_admin', None)
    return jsonify({'ok': True})

# ── AUTH ADMIN BOLICHE ─────────────────────────────────────────────────────────

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    body = request.get_json() or {}
    email = body.get('email','').strip().lower()
    password = body.get('password','').strip()
    db = get_db()
    row = q1(db, '''SELECT a.id, a.rol, a.nombre, a.boliche_id,
                           b.nombre as boliche_nombre, b.slug, b.color_primario
                    FROM admins a JOIN boliches b ON b.id=a.boliche_id
                    WHERE a.email=:e AND a.password_hash=:p AND a.activo=TRUE''',
             {'e': email, 'p': hp(password)})
    if not row: return jsonify({'ok': False, 'error': 'Email o contraseña incorrectos'}), 401
    session.permanent = True
    session['admin_id'] = str(row['id'])
    session['admin_rol'] = row['rol']
    session['admin_boliche_id'] = str(row['boliche_id'])
    return jsonify({'ok': True, 'admin': safe(row)})

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    for k in ['admin_id','admin_rol','admin_boliche_id']:
        session.pop(k, None)
    return jsonify({'ok': True})

@app.route('/api/admin/me')
def admin_me():
    admin = require_admin()
    if not admin: return jsonify({'ok': False}), 401
    db = get_db()
    row = q1(db, '''SELECT a.id,a.rol,a.nombre,a.email,a.boliche_id,
                           b.nombre as boliche_nombre,b.slug,b.color_primario,b.color_secundario,b.logo_url
                    FROM admins a JOIN boliches b ON b.id=a.boliche_id
                    WHERE a.id=:id''', {'id': admin['id']})
    return jsonify({'ok': True, 'admin': safe(row)})

# ── AUTH CLIENTE ───────────────────────────────────────────────────────────────

@app.route('/api/auth/registro', methods=['POST'])
def registro():
    body = request.get_json() or {}
    email = body.get('email','').strip().lower()
    password = body.get('password','').strip()
    usuario = body.get('usuario','').strip().lower()
    dni = body.get('dni','').strip()
    if not all([email, password, usuario, dni]):
        return jsonify({'ok': False, 'error': 'Completá todos los campos'}), 400
    if len(password) < 6:
        return jsonify({'ok': False, 'error': 'La contraseña debe tener al menos 6 caracteres'}), 400
    db = get_db()
    if q1(db, 'SELECT id FROM usuarios WHERE dni=:d', {'d': dni}):
        return jsonify({'ok': False, 'error': 'Ya existe una cuenta con ese DNI'}), 400
    if q1(db, 'SELECT id FROM usuarios WHERE usuario=:u', {'u': usuario}):
        return jsonify({'ok': False, 'error': 'Ese usuario ya está tomado'}), 400
    if q1(db, 'SELECT id FROM usuarios WHERE email=:e', {'e': email}):
        return jsonify({'ok': False, 'error': 'Ya existe una cuenta con ese email'}), 400
    nombre = body.get('nombre','').strip()
    genero = body.get('genero','M').strip()
    q(db, 'INSERT INTO usuarios (email,password_hash,usuario,dni,nombre,genero) VALUES (:e,:p,:u,:d,:n,:g)',
      {'e': email, 'p': hp(password), 'u': usuario, 'd': dni, 'n': nombre, 'g': genero})
    # Auto-unir a todos los boliches activos
    nuevo = q1(db, 'SELECT id FROM usuarios WHERE usuario=:u', {'u': usuario})
    if nuevo:
        boliches = q(db, 'SELECT id FROM boliches WHERE activo=TRUE')
        for b in boliches:
            q(db, 'INSERT INTO boliche_usuarios (boliche_id,usuario_id) VALUES (:bid,:uid) ON CONFLICT DO NOTHING',
              {'bid': str(b['id']), 'uid': str(nuevo['id'])})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    body = request.get_json() or {}
    u = body.get('usuario','').strip()
    p = body.get('password','').strip()
    db = get_db()
    row = q1(db, 'SELECT id,usuario,dni,avatar,nombre,genero,nombre_pantalla,email FROM usuarios WHERE (usuario=:u OR email=:e) AND password_hash=:p',
             {'u': u, 'e': u.lower(), 'p': hp(p)})
    if not row: return jsonify({'ok': False, 'error': 'Usuario o contraseña incorrectos'}), 401
    uid = str(row['id'])
    boliches = q(db, '''SELECT b.id,b.nombre,b.slug,b.color_primario,b.color_secundario,b.logo_url,
                               bu.jaggercitos,bu.nivel,bu.nombre_display
                        FROM boliche_usuarios bu JOIN boliches b ON b.id=bu.boliche_id
                        WHERE bu.usuario_id=:uid AND b.activo=TRUE''', {'uid': uid})
    return jsonify({'ok': True, 'usuario': safe(row), 'boliches': [safe(b) for b in boliches]})

@app.route('/api/auth/me')
def auth_me():
    u = request.args.get('usuario','').strip()
    db = get_db()
    row = q1(db, 'SELECT id,usuario,dni,avatar,nombre,genero,nombre_pantalla,email FROM usuarios WHERE usuario=:u', {'u': u})
    if not row: return jsonify({'ok': False})
    uid = str(row['id'])
    boliches = q(db, '''SELECT b.id,b.nombre,b.slug,b.color_primario,b.color_secundario,b.logo_url,
                               bu.jaggercitos,bu.nivel,bu.nombre_display,bu.id as bu_id
                        FROM boliche_usuarios bu JOIN boliches b ON b.id=bu.boliche_id
                        WHERE bu.usuario_id=:uid AND b.activo=TRUE''', {'uid': uid})
    return jsonify({'ok': True, 'usuario': safe(row), 'boliches': [safe(b) for b in boliches]})

# ── BOLICHES (público) ────────────────────────────────────────────────────────

@app.route('/api/boliches')
def get_boliches():
    db = get_db()
    rows = q(db, 'SELECT id,nombre,slug,color_primario,color_secundario,logo_url,descripcion FROM boliches WHERE activo=TRUE ORDER BY nombre')
    return jsonify([safe(r) for r in rows])

@app.route('/api/boliches/<slug>')
def get_boliche(slug):
    db = get_db()
    row = q1(db, 'SELECT id,nombre,slug,color_primario,color_secundario,logo_url,descripcion FROM boliches WHERE slug=:s AND activo=TRUE', {'s': slug})
    if not row: return jsonify({'ok': False, 'error': 'Boliche no encontrado'}), 404
    return jsonify(safe(row))

@app.route('/api/boliches/<slug>/unirse', methods=['POST'])
def unirse_boliche(slug):
    body = request.get_json() or {}
    usuario_q = body.get('usuario','').strip()
    db = get_db()
    u = q1(db, 'SELECT id FROM usuarios WHERE usuario=:u', {'u': usuario_q})
    if not u: return jsonify({'ok': False, 'error': 'Usuario no encontrado'}), 404
    b = q1(db, 'SELECT id FROM boliches WHERE slug=:s AND activo=TRUE', {'s': slug})
    if not b: return jsonify({'ok': False, 'error': 'Boliche no encontrado'}), 404
    existing = q1(db, 'SELECT id FROM boliche_usuarios WHERE boliche_id=:bid AND usuario_id=:uid',
                  {'bid': str(b['id']), 'uid': str(u['id'])})
    if existing: return jsonify({'ok': False, 'error': 'Ya estás en este boliche'}), 400
    q(db, 'INSERT INTO boliche_usuarios (boliche_id,usuario_id) VALUES (:bid,:uid)',
      {'bid': str(b['id']), 'uid': str(u['id'])})
    db.commit()
    return jsonify({'ok': True})

# ── AVATAR ────────────────────────────────────────────────────────────────────

@app.route('/api/usuario/avatar', methods=['POST'])
def avatar():
    body = request.get_json(force=True, silent=True) or {}
    u = (body.get('usuario') or '').strip()
    av = body.get('avatar') or ''
    if not u or not av: return jsonify({'ok': False, 'error': 'Datos incompletos'})
    db = get_db()
    if not q1(db, 'SELECT id FROM usuarios WHERE usuario=:u', {'u': u}):
        return jsonify({'ok': False, 'error': 'Usuario no encontrado'})
    q(db, 'UPDATE usuarios SET avatar=:a WHERE usuario=:u', {'a': av, 'u': u})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/usuario/nombre-pantalla', methods=['POST'])
def nombre_pantalla():
    body = request.get_json() or {}
    u = (body.get('usuario') or '').strip()
    np = (body.get('nombre_pantalla') or '').strip()
    db = get_db()
    if not q1(db, 'SELECT id FROM usuarios WHERE usuario=:u', {'u': u}):
        return jsonify({'ok': False, 'error': 'Usuario no encontrado'})
    q(db, 'UPDATE usuarios SET nombre_pantalla=:n WHERE usuario=:u', {'n': np, 'u': u})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/usuario/password', methods=['POST'])
def cambiar_password():
    body = request.get_json() or {}
    u = (body.get('usuario') or '').strip()
    actual = body.get('actual') or ''
    nueva = body.get('nueva') or ''
    if len(nueva) < 6:
        return jsonify({'ok': False, 'error': 'La contraseña debe tener al menos 6 caracteres'})
    db = get_db()
    row = q1(db, 'SELECT id FROM usuarios WHERE usuario=:u AND password_hash=:p', {'u': u, 'p': hp(actual)})
    if not row:
        return jsonify({'ok': False, 'error': 'La contraseña actual es incorrecta'})
    q(db, 'UPDATE usuarios SET password_hash=:p WHERE usuario=:u', {'p': hp(nueva), 'u': u})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/usuario/email', methods=['POST'])
def cambiar_email():
    body = request.get_json() or {}
    u = (body.get('usuario') or '').strip()
    password = body.get('password') or ''
    nuevo = (body.get('email') or '').strip().lower()
    if not nuevo:
        return jsonify({'ok': False, 'error': 'Ingresá el nuevo email'})
    db = get_db()
    row = q1(db, 'SELECT id FROM usuarios WHERE usuario=:u AND password_hash=:p', {'u': u, 'p': hp(password)})
    if not row:
        return jsonify({'ok': False, 'error': 'Contraseña incorrecta'})
    if q1(db, 'SELECT id FROM usuarios WHERE email=:e AND usuario!=:u', {'e': nuevo, 'u': u}):
        return jsonify({'ok': False, 'error': 'Ese email ya está en uso'})
    q(db, 'UPDATE usuarios SET email=:e WHERE usuario=:u', {'e': nuevo, 'u': u})
    db.commit()
    return jsonify({'ok': True})

# ── POSICIÓN Y HISTORIAL ───────────────────────────────────────────────────────

@app.route('/api/usuario/posicion')
def posicion():
    u = request.args.get('usuario','').strip()
    slug = request.args.get('boliche','').strip()
    db = get_db()
    user = q1(db, 'SELECT id FROM usuarios WHERE usuario=:u', {'u': u})
    if not user: return jsonify({'posicion_noche': None, 'posicion_historico': None})
    b = q1(db, 'SELECT id FROM boliches WHERE slug=:s', {'s': slug})
    if not b: return jsonify({'posicion_noche': None, 'posicion_historico': None})
    bu = q1(db, 'SELECT id FROM boliche_usuarios WHERE usuario_id=:uid AND boliche_id=:bid',
            {'uid': str(user['id']), 'bid': str(b['id'])})
    if not bu: return jsonify({'posicion_noche': None, 'posicion_historico': None})
    buid = str(bu['id'])
    ev = q1(db, 'SELECT id FROM eventos WHERE boliche_id=:bid AND activo=TRUE LIMIT 1', {'bid': str(b['id'])})
    pos_noche = None
    if ev:
        rows = q(db, 'SELECT boliche_usuario_id FROM ranking_noche WHERE evento_id=:eid ORDER BY consumo_pesos DESC', {'eid': str(ev['id'])})
        for i,r in enumerate(rows):
            if str(r['boliche_usuario_id']) == buid: pos_noche=i+1; break
    hist = q(db, '''SELECT boliche_usuario_id FROM ranking_noche rn
                    JOIN eventos e ON e.id=rn.evento_id
                    WHERE e.boliche_id=:bid
                    GROUP BY boliche_usuario_id ORDER BY SUM(consumo_pesos) DESC''', {'bid': str(b['id'])})
    pos_hist = None
    for i,r in enumerate(hist):
        if str(r['boliche_usuario_id']) == buid: pos_hist=i+1; break
    return jsonify({'posicion_noche': pos_noche, 'posicion_historico': pos_hist})

@app.route('/api/usuario/historial')
def historial():
    u = request.args.get('usuario','').strip()
    slug = request.args.get('boliche','').strip()
    db = get_db()
    user = q1(db, 'SELECT id FROM usuarios WHERE usuario=:u', {'u': u})
    if not user: return jsonify([])
    b = q1(db, 'SELECT id FROM boliches WHERE slug=:s', {'s': slug})
    if not b: return jsonify([])
    bu = q1(db, 'SELECT id FROM boliche_usuarios WHERE usuario_id=:uid AND boliche_id=:bid',
            {'uid': str(user['id']), 'bid': str(b['id'])})
    if not bu: return jsonify([])
    rows = q(db, '''SELECT e.fecha::text as fecha, e.nombre as evento_nombre,
                           v.pts_asistencia,v.pts_consumo,v.pts_racha,v.pts_mesa,
                           (v.pts_asistencia+v.pts_consumo+v.pts_racha+v.pts_mesa) as total_pts
                    FROM visitas v JOIN eventos e ON e.id=v.evento_id
                    WHERE v.boliche_usuario_id=:buid ORDER BY e.fecha DESC LIMIT 30''',
             {'buid': str(bu['id'])})
    return jsonify([dict(r) for r in rows])

# ── EVENTOS ────────────────────────────────────────────────────────────────────

@app.route('/api/eventos/activo')
def evento_activo():
    slug = request.args.get('boliche','').strip()
    db = get_db()
    b = q1(db, 'SELECT id FROM boliches WHERE slug=:s', {'s': slug})
    if not b: return jsonify(None)
    row = q1(db, 'SELECT id,fecha::text as fecha,nombre FROM eventos WHERE boliche_id=:bid AND activo=TRUE LIMIT 1',
             {'bid': str(b['id'])})
    return jsonify(safe(row))

@app.route('/api/admin/eventos')
def get_eventos():
    admin = require_admin()
    if not admin: return jsonify({'ok': False}), 401
    db = get_db()
    rows = q(db, 'SELECT id,fecha::text as fecha,nombre,activo,ganador FROM eventos WHERE boliche_id=:bid ORDER BY fecha DESC LIMIT 50',
             {'bid': admin['boliche_id']})
    return jsonify([safe(r) for r in rows])

@app.route('/api/admin/eventos', methods=['POST'])
def crear_evento():
    admin = require_admin()
    if not admin: return jsonify({'ok': False}), 401
    body = request.get_json() or {}
    db = get_db()
    q(db, 'UPDATE eventos SET activo=FALSE WHERE boliche_id=:bid AND activo=TRUE', {'bid': admin['boliche_id']})
    q(db, 'INSERT INTO eventos (boliche_id,fecha,nombre,activo) VALUES (:bid,:f,:n,TRUE)',
      {'bid': admin['boliche_id'], 'f': body.get('fecha'), 'n': body.get('nombre','')})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/admin/eventos/<eid>/cerrar', methods=['POST'])
def cerrar_evento(eid):
    admin = require_admin()
    if not admin: return jsonify({'ok': False}), 401
    db = get_db()
    q(db, 'UPDATE eventos SET activo=FALSE WHERE id=:id AND boliche_id=:bid', {'id': eid, 'bid': admin['boliche_id']})
    db.commit()
    return jsonify({'ok': True})

# ── USUARIOS ADMIN ─────────────────────────────────────────────────────────────

@app.route('/api/admin/usuarios')
def get_usuarios_admin():
    admin = require_admin()
    if not admin: return jsonify({'ok': False}), 401
    db = get_db()
    rows = q(db, '''SELECT u.id,u.usuario,u.dni,bu.nombre_display,bu.jaggercitos,bu.nivel,bu.id as bu_id
                    FROM boliche_usuarios bu JOIN usuarios u ON u.id=bu.usuario_id
                    WHERE bu.boliche_id=:bid ORDER BY bu.jaggercitos DESC''',
             {'bid': admin['boliche_id']})
    return jsonify([safe(r) for r in rows])

@app.route('/api/admin/usuarios/buscar')
def buscar_usuario_admin():
    sq = request.args.get('q','').strip()
    admin = require_admin()
    if not admin: return jsonify({'usuario': None}), 401
    if not sq: return jsonify({'usuario': None})
    db = get_db()
    row = q1(db, '''SELECT u.id,u.usuario,u.dni,bu.nombre_display,bu.jaggercitos,bu.nivel,bu.id as bu_id
                    FROM boliche_usuarios bu JOIN usuarios u ON u.id=bu.usuario_id
                    WHERE bu.boliche_id=:bid AND (u.usuario ILIKE :q OR u.dni=:d) LIMIT 1''',
             {'bid': admin['boliche_id'], 'q': f'%{sq}%', 'd': sq})
    return jsonify({'usuario': safe(row)})

@app.route('/api/admin/usuarios/<bu_id>/puntos', methods=['POST'])
def ajustar_puntos(bu_id):
    admin = require_admin()
    if not admin: return jsonify({'ok': False}), 401
    delta = int((request.get_json() or {}).get('delta', 0))
    db = get_db()
    q(db, 'UPDATE boliche_usuarios SET jaggercitos=GREATEST(0,jaggercitos+:d) WHERE id=:id AND boliche_id=:bid',
      {'d': delta, 'id': bu_id, 'bid': admin['boliche_id']})
    row = q1(db, 'SELECT jaggercitos FROM boliche_usuarios WHERE id=:id', {'id': bu_id})
    nv = nivel(row['jaggercitos'])
    q(db, 'UPDATE boliche_usuarios SET nivel=:n WHERE id=:id', {'n': nv, 'id': bu_id})
    db.commit()
    return jsonify({'ok': True, 'jaggercitos': row['jaggercitos'], 'nivel': nv})

@app.route('/api/admin/usuarios/<bu_id>/nombre-display', methods=['POST'])
def nombre_display(bu_id):
    admin = require_admin(['owner','staff'])
    if not admin: return jsonify({'ok': False}), 401
    nombre = (request.get_json() or {}).get('nombre_display','').strip()
    db = get_db()
    q(db, 'UPDATE boliche_usuarios SET nombre_display=:n WHERE id=:id AND boliche_id=:bid',
      {'n': nombre, 'id': bu_id, 'bid': admin['boliche_id']})
    db.commit()
    return jsonify({'ok': True})

# ── VISITAS ────────────────────────────────────────────────────────────────────

@app.route('/api/admin/visitas', methods=['POST'])
def registrar_visita():
    admin = require_admin()
    if not admin: return jsonify({'ok': False}), 401
    body = request.get_json() or {}
    bu_id = body.get('bu_id')
    consumo = int(body.get('consumo_pesos', 0))
    origen = body.get('origen', 'caja')
    bid = admin['boliche_id']
    db = get_db()
    ev = q1(db, 'SELECT id FROM eventos WHERE boliche_id=:bid AND activo=TRUE LIMIT 1', {'bid': bid})
    if not ev: return jsonify({'ok': False, 'error': 'No hay evento activo. Abrí una noche primero.'}), 400
    c = cfg(bid)
    racha = len(q(db, 'SELECT id FROM visitas WHERE boliche_usuario_id=:buid', {'buid': bu_id}))
    pa = c.get('pts_asistencia', 20)
    pm = c.get('pts_mesa', 30) if origen == 'mesa' else 0
    pc = (consumo // 1000) * c.get('pts_por_mil', 1)
    pr = c.get('pts_racha_mes',150) if racha>=4 else (c.get('pts_racha_3',50) if racha>=3 else 0)
    total = pa + pm + pc + pr
    eid = str(ev['id'])
    q(db, '''INSERT INTO visitas (boliche_usuario_id,evento_id,pts_asistencia,pts_consumo,pts_racha,pts_mesa,consumo_pesos,es_mesa,origen)
        VALUES (:buid,:eid,:pa,:pc,:pr,:pm,:cp,:em,:or)''',
      {'buid': bu_id,'eid': eid,'pa': pa,'pc': pc,'pr': pr,'pm': pm,'cp': consumo,'em': origen=='mesa','or': origen})
    ex = q1(db, 'SELECT id FROM ranking_noche WHERE boliche_usuario_id=:buid AND evento_id=:eid', {'buid': bu_id,'eid': eid})
    if ex:
        q(db, 'UPDATE ranking_noche SET consumo_pesos=consumo_pesos+:cp WHERE id=:id', {'cp': consumo,'id': str(ex['id'])})
    else:
        q(db, 'INSERT INTO ranking_noche (boliche_usuario_id,evento_id,consumo_pesos) VALUES (:buid,:eid,:cp)',
          {'buid': bu_id,'eid': eid,'cp': consumo})
    q(db, 'UPDATE boliche_usuarios SET jaggercitos=jaggercitos+:t WHERE id=:id', {'t': total,'id': bu_id})
    row = q1(db, 'SELECT jaggercitos FROM boliche_usuarios WHERE id=:id', {'id': bu_id})
    nv = nivel(row['jaggercitos'])
    q(db, 'UPDATE boliche_usuarios SET nivel=:n WHERE id=:id', {'n': nv,'id': bu_id})
    db.commit()
    return jsonify({'ok': True,'pts_sumados': total,'jaggercitos': row['jaggercitos'],'nivel': nv})

# ── RANKING ────────────────────────────────────────────────────────────────────

@app.route('/api/ranking/noche')
def ranking_noche():
    slug = request.args.get('boliche','').strip()
    db = get_db()
    b = q1(db, 'SELECT id FROM boliches WHERE slug=:s', {'s': slug})
    if not b: return jsonify([])
    ev = q1(db, 'SELECT id FROM eventos WHERE boliche_id=:bid AND activo=TRUE LIMIT 1', {'bid': str(b['id'])})
    if not ev: return jsonify([])
    rows = q(db, '''SELECT rn.consumo_pesos,rn.gano_botella,rn.pts_bonus,
                           COALESCE(bu.nombre_display, u.usuario) as nombre
                    FROM ranking_noche rn
                    JOIN boliche_usuarios bu ON bu.id=rn.boliche_usuario_id
                    JOIN usuarios u ON u.id=bu.usuario_id
                    WHERE rn.evento_id=:eid ORDER BY rn.consumo_pesos DESC''', {'eid': str(ev['id'])})
    return jsonify([dict(r) for r in rows])

@app.route('/api/ranking/historico')
def ranking_historico():
    slug = request.args.get('boliche','').strip()
    periodo = request.args.get('periodo','historico').strip()
    db = get_db()
    b = q1(db, 'SELECT id FROM boliches WHERE slug=:s', {'s': slug})
    if not b: return jsonify([])
    from datetime import date, timedelta
    hoy = date.today()
    filtro_fecha = ''
    if periodo == 'mensual':
        desde = hoy.replace(day=1).isoformat()
        filtro_fecha = f"AND e.fecha >= '{desde}'"
    elif periodo == 'trimestral':
        mes = ((hoy.month - 1) // 3) * 3 + 1
        desde = hoy.replace(month=mes, day=1).isoformat()
        filtro_fecha = f"AND e.fecha >= '{desde}'"
    elif periodo == 'anual':
        desde = hoy.replace(month=1, day=1).isoformat()
        filtro_fecha = f"AND e.fecha >= '{desde}'"
    rows = q(db, f'''SELECT COALESCE(bu.nombre_display,u.usuario) as nombre,
                           SUM(rn.consumo_pesos) as total_consumo, COUNT(rn.id) as noches
                    FROM ranking_noche rn
                    JOIN boliche_usuarios bu ON bu.id=rn.boliche_usuario_id
                    JOIN usuarios u ON u.id=bu.usuario_id
                    JOIN eventos e ON e.id=rn.evento_id
                    WHERE e.boliche_id=:bid {filtro_fecha}
                    GROUP BY bu.id,bu.nombre_display,u.usuario
                    ORDER BY total_consumo DESC LIMIT 50''', {'bid': str(b['id'])})
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/ranking/declarar-ganador', methods=['POST'])
def declarar_ganador():
    admin = require_admin()
    if not admin: return jsonify({'ok': False}), 401
    bid = admin['boliche_id']
    db = get_db()
    ev = q1(db, 'SELECT id FROM eventos WHERE boliche_id=:bid AND activo=TRUE LIMIT 1', {'bid': bid})
    if not ev: return jsonify({'ok': False,'error': 'No hay evento activo'})
    c = cfg(bid)
    top = q(db, '''SELECT rn.id,rn.boliche_usuario_id,COALESCE(bu.nombre_display,u.usuario) as nombre
                   FROM ranking_noche rn
                   JOIN boliche_usuarios bu ON bu.id=rn.boliche_usuario_id
                   JOIN usuarios u ON u.id=bu.usuario_id
                   WHERE rn.evento_id=:eid ORDER BY rn.consumo_pesos DESC LIMIT 3''', {'eid': str(ev['id'])})
    if not top: return jsonify({'ok': False,'error': 'Sin participantes'})
    bonuses = [c.get('bonus_ganador',300), c.get('bonus_segundo',150), c.get('bonus_tercero',75)]
    for i,row in enumerate(top):
        q(db, 'UPDATE ranking_noche SET posicion=:p,pts_bonus=:b,gano_botella=:g WHERE id=:id',
          {'p': i+1,'b': bonuses[i],'g': i==0,'id': str(row['id'])})
        q(db, 'UPDATE boliche_usuarios SET jaggercitos=jaggercitos+:b WHERE id=:id',
          {'b': bonuses[i],'id': str(row['boliche_usuario_id'])})
    q(db, 'UPDATE eventos SET ganador=:g WHERE id=:id', {'g': top[0]['nombre'],'id': str(ev['id'])})
    db.commit()
    return jsonify({'ok': True,'ganador': top[0]['nombre']})

# ── PREMIOS ────────────────────────────────────────────────────────────────────

@app.route('/api/premios')
def get_premios():
    slug = request.args.get('boliche','').strip()
    db = get_db()
    b = q1(db, 'SELECT id FROM boliches WHERE slug=:s', {'s': slug})
    if not b: return jsonify([])
    rows = q(db, 'SELECT id,nombre,categoria,precio_pesos,pts_necesarios,activo FROM premios WHERE boliche_id=:bid ORDER BY categoria,precio_pesos',
             {'bid': str(b['id'])})
    return jsonify([safe(r) for r in rows])

@app.route('/api/admin/premios')
def get_premios_admin():
    admin = require_admin()
    if not admin: return jsonify({'ok': False}), 401
    db = get_db()
    rows = q(db, 'SELECT id,nombre,categoria,precio_pesos,pts_necesarios,activo FROM premios WHERE boliche_id=:bid ORDER BY categoria,precio_pesos',
             {'bid': admin['boliche_id']})
    return jsonify([safe(r) for r in rows])

@app.route('/api/admin/premios', methods=['POST'])
def agregar_premio():
    admin = require_admin(['owner'])
    if not admin: return jsonify({'ok': False}), 401
    body = request.get_json() or {}
    db = get_db()
    q(db, 'INSERT INTO premios (boliche_id,nombre,categoria,precio_pesos,pts_necesarios) VALUES (:bid,:n,:c,:p,:pts)',
      {'bid': admin['boliche_id'],'n': body['nombre'],'c': body.get('categoria',''),
       'p': int(body.get('precio_pesos',0)),'pts': int(body.get('pts_necesarios',0))})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/admin/premios/<pid>', methods=['PUT'])
def actualizar_premio(pid):
    admin = require_admin(['owner'])
    if not admin: return jsonify({'ok': False}), 401
    body = request.get_json() or {}
    db = get_db()
    if 'pts_necesarios' in body:
        q(db, 'UPDATE premios SET pts_necesarios=:p WHERE id=:id AND boliche_id=:bid',
          {'p': int(body['pts_necesarios']),'id': pid,'bid': admin['boliche_id']})
    if 'activo' in body:
        q(db, 'UPDATE premios SET activo=:a WHERE id=:id AND boliche_id=:bid',
          {'a': body['activo'],'id': pid,'bid': admin['boliche_id']})
    db.commit()
    return jsonify({'ok': True})

# ── CANJES ─────────────────────────────────────────────────────────────────────

@app.route('/api/canjes', methods=['POST'])
def crear_canje():
    body = request.get_json() or {}
    usuario_q = body.get('usuario','').strip()
    slug = body.get('boliche','').strip()
    premio_id = body.get('premio_id')
    db = get_db()
    u = q1(db, 'SELECT id FROM usuarios WHERE usuario=:u', {'u': usuario_q})
    if not u: return jsonify({'ok': False,'error': 'Usuario no encontrado'})
    b = q1(db, 'SELECT id FROM boliches WHERE slug=:s', {'s': slug})
    if not b: return jsonify({'ok': False,'error': 'Boliche no encontrado'})
    bu = q1(db, 'SELECT id,jaggercitos FROM boliche_usuarios WHERE usuario_id=:uid AND boliche_id=:bid',
            {'uid': str(u['id']),'bid': str(b['id'])})
    if not bu: return jsonify({'ok': False,'error': 'No estás en este boliche'})
    p = q1(db, 'SELECT id,pts_necesarios,nombre FROM premios WHERE id=:id AND boliche_id=:bid AND activo=TRUE',
           {'id': str(premio_id),'bid': str(b['id'])})
    if not p: return jsonify({'ok': False,'error': 'Premio no disponible'})
    if bu['jaggercitos'] < p['pts_necesarios']:
        return jsonify({'ok': False,'error': 'No tenés suficientes jaggercitos'})
    codigo = secrets.token_hex(4).upper()
    q(db, 'INSERT INTO canjes (boliche_usuario_id,premio_id,codigo_unico) VALUES (:buid,:pid,:c)',
      {'buid': str(bu['id']),'pid': str(p['id']),'c': codigo})
    q(db, 'UPDATE boliche_usuarios SET jaggercitos=jaggercitos-:p WHERE id=:id',
      {'p': p['pts_necesarios'],'id': str(bu['id'])})
    db.commit()
    return jsonify({'ok': True,'codigo': codigo})

# ── CONFIG ─────────────────────────────────────────────────────────────────────

@app.route('/api/admin/config')
def get_config_api():
    admin = require_admin()
    if not admin: return jsonify({'ok': False}), 401
    db = get_db()
    rows = q(db, 'SELECT clave,valor,descripcion FROM config_puntos WHERE boliche_id=:bid ORDER BY clave',
             {'bid': admin['boliche_id']})
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/canjes')
def admin_canjes():
    admin = require_admin()
    if not admin: return jsonify({'ok': False}), 401
    db = get_db()
    pend = q(db, '''SELECT c.codigo_unico, c.created_at::text as fecha, p.nombre as premio,
                           u.usuario, COALESCE(u.nombre,'') as nombre
                    FROM canjes c JOIN premios p ON p.id=c.premio_id
                    JOIN boliche_usuarios bu ON bu.id=c.boliche_usuario_id
                    JOIN usuarios u ON u.id=bu.usuario_id
                    WHERE bu.boliche_id=:bid AND c.usado=FALSE
                    ORDER BY c.created_at DESC LIMIT 100''', {'bid': admin['boliche_id']})
    usados = q(db, '''SELECT c.codigo_unico, c.usado_at::text as fecha, p.nombre as premio,
                             u.usuario, COALESCE(u.nombre,'') as nombre
                      FROM canjes c JOIN premios p ON p.id=c.premio_id
                      JOIN boliche_usuarios bu ON bu.id=c.boliche_usuario_id
                      JOIN usuarios u ON u.id=bu.usuario_id
                      WHERE bu.boliche_id=:bid AND c.usado=TRUE AND c.usado_at::date=CURRENT_DATE
                      ORDER BY c.usado_at DESC LIMIT 100''', {'bid': admin['boliche_id']})
    return jsonify({'ok': True, 'pendientes': [safe(r) for r in pend], 'usados': [safe(r) for r in usados]})

@app.route('/api/admin/canjes/<codigo>/entregar', methods=['POST'])
def admin_entregar_canje(codigo):
    admin = require_admin()
    if not admin: return jsonify({'ok': False}), 401
    db = get_db()
    row = q1(db, '''SELECT c.id, c.usado FROM canjes c
                    JOIN boliche_usuarios bu ON bu.id=c.boliche_usuario_id
                    WHERE c.codigo_unico=:c AND bu.boliche_id=:bid''',
             {'c': codigo, 'bid': admin['boliche_id']})
    if not row: return jsonify({'ok': False, 'error': 'Canje no encontrado'})
    if row['usado']: return jsonify({'ok': False, 'error': 'Ya fue entregado'})
    q(db, 'UPDATE canjes SET usado=TRUE, usado_at=NOW() WHERE id=:id', {'id': str(row['id'])})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/admin/config/<clave>', methods=['PUT'])
def update_config(clave):
    admin = require_admin(['owner'])
    if not admin: return jsonify({'ok': False}), 401
    body = request.get_json() or {}
    db = get_db()
    q(db, 'UPDATE config_puntos SET valor=:v WHERE clave=:c AND boliche_id=:bid',
      {'v': int(body['valor']),'c': clave,'bid': admin['boliche_id']})
    db.commit()
    return jsonify({'ok': True})

# ── SUPER ADMIN ────────────────────────────────────────────────────────────────

@app.route('/api/superadmin/boliches')
def sa_boliches():
    if not require_super(): return jsonify({'ok': False}), 401
    db = get_db()
    rows = q(db, 'SELECT id,nombre,slug,activo,plan,created_at::text FROM boliches ORDER BY created_at DESC')
    return jsonify([safe(r) for r in rows])

@app.route('/api/superadmin/boliches', methods=['POST'])
def sa_crear_boliche():
    if not require_super(): return jsonify({'ok': False}), 401
    body = request.get_json() or {}
    db = get_db()
    q(db, '''INSERT INTO boliches (nombre,slug,color_primario,color_secundario,descripcion)
             VALUES (:n,:s,:c1,:c2,:d)''',
      {'n': body['nombre'],'s': body['slug'],'c1': body.get('color_primario','#d4a829'),
       'c2': body.get('color_secundario','#111111'),'d': body.get('descripcion','')})
    bid = q1(db, 'SELECT id FROM boliches WHERE slug=:s', {'s': body['slug']})
    configs = [
        ('pts_asistencia',20,'Jaggercitos por ir'),('pts_mesa',30,'Bonus por mesa'),
        ('pts_racha_3',50,'Bonus 3 semanas'),('pts_racha_mes',150,'Bonus 1 mes'),
        ('pts_por_mil',1,'Jaggercitos por $1.000'),('bonus_ganador',300,'Bonus ganador'),
        ('bonus_segundo',150,'Bonus segundo'),('bonus_tercero',75,'Bonus tercero'),
    ]
    for clave,valor,desc in configs:
        q(db, 'INSERT INTO config_puntos (boliche_id,clave,valor,descripcion) VALUES (:bid,:c,:v,:d)',
          {'bid': str(bid['id']),'c': clave,'v': valor,'d': desc})
    if body.get('admin_email') and body.get('admin_password'):
        q(db, 'INSERT INTO admins (boliche_id,email,password_hash,nombre,rol) VALUES (:bid,:e,:p,:n,:r)',
          {'bid': str(bid['id']),'e': body['admin_email'],'p': hp(body['admin_password']),
           'n': body.get('admin_nombre','Owner'),'r': 'owner'})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/superadmin/boliches/<bid>/toggle', methods=['POST'])
def sa_toggle_boliche(bid):
    if not require_super(): return jsonify({'ok': False}), 401
    db = get_db()
    row = q1(db, 'SELECT activo FROM boliches WHERE id=:id', {'id': bid})
    if not row: return jsonify({'ok': False}), 404
    q(db, 'UPDATE boliches SET activo=:a WHERE id=:id', {'a': not row['activo'],'id': bid})
    db.commit()
    return jsonify({'ok': True,'activo': not row['activo']})

# ── EXTERNAL API (ranking VIP → clubpass) ─────────────────────────────────────

@app.route('/api/external/registrar', methods=['POST'])
def external_registrar():
    if request.headers.get('X-API-Key') != EXTERNAL_API_KEY:
        return jsonify({'ok': False}), 403
    body = request.get_json() or {}
    usuario_q = body.get('usuario','').strip()
    slug = body.get('boliche','club-jagger')
    consumo = int(body.get('consumo_pesos', 0))
    origen = body.get('origen', 'caja')
    db = get_db()
    u = q1(db, 'SELECT id FROM usuarios WHERE usuario ILIKE :u OR dni=:d LIMIT 1', {'u': usuario_q,'d': usuario_q})
    if not u: return jsonify({'ok': False,'error': 'Usuario no encontrado'})
    b = q1(db, 'SELECT id FROM boliches WHERE slug=:s AND activo=TRUE', {'s': slug})
    if not b: return jsonify({'ok': False,'error': 'Boliche no encontrado'})
    bu = q1(db, 'SELECT id FROM boliche_usuarios WHERE usuario_id=:uid AND boliche_id=:bid',
            {'uid': str(u['id']),'bid': str(b['id'])})
    if not bu: return jsonify({'ok': False,'error': 'Usuario no está en este boliche'})
    ev = q1(db, 'SELECT id FROM eventos WHERE boliche_id=:bid AND activo=TRUE LIMIT 1', {'bid': str(b['id'])})
    if not ev:
        from datetime import date
        fecha_hoy = date.today().isoformat()
        q(db, 'INSERT INTO eventos (boliche_id,fecha,nombre,activo) VALUES (:bid,:f,:n,TRUE)',
          {'bid': str(b['id']), 'f': fecha_hoy, 'n': 'Noche '+fecha_hoy})
        ev = q1(db, 'SELECT id FROM eventos WHERE boliche_id=:bid AND activo=TRUE LIMIT 1', {'bid': str(b['id'])})
        db.commit()
    c = cfg(str(b['id']))
    pc = (consumo // 1000) * c.get('pts_por_mil', 1)
    pm = c.get('pts_mesa',30) if origen=='mesa' else 0
    total = pc + pm
    buid, eid = str(bu['id']), str(ev['id'])
    q(db, 'INSERT INTO visitas (boliche_usuario_id,evento_id,pts_consumo,pts_mesa,consumo_pesos,es_mesa,origen) VALUES (:buid,:eid,:pc,:pm,:cp,:em,:or)',
      {'buid': buid,'eid': eid,'pc': pc,'pm': pm,'cp': consumo,'em': origen=='mesa','or': origen})
    ex = q1(db, 'SELECT id FROM ranking_noche WHERE boliche_usuario_id=:buid AND evento_id=:eid', {'buid': buid,'eid': eid})
    if ex:
        q(db, 'UPDATE ranking_noche SET consumo_pesos=consumo_pesos+:cp WHERE id=:id', {'cp': consumo,'id': str(ex['id'])})
    else:
        q(db, 'INSERT INTO ranking_noche (boliche_usuario_id,evento_id,consumo_pesos) VALUES (:buid,:eid,:cp)', {'buid': buid,'eid': eid,'cp': consumo})
    q(db, 'UPDATE boliche_usuarios SET jaggercitos=jaggercitos+:t WHERE id=:id', {'t': total,'id': buid})
    db.commit()
    return jsonify({'ok': True,'pts_sumados': total})

@app.route('/api/external/cerrar-noche', methods=['POST'])
def external_cerrar_noche():
    if request.headers.get('X-API-Key') != EXTERNAL_API_KEY:
        return jsonify({'ok': False}), 403
    body = request.get_json() or {}
    slug = body.get('boliche', 'club-jagger')
    db = get_db()
    b = q1(db, 'SELECT id FROM boliches WHERE slug=:s', {'s': slug})
    if not b: return jsonify({'ok': False, 'error': 'Boliche no encontrado'})
    q(db, 'UPDATE eventos SET activo=FALSE WHERE boliche_id=:bid AND activo=TRUE', {'bid': str(b['id'])})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/external/canjes', methods=['GET'])
def external_canjes():
    if request.headers.get('X-API-Key') != EXTERNAL_API_KEY:
        return jsonify({'ok': False}), 403
    usuario_q = request.args.get('usuario', '').strip()
    slug = request.args.get('boliche', 'club-jagger')
    db = get_db()
    u = q1(db, 'SELECT id FROM usuarios WHERE usuario ILIKE :u OR dni=:d LIMIT 1', {'u': usuario_q, 'd': usuario_q})
    if not u: return jsonify({'ok': False, 'error': 'Usuario no encontrado'})
    b = q1(db, 'SELECT id FROM boliches WHERE slug=:s', {'s': slug})
    if not b: return jsonify({'ok': False, 'error': 'Boliche no encontrado'})
    bu = q1(db, 'SELECT id FROM boliche_usuarios WHERE usuario_id=:uid AND boliche_id=:bid',
            {'uid': str(u['id']), 'bid': str(b['id'])})
    if not bu: return jsonify({'ok': True, 'canjes': []})
    rows = q(db, '''SELECT c.id, c.codigo_unico, c.usado, c.created_at::text as fecha, p.nombre as premio
                    FROM canjes c JOIN premios p ON p.id=c.premio_id
                    WHERE c.boliche_usuario_id=:buid
                    ORDER BY c.usado ASC, c.created_at DESC LIMIT 30''', {'buid': str(bu['id'])})
    return jsonify({'ok': True, 'canjes': [safe(r) for r in rows]})

@app.route('/api/external/canjes/<codigo>/entregar', methods=['POST'])
def external_entregar_canje(codigo):
    if request.headers.get('X-API-Key') != EXTERNAL_API_KEY:
        return jsonify({'ok': False}), 403
    db = get_db()
    row = q1(db, 'SELECT id, usado FROM canjes WHERE codigo_unico=:c', {'c': codigo})
    if not row: return jsonify({'ok': False, 'error': 'Canje no encontrado'})
    if row['usado']: return jsonify({'ok': False, 'error': 'Este canje ya fue entregado'})
    q(db, 'UPDATE canjes SET usado=TRUE, usado_at=NOW() WHERE id=:id', {'id': str(row['id'])})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/external/canjes-pendientes', methods=['GET'])
def external_canjes_pendientes():
    if request.headers.get('X-API-Key') != EXTERNAL_API_KEY:
        return jsonify({'ok': False}), 403
    slug = request.args.get('boliche', 'club-jagger')
    db = get_db()
    b = q1(db, 'SELECT id FROM boliches WHERE slug=:s', {'s': slug})
    if not b: return jsonify({'ok': False, 'error': 'Boliche no encontrado'})
    rows = q(db, '''SELECT c.codigo_unico, c.created_at::text as fecha, p.nombre as premio,
                           u.usuario, COALESCE(u.nombre,'') as nombre
                    FROM canjes c
                    JOIN premios p ON p.id=c.premio_id
                    JOIN boliche_usuarios bu ON bu.id=c.boliche_usuario_id
                    JOIN usuarios u ON u.id=bu.usuario_id
                    WHERE bu.boliche_id=:bid AND c.usado=FALSE
                    ORDER BY c.created_at DESC LIMIT 100''', {'bid': str(b['id'])})
    return jsonify({'ok': True, 'canjes': [safe(r) for r in rows]})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001)), debug=False)

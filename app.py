from flask import Flask, jsonify, request, render_template_string, session
import os, hashlib, secrets
from datetime import datetime, timedelta
from db import get_db, init_db, close_db, execute, execute_one

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'jaggercitos_secret_2024')
app.permanent_session_lifetime = timedelta(hours=12)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
app.teardown_appcontext(close_db)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'jagger2024')
EXTERNAL_API_KEY = os.environ.get('EXTERNAL_API_KEY', 'jaggercitos_ext_key')

with app.app_context():
    init_db()

def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()

def get_config():
    db = get_db()
    rows = execute(db, 'SELECT clave, valor FROM config_puntos')
    return {r['clave']: r['valor'] for r in rows}

def calcular_nivel(puntos):
    if puntos >= 3000: return 4
    if puntos >= 1000: return 3
    if puntos >= 300:  return 2
    return 1

def calcular_racha(usuario_id):
    db = get_db()
    rows = execute(db, 'SELECT id FROM visitas WHERE usuario_id = :uid', {'uid': usuario_id})
    return len(rows)

def require_admin():
    return session.get('admin')

def safe_dict(row):
    if row is None: return None
    return {k: str(v) if hasattr(v, 'hex') else v for k, v in dict(row).items()}

ADMIN_HTML = open(os.path.join(os.path.dirname(__file__), 'admin.html'), encoding='utf-8').read() if os.path.exists(os.path.join(os.path.dirname(__file__), 'admin.html')) else "<h1>Admin</h1>"

# ── ADMIN PAGE ─────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template_string(ADMIN_HTML)

# ── AUTH ───────────────────────────────────────────────────────────────────────

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    body = request.get_json() or {}
    if body.get('password') == ADMIN_PASSWORD:
        session.permanent = True
        session['admin'] = True
        return jsonify({'ok': True})
    return jsonify({'ok': False}), 401

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('admin', None)
    return jsonify({'ok': True})

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    body = request.get_json() or {}
    usuario_q = body.get('usuario','').strip()
    password = body.get('password','').strip()
    db = get_db()
    row = execute_one(db,
        'SELECT id,usuario,nombre_display,dni,puntos_total,nivel,avatar FROM usuarios WHERE (usuario=:u OR email=:e) AND password_hash=:p',
        {'u': usuario_q, 'e': usuario_q.lower(), 'p': hash_password(password)}
    )
    if not row: return jsonify({'ok': False, 'error': 'Usuario o contraseña incorrectos'}), 401
    return jsonify({'ok': True, 'usuario': safe_dict(row)})

@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    usuario_q = request.args.get('usuario','').strip()
    db = get_db()
    row = execute_one(db,
        'SELECT id,usuario,nombre_display,dni,puntos_total,nivel,avatar FROM usuarios WHERE usuario=:u',
        {'u': usuario_q}
    )
    if not row: return jsonify({'ok': False})
    return jsonify({'ok': True, 'usuario': safe_dict(row)})

# ── USUARIOS ───────────────────────────────────────────────────────────────────

@app.route('/api/usuarios/registro', methods=['POST'])
def registro_usuario():
    body = request.get_json() or {}
    email = body.get('email','').strip().lower()
    password = body.get('password','').strip()
    usuario = body.get('usuario','').strip().lower()
    dni = body.get('dni','').strip()
    if not all([email, password, usuario, dni]):
        return jsonify({'ok': False, 'error': 'Completá todos los campos'}), 400
    db = get_db()
    if execute_one(db, 'SELECT id FROM usuarios WHERE dni=:d', {'d': dni}):
        return jsonify({'ok': False, 'error': 'Ya existe una cuenta con ese DNI'}), 400
    if execute_one(db, 'SELECT id FROM usuarios WHERE usuario=:u', {'u': usuario}):
        return jsonify({'ok': False, 'error': 'Ese usuario ya está tomado'}), 400
    if execute_one(db, 'SELECT id FROM usuarios WHERE email=:e', {'e': email}):
        return jsonify({'ok': False, 'error': 'Ya existe una cuenta con ese email'}), 400
    execute(db, 'INSERT INTO usuarios (email,password_hash,usuario,dni) VALUES (:e,:p,:u,:d)',
            {'e': email, 'p': hash_password(password), 'u': usuario, 'd': dni})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/usuarios', methods=['GET'])
def get_usuarios():
    if not require_admin(): return jsonify({'ok': False}), 401
    db = get_db()
    rows = execute(db, 'SELECT id,usuario,nombre_display,dni,puntos_total,nivel FROM usuarios ORDER BY puntos_total DESC')
    return jsonify([safe_dict(r) for r in rows])

@app.route('/api/usuarios/buscar', methods=['GET'])
def buscar_usuario():
    q = request.args.get('q','').strip()
    if not q: return jsonify({'usuario': None})
    db = get_db()
    row = execute_one(db,
        'SELECT id,usuario,nombre_display,dni,puntos_total,nivel FROM usuarios WHERE usuario ILIKE :q OR dni=:d LIMIT 1',
        {'q': f'%{q}%', 'd': q}
    )
    return jsonify({'usuario': safe_dict(row) if row else None})

@app.route('/api/usuarios/<usuario_id>/puntos', methods=['POST'])
def ajustar_puntos(usuario_id):
    if not require_admin(): return jsonify({'ok': False}), 401
    body = request.get_json() or {}
    delta = int(body.get('delta', 0))
    db = get_db()
    execute(db, 'UPDATE usuarios SET puntos_total=GREATEST(0,puntos_total+:d) WHERE id=:id', {'d': delta, 'id': usuario_id})
    row = execute_one(db, 'SELECT puntos_total FROM usuarios WHERE id=:id', {'id': usuario_id})
    nivel = calcular_nivel(row['puntos_total'])
    execute(db, 'UPDATE usuarios SET nivel=:n WHERE id=:id', {'n': nivel, 'id': usuario_id})
    db.commit()
    return jsonify({'ok': True, 'puntos_total': row['puntos_total'], 'nivel': nivel})

@app.route('/api/usuarios/<usuario_id>/nombre-display', methods=['POST'])
def cambiar_nombre_display(usuario_id):
    if not require_admin(): return jsonify({'ok': False}), 401
    body = request.get_json() or {}
    nombre = body.get('nombre_display','').strip()
    db = get_db()
    execute(db, 'UPDATE usuarios SET nombre_display=:n WHERE id=:id', {'n': nombre, 'id': usuario_id})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/usuario/avatar', methods=['POST'])
def guardar_avatar():
    body = request.get_json(force=True, silent=True) or {}
    usuario_q = (body.get('usuario') or '').strip()
    avatar = body.get('avatar') or ''
    if not usuario_q or not avatar: return jsonify({'ok': False, 'error': 'Datos incompletos'})
    db = get_db()
    result = execute_one(db, 'SELECT id FROM usuarios WHERE usuario=:u', {'u': usuario_q})
    if not result: return jsonify({'ok': False, 'error': 'Usuario no encontrado'})
    execute(db, 'UPDATE usuarios SET avatar=:a WHERE usuario=:u', {'a': avatar, 'u': usuario_q})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/usuario/posicion', methods=['GET'])
def usuario_posicion():
    usuario_q = request.args.get('usuario','').strip()
    db = get_db()
    u = execute_one(db, 'SELECT id FROM usuarios WHERE usuario=:u', {'u': usuario_q})
    if not u: return jsonify({'posicion_noche': None, 'posicion_historico': None})
    evento = execute_one(db, 'SELECT id FROM eventos WHERE activo=TRUE LIMIT 1')
    pos_noche = None
    if evento:
        rows = execute(db, 'SELECT usuario_id FROM ranking_noche WHERE evento_id=:e ORDER BY consumo_pesos DESC', {'e': str(evento['id'])})
        for i, r in enumerate(rows):
            if str(r['usuario_id']) == str(u['id']): pos_noche = i+1; break
    hist = execute(db, 'SELECT usuario_id FROM ranking_noche GROUP BY usuario_id ORDER BY SUM(consumo_pesos) DESC')
    pos_hist = None
    for i, r in enumerate(hist):
        if str(r['usuario_id']) == str(u['id']): pos_hist = i+1; break
    return jsonify({'posicion_noche': pos_noche, 'posicion_historico': pos_hist})

@app.route('/api/usuario/historial', methods=['GET'])
def usuario_historial():
    usuario_q = request.args.get('usuario','').strip()
    db = get_db()
    u = execute_one(db, 'SELECT id FROM usuarios WHERE usuario=:u', {'u': usuario_q})
    if not u: return jsonify([])
    rows = execute(db, '''
        SELECT v.puntos_asistencia, v.puntos_consumo, v.puntos_racha, v.puntos_mesa,
               e.fecha::text as fecha, e.nombre as evento_nombre,
               (v.puntos_asistencia+v.puntos_consumo+v.puntos_racha+v.puntos_mesa) as total_pts
        FROM visitas v JOIN eventos e ON e.id=v.evento_id
        WHERE v.usuario_id=:uid ORDER BY e.fecha DESC LIMIT 30
    ''', {'uid': str(u['id'])})
    return jsonify([dict(r) for r in rows])

# ── VISITAS ────────────────────────────────────────────────────────────────────

@app.route('/api/visitas', methods=['POST'])
def registrar_visita():
    if not require_admin(): return jsonify({'ok': False}), 401
    body = request.get_json() or {}
    usuario_id = body.get('usuario_id')
    consumo_pesos = int(body.get('consumo_pesos', 0))
    origen = body.get('origen', 'caja')
    db = get_db()
    evento = execute_one(db, 'SELECT id FROM eventos WHERE activo=TRUE LIMIT 1')
    if not evento: return jsonify({'ok': False, 'error': 'No hay evento activo. Abrí una noche primero.'}), 400
    config = get_config()
    racha = calcular_racha(usuario_id)
    pts_asistencia = config.get('puntos_asistencia', 20)
    pts_mesa = config.get('puntos_mesa', 30) if origen == 'mesa' else 0
    pts_consumo = (consumo_pesos // 1000) * config.get('puntos_por_mil_pesos', 1)
    pts_racha = 0
    if racha >= 4: pts_racha = config.get('puntos_racha_mes', 150)
    elif racha >= 3: pts_racha = config.get('puntos_racha_3', 50)
    total_pts = pts_asistencia + pts_mesa + pts_consumo + pts_racha
    execute(db, '''INSERT INTO visitas (usuario_id,evento_id,puntos_asistencia,puntos_consumo,puntos_racha,puntos_mesa,consumo_pesos,es_mesa,origen)
        VALUES (:uid,:eid,:pa,:pc,:pr,:pm,:cp,:em,:or)''',
        {'uid': usuario_id, 'eid': str(evento['id']), 'pa': pts_asistencia, 'pc': pts_consumo,
         'pr': pts_racha, 'pm': pts_mesa, 'cp': consumo_pesos, 'em': origen=='mesa', 'or': origen})
    existing = execute_one(db, 'SELECT id FROM ranking_noche WHERE usuario_id=:uid AND evento_id=:eid',
                          {'uid': usuario_id, 'eid': str(evento['id'])})
    if existing:
        execute(db, 'UPDATE ranking_noche SET consumo_pesos=consumo_pesos+:cp WHERE id=:id',
               {'cp': consumo_pesos, 'id': str(existing['id'])})
    else:
        execute(db, 'INSERT INTO ranking_noche (usuario_id,evento_id,consumo_pesos) VALUES (:uid,:eid,:cp)',
               {'uid': usuario_id, 'eid': str(evento['id']), 'cp': consumo_pesos})
    execute(db, 'UPDATE usuarios SET puntos_total=puntos_total+:pts WHERE id=:id', {'pts': total_pts, 'id': usuario_id})
    row = execute_one(db, 'SELECT puntos_total FROM usuarios WHERE id=:id', {'id': usuario_id})
    nivel = calcular_nivel(row['puntos_total'])
    execute(db, 'UPDATE usuarios SET nivel=:n WHERE id=:id', {'n': nivel, 'id': usuario_id})
    db.commit()
    return jsonify({'ok': True, 'puntos_sumados': total_pts, 'puntos_total': row['puntos_total'], 'nivel': nivel})

# ── EVENTOS ────────────────────────────────────────────────────────────────────

@app.route('/api/eventos', methods=['GET'])
def get_eventos():
    db = get_db()
    rows = execute(db, 'SELECT id,fecha::text as fecha,nombre,activo,ganador FROM eventos ORDER BY fecha DESC LIMIT 50')
    return jsonify([safe_dict(r) for r in rows])

@app.route('/api/eventos', methods=['POST'])
def crear_evento():
    if not require_admin(): return jsonify({'ok': False}), 401
    body = request.get_json() or {}
    db = get_db()
    execute(db, 'UPDATE eventos SET activo=FALSE WHERE activo=TRUE')
    execute(db, 'INSERT INTO eventos (fecha,nombre,activo) VALUES (:f,:n,TRUE)',
            {'f': body.get('fecha'), 'n': body.get('nombre','')})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/eventos/<evento_id>/cerrar', methods=['POST'])
def cerrar_evento(evento_id):
    if not require_admin(): return jsonify({'ok': False}), 401
    db = get_db()
    execute(db, 'UPDATE eventos SET activo=FALSE WHERE id=:id', {'id': evento_id})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/eventos/activo', methods=['GET'])
def evento_activo():
    db = get_db()
    row = execute_one(db, 'SELECT id,fecha::text as fecha,nombre FROM eventos WHERE activo=TRUE LIMIT 1')
    if not row: return jsonify(None)
    return jsonify(safe_dict(row))

# ── RANKING ────────────────────────────────────────────────────────────────────

@app.route('/api/ranking/noche', methods=['GET'])
def ranking_noche():
    db = get_db()
    evento = execute_one(db, 'SELECT id FROM eventos WHERE activo=TRUE LIMIT 1')
    if not evento: return jsonify([])
    rows = execute(db, '''
        SELECT r.consumo_pesos, r.gano_botella, r.puntos_bonus,
               COALESCE(u.nombre_display, u.usuario) as usuario
        FROM ranking_noche r JOIN usuarios u ON u.id=r.usuario_id
        WHERE r.evento_id=:eid ORDER BY r.consumo_pesos DESC
    ''', {'eid': str(evento['id'])})
    return jsonify([dict(r) for r in rows])

@app.route('/api/ranking/declarar-ganador', methods=['POST'])
def declarar_ganador():
    if not require_admin(): return jsonify({'ok': False}), 401
    db = get_db()
    evento = execute_one(db, 'SELECT id FROM eventos WHERE activo=TRUE LIMIT 1')
    if not evento: return jsonify({'ok': False, 'error': 'No hay evento activo'})
    config = get_config()
    top = execute(db, '''
        SELECT r.id, r.usuario_id, COALESCE(u.nombre_display, u.usuario) as usuario
        FROM ranking_noche r JOIN usuarios u ON u.id=r.usuario_id
        WHERE r.evento_id=:eid ORDER BY r.consumo_pesos DESC LIMIT 3
    ''', {'eid': str(evento['id'])})
    if not top: return jsonify({'ok': False, 'error': 'Sin participantes'})
    bonuses = [config.get('bonus_ganador_noche',300), config.get('bonus_segundo',150), config.get('bonus_tercero',75)]
    for i, row in enumerate(top):
        execute(db, 'UPDATE ranking_noche SET posicion=:p,puntos_bonus=:b,gano_botella=:g WHERE id=:id',
               {'p': i+1, 'b': bonuses[i], 'g': i==0, 'id': str(row['id'])})
        execute(db, 'UPDATE usuarios SET puntos_total=puntos_total+:b WHERE id=:id',
               {'b': bonuses[i], 'id': str(row['usuario_id'])})
    execute(db, 'UPDATE eventos SET ganador=:g WHERE id=:id', {'g': top[0]['usuario'], 'id': str(evento['id'])})
    db.commit()
    return jsonify({'ok': True, 'ganador': top[0]['usuario']})

@app.route('/api/ranking/historico', methods=['GET'])
def ranking_historico():
    db = get_db()
    rows = execute(db, '''
        SELECT COALESCE(u.nombre_display, u.usuario) as usuario,
               SUM(r.consumo_pesos) as total_consumo, COUNT(r.id) as noches
        FROM ranking_noche r JOIN usuarios u ON u.id=r.usuario_id
        GROUP BY u.id, u.usuario, u.nombre_display ORDER BY total_consumo DESC LIMIT 50
    ''')
    return jsonify([dict(r) for r in rows])

# ── PREMIOS ────────────────────────────────────────────────────────────────────

@app.route('/api/premios', methods=['GET'])
def get_premios():
    db = get_db()
    rows = execute(db, 'SELECT id,nombre,categoria,precio_pesos,puntos_necesarios,activo FROM premios ORDER BY categoria,precio_pesos')
    return jsonify([safe_dict(r) for r in rows])

@app.route('/api/premios', methods=['POST'])
def agregar_premio():
    if not require_admin(): return jsonify({'ok': False}), 401
    body = request.get_json() or {}
    db = get_db()
    execute(db, 'INSERT INTO premios (nombre,categoria,precio_pesos,puntos_necesarios) VALUES (:n,:c,:p,:pts)',
            {'n': body['nombre'], 'c': body.get('categoria',''), 'p': int(body.get('precio_pesos',0)), 'pts': int(body.get('puntos_necesarios',0))})
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/premios/<premio_id>', methods=['PUT'])
def actualizar_premio(premio_id):
    if not require_admin(): return jsonify({'ok': False}), 401
    body = request.get_json() or {}
    db = get_db()
    if 'puntos_necesarios' in body:
        execute(db, 'UPDATE premios SET puntos_necesarios=:p WHERE id=:id', {'p': int(body['puntos_necesarios']), 'id': premio_id})
    if 'activo' in body:
        execute(db, 'UPDATE premios SET activo=:a WHERE id=:id', {'a': body['activo'], 'id': premio_id})
    db.commit()
    return jsonify({'ok': True})

# ── CANJES ─────────────────────────────────────────────────────────────────────

@app.route('/api/canjes', methods=['POST'])
def crear_canje():
    body = request.get_json() or {}
    usuario_q = body.get('usuario','').strip()
    premio_id = body.get('premio_id')
    db = get_db()
    u = execute_one(db, 'SELECT id,puntos_total FROM usuarios WHERE usuario=:u', {'u': usuario_q})
    if not u: return jsonify({'ok': False, 'error': 'Usuario no encontrado'})
    p = execute_one(db, 'SELECT * FROM premios WHERE id=:id AND activo=TRUE', {'id': str(premio_id)})
    if not p: return jsonify({'ok': False, 'error': 'Premio no disponible'})
    if u['puntos_total'] < p['puntos_necesarios']:
        return jsonify({'ok': False, 'error': 'No tenés suficientes jaggercitos'})
    codigo = secrets.token_hex(4).upper()
    execute(db, 'INSERT INTO canjes (usuario_id,premio_id,codigo_unico) VALUES (:uid,:pid,:c)',
            {'uid': str(u['id']), 'pid': str(p['id']), 'c': codigo})
    execute(db, 'UPDATE usuarios SET puntos_total=puntos_total-:p WHERE id=:id',
            {'p': p['puntos_necesarios'], 'id': str(u['id'])})
    db.commit()
    return jsonify({'ok': True, 'codigo': codigo})

# ── CONFIG ─────────────────────────────────────────────────────────────────────

@app.route('/api/config', methods=['GET'])
def get_config_api():
    db = get_db()
    rows = execute(db, 'SELECT * FROM config_puntos ORDER BY clave')
    return jsonify([dict(r) for r in rows])

@app.route('/api/config/<clave>', methods=['PUT'])
def update_config(clave):
    if not require_admin(): return jsonify({'ok': False}), 401
    body = request.get_json() or {}
    db = get_db()
    execute(db, 'UPDATE config_puntos SET valor=:v WHERE clave=:c', {'v': int(body['valor']), 'c': clave})
    db.commit()
    return jsonify({'ok': True})

# ── EXTERNAL API ───────────────────────────────────────────────────────────────

@app.route('/api/external/registrar', methods=['POST'])
def external_registrar():
    api_key = request.headers.get('X-API-Key')
    if api_key != EXTERNAL_API_KEY: return jsonify({'ok': False}), 403
    body = request.get_json() or {}
    usuario_q = body.get('usuario','').strip()
    consumo_pesos = int(body.get('consumo_pesos', 0))
    origen = body.get('origen', 'caja')
    db = get_db()
    usuario = execute_one(db, 'SELECT id FROM usuarios WHERE usuario ILIKE :u OR dni=:d LIMIT 1',
                         {'u': usuario_q, 'd': usuario_q})
    if not usuario: return jsonify({'ok': False, 'error': 'Usuario no encontrado'})
    evento = execute_one(db, 'SELECT id FROM eventos WHERE activo=TRUE LIMIT 1')
    if not evento: return jsonify({'ok': False, 'error': 'No hay evento activo'})
    config = get_config()
    pts_consumo = (consumo_pesos // 1000) * config.get('puntos_por_mil_pesos', 1)
    pts_mesa = config.get('puntos_mesa', 30) if origen == 'mesa' else 0
    total = pts_consumo + pts_mesa
    execute(db, '''INSERT INTO visitas (usuario_id,evento_id,puntos_consumo,puntos_mesa,consumo_pesos,es_mesa,origen)
        VALUES (:uid,:eid,:pc,:pm,:cp,:em,:or)''',
        {'uid': str(usuario['id']), 'eid': str(evento['id']), 'pc': pts_consumo,
         'pm': pts_mesa, 'cp': consumo_pesos, 'em': origen=='mesa', 'or': origen})
    existing = execute_one(db, 'SELECT id FROM ranking_noche WHERE usuario_id=:uid AND evento_id=:eid',
                          {'uid': str(usuario['id']), 'eid': str(evento['id'])})
    if existing:
        execute(db, 'UPDATE ranking_noche SET consumo_pesos=consumo_pesos+:cp WHERE id=:id',
               {'cp': consumo_pesos, 'id': str(existing['id'])})
    else:
        execute(db, 'INSERT INTO ranking_noche (usuario_id,evento_id,consumo_pesos) VALUES (:uid,:eid,:cp)',
               {'uid': str(usuario['id']), 'eid': str(evento['id']), 'cp': consumo_pesos})
    execute(db, 'UPDATE usuarios SET puntos_total=puntos_total+:t WHERE id=:id',
            {'t': total, 'id': str(usuario['id'])})
    db.commit()
    return jsonify({'ok': True, 'puntos_sumados': total})

# ── PWA ────────────────────────────────────────────────────────────────────────

@app.route('/cliente')
def cliente():
    client_path = os.path.join(os.path.dirname(__file__), 'client', 'index.html')
    with open(client_path, encoding='utf-8') as f:
        return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/manifest.json')
def manifest():
    return jsonify({"name":"Jaggercitos","short_name":"Jaggercitos","start_url":"/cliente","display":"standalone","background_color":"#050505","theme_color":"#d4a829","orientation":"portrait"})

@app.route('/sw.js')
def service_worker():
    return "self.addEventListener('install',e=>self.skipWaiting());self.addEventListener('activate',e=>self.clients.claim());", 200, {'Content-Type':'application/javascript'}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)


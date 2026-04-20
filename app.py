from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
import uuid
from datetime import datetime, timedelta
import cloudinary
import cloudinary.uploader

app = Flask(__name__)
CORS(app)

ADMIN_KEY = os.environ.get('ADMIN_KEY', 'cambiar-esta-clave')

def require_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get('X-Admin-Key', '')
        if key != ADMIN_KEY:
            return jsonify({'ok': False, 'error': 'No autorizado'}), 401
        return f(*args, **kwargs)
    return decorated

# ===== CONFIGURACION =====
TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
DATABASE_URL     = os.environ.get('DATABASE_URL', '')

cloudinary.config(
    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME', ''),
    api_key    = os.environ.get('CLOUDINARY_API_KEY', ''),
    api_secret = os.environ.get('CLOUDINARY_API_SECRET', '')
)

# ===== BASE DE DATOS =====
def get_conn():
    if DATABASE_URL:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        return conn, True  # True = postgres
    else:
        import sqlite3
        conn = sqlite3.connect('dreambed.db')
        conn.row_factory = sqlite3.Row
        return conn, False  # False = sqlite

def query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    conn, is_pg = get_conn()
    try:
        if is_pg:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            sql = sql.replace('?', '%s')
        else:
            cur = conn.cursor()
        cur.execute(sql, params)
        result = None
        if fetchone:
            row = cur.fetchone()
            result = dict(row) if row else None
        elif fetchall:
            rows = cur.fetchall()
            result = [dict(r) for r in rows]
        if commit:
            conn.commit()
        return result
    finally:
        conn.close()

def init_db():
    conn, is_pg = get_conn()
    try:
        if is_pg:
            cur = conn.cursor()
        else:
            cur = conn.cursor()

        cur.execute('''CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            size TEXT,
            price REAL NOT NULL,
            stock INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            colors TEXT DEFAULT '[]',
            image TEXT DEFAULT '',
            code TEXT DEFAULT '',
            figura TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS reservations (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            product_name TEXT NOT NULL,
            color TEXT,
            client_name TEXT NOT NULL,
            client_phone TEXT NOT NULL,
            location TEXT NOT NULL,
            quantity INTEGER DEFAULT 1,
            price REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS locations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            address TEXT NOT NULL,
            cost REAL DEFAULT 0,
            lat REAL DEFAULT NULL,
            lng REAL DEFAULT NULL
        )''')
        conn.commit()

        # Agregar columnas lat/lng si no existen
        try:
            cur.execute('ALTER TABLE locations ADD COLUMN lat REAL DEFAULT NULL')
            conn.commit()
        except:
            pass
        try:
            cur.execute('ALTER TABLE locations ADD COLUMN lng REAL DEFAULT NULL')
            conn.commit()
        except:
            pass

    finally:
        conn.close()

# ===== TELEGRAM =====
def send_telegram(message, photo_urls=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print('Telegram no configurado')
        return
    try:
        if photo_urls and len(photo_urls) > 1:
            # Enviar media group con múltiples fotos
            media = []
            for i, url in enumerate(photo_urls[:10]):
                item = {'type': 'photo', 'media': url}
                if i == 0:
                    item['caption'] = message
                    item['parse_mode'] = 'Markdown'
                media.append(item)
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMediaGroup"
            requests.post(url, json={
                'chat_id': TELEGRAM_CHAT_ID,
                'media': media
            }, timeout=10)
        elif photo_urls and len(photo_urls) == 1:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            requests.post(url, json={
                'chat_id': TELEGRAM_CHAT_ID,
                'photo': photo_urls[0],
                'caption': message,
                'parse_mode': 'Markdown'
            }, timeout=10)
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'Markdown'
            }, timeout=10)
        print('Telegram enviado OK')
    except Exception as e:
        print(f'Error Telegram: {e}')


# ===== PRODUCTOS =====
@app.route('/api/products', methods=['GET'])
def get_products():
    products = query('SELECT * FROM products WHERE active = 1 ORDER BY created_at DESC', fetchall=True)
    return jsonify(products or [])

@app.route('/api/products', methods=['POST'])
@require_admin
def create_product():
    data = request.json
    product_id = str(uuid.uuid4())[:8]
    query('''INSERT INTO products (id, name, type, size, price, stock, colors, image, code, figura)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (product_id, data['name'], data['type'], data.get('size',''),
         data['price'], data.get('stock', 0),
         data.get('colors', '[]'), data.get('image', ''),
         data.get('code', ''), data.get('figura', '')),
        commit=True)
    return jsonify({'ok': True, 'id': product_id})

@app.route('/api/products/<product_id>', methods=['PUT'])
@require_admin 
def update_product(product_id):
    data = request.json
    query('''UPDATE products SET name=?, type=?, size=?, price=?, stock=?,
        colors=?, image=?, active=?, code=?, figura=? WHERE id=?''',
        (data['name'], data['type'], data.get('size',''),
         data['price'], data.get('stock', 0),
         data.get('colors','[]'), data.get('image',''),
         data.get('active', 1), data.get('code',''),
         data.get('figura', ''), product_id),
        commit=True)
    return jsonify({'ok': True})

@app.route('/api/products/<product_id>', methods=['DELETE'])
@require_admin  
def delete_product(product_id):
    query('UPDATE products SET active = 0 WHERE id = ?', (product_id,), commit=True)
    return jsonify({'ok': True})

# ===== RESERVAS =====
@app.route('/api/reservations', methods=['GET'])
def get_reservations():
    expire_old_reservations()
    reservations = query('SELECT * FROM reservations ORDER BY created_at DESC', fetchall=True)
    return jsonify(reservations or [])

@app.route('/api/reservations/lookup', methods=['GET'])
def lookup_reservations():
    phone = request.args.get('phone', '')
    reservations = query(
        'SELECT * FROM reservations WHERE client_phone = ? ORDER BY created_at DESC',
        (phone,), fetchall=True)
    return jsonify(reservations or [])

@app.route('/api/reservations', methods=['POST'])
def create_reservation():
    data = request.json
    required = ['product_id', 'client_name', 'client_phone', 'location', 'color']
    for field in required:
        if not data.get(field):
            return jsonify({'ok': False, 'error': f'Falta {field}'}), 400

    product = query('SELECT * FROM products WHERE id = ? AND active = 1',
                   (data['product_id'],), fetchone=True)
    if not product:
        return jsonify({'ok': False, 'error': 'Producto no encontrado'}), 404
    if product['stock'] <= 0:
        return jsonify({'ok': False, 'error': 'Sin stock'}), 400

    reservation_id = 'RES-' + str(uuid.uuid4())[:6].upper()
    days = data.get('days', 3)
    expires_at = (datetime.now() + timedelta(days=days)).isoformat()

    query('''INSERT INTO reservations
        (id, product_id, product_name, color, client_name, client_phone,
         location, quantity, price, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (reservation_id, data['product_id'], product['name'],
         data['color'], data['client_name'], data['client_phone'],
         data['location'], data.get('quantity', 1),
         product['price'], expires_at),
        commit=True)

    query('UPDATE products SET stock = stock - ? WHERE id = ?',
        (data.get('quantity', 1), data['product_id']), commit=True)

    # obtener primera imagen del producto
    photo_url = None
    try:
        import json as _json
        imgs = _json.loads(product['image'] or '[]')
        if isinstance(imgs, list) and imgs:
            photo_url = imgs[0]
        elif isinstance(imgs, str) and imgs:
            photo_url = imgs
    except:
        photo_url = product['image'] or None

    msg = (
        f"🛏️ *Nueva reserva DreamBed*\n"
        f"*ID Reserva:* `{reservation_id}`\n"
        f"*Código producto:* `{product.get('code', 'Sin código')}`\n"
        f"*Producto:* {product['name']}\n"
        f"*Figura/Color:* {data['color']}\n"
        f"*Cliente:* {data['client_name']}\n"
        f"*Teléfono:* {data['client_phone']}\n"
        f"*Punto:* {data['location']}\n"
        f"*Cantidad:* {data.get('quantity', 1)}\n"
        f"*Precio:* Bs {product['price']}\n"
        f"*Válida hasta:* {expires_at[:10]}\n"
        + (f"*Nota:* {data['note']}" if data.get('note') else '')
    )
    send_telegram(msg, photo_urls=[photo_url] if photo_url else None)

    return jsonify({'ok': True, 'reservation_id': reservation_id, 'expires_at': expires_at})


@app.route('/api/reservations/batch', methods=['POST'])
def create_reservation_batch():
    data = request.json
    items = data.get('items', [])
    if not items:
        return jsonify({'ok': False, 'error': 'Sin productos'}), 400

    required_fields = ['client_name', 'client_phone', 'location', 'days']
    for field in required_fields:
        if not data.get(field):
            return jsonify({'ok': False, 'error': f'Falta {field}'}), 400

    reservation_ids = []
    products_info = []
    total = 0

    for item in items:
        product = query('SELECT * FROM products WHERE id = ? AND active = 1',
                       (item['product_id'],), fetchone=True)
        if not product:
            continue
        if product['stock'] <= 0:
            continue

        qty = item.get('quantity', 1)
        reservation_id = 'RES-' + str(uuid.uuid4())[:6].upper()
        days = data.get('days', 3)
        expires_at = (datetime.now() + timedelta(days=days)).isoformat()

        query('''INSERT INTO reservations
            (id, product_id, product_name, color, client_name, client_phone,
             location, quantity, price, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (reservation_id, item['product_id'], product['name'],
             item['color'], data['client_name'], data['client_phone'],
             data['location'], qty, product['price'], expires_at),
            commit=True)

        query('UPDATE products SET stock = stock - ? WHERE id = ?',
            (qty, item['product_id']), commit=True)

        reservation_ids.append(reservation_id)
        subtotal = product['price'] * qty
        total += subtotal
        products_info.append({
            'name': product['name'],
            'code': product.get('code', ''),
            'color': item['color'],
            'qty': qty,
            'price': product['price'],
            'subtotal': subtotal,
            'image': product.get('image', '')
        })

    if not reservation_ids:
        return jsonify({'ok': False, 'error': 'No se pudo reservar ningún producto'}), 400

    # primera imagen disponible
    photo_url = None
    for p in products_info:
        try:
            import json as _json
            imgs = _json.loads(p['image'] or '[]')
            if isinstance(imgs, list) and imgs:
                photo_url = imgs[0]
                break
        except:
            if p['image']:
                photo_url = p['image']
                break

    # armar mensaje único
    items_text = '\n'.join([
        f"  • {p['name']} ({p['code']}) x{p['qty']} — Color: {p['color']} — Bs {p['subtotal']}"
        for p in products_info
    ])

    msg = (
        f"🛏️ *Nueva reserva DreamBed*\n"
        f"*IDs:* `{', '.join(reservation_ids)}`\n\n"
        f"*Productos:*\n{items_text}\n\n"
        f"*Total: Bs {total}*\n\n"
        f"*Cliente:* {data['client_name']}\n"
        f"*Teléfono:* {data['client_phone']}\n"
        f"*Punto:* {data['location']}\n"
        f"*Días:* {data.get('days', 3)}\n"
        + (f"*Nota:* {data['note']}" if data.get('note') else '')
    )
    all_photos = []
    for p in products_info:
        try:
            import json as _json
            imgs = _json.loads(p['image'] or '[]')
            if isinstance(imgs, list) and imgs:
                all_photos.append(imgs[0])
            elif p['image']:
                all_photos.append(p['image'])
        except:
            if p['image']:
                all_photos.append(p['image'])

    send_telegram(msg, photo_urls=all_photos if all_photos else None)

    return jsonify({
        'ok': True,
        'reservation_ids': reservation_ids,
        'expires_at': expires_at
    })

@app.route('/api/reservations/<res_id>/confirm', methods=['PUT'])
@require_admin
def confirm_reservation(res_id):
    query("UPDATE reservations SET status = 'confirmed' WHERE id = ?", (res_id,), commit=True)
    return jsonify({'ok': True})

@app.route('/api/reservations/<res_id>', methods=['DELETE'])
@require_admin 
def delete_reservation(res_id):
    res = query('SELECT * FROM reservations WHERE id = ?', (res_id,), fetchone=True)
    if res:
        query('UPDATE products SET stock = stock + ? WHERE id = ?',
              (res.get('quantity', 1), res['product_id']), commit=True)
    query('DELETE FROM reservations WHERE id = ?', (res_id,), commit=True)
    return jsonify({'ok': True})

# ===== UBICACIONES =====
@app.route('/api/locations', methods=['GET'])
def get_locations():
    locations = query('SELECT * FROM locations', fetchall=True)
    return jsonify(locations or [])

@app.route('/api/locations', methods=['POST'])
@require_admin
def create_location():
    data = request.json
    loc_id = str(uuid.uuid4())[:8]
    query('INSERT INTO locations (id, name, address, cost, lat, lng) VALUES (?, ?, ?, ?, ?, ?)',
        (loc_id, data['name'], data['address'], data.get('cost', 0), data.get('lat'), data.get('lng')),
        commit=True)
    return jsonify({'ok': True, 'id': loc_id})

@app.route('/api/locations/<loc_id>', methods=['PUT'])
@require_admin 
def update_location(loc_id):
    data = request.json
    query('UPDATE locations SET name=?, address=?, cost=?, lat=?, lng=? WHERE id=?',
        (data['name'], data['address'], data.get('cost', 0), data.get('lat'), data.get('lng'), loc_id),
        commit=True)
    return jsonify({'ok': True})

@app.route('/api/locations/<loc_id>', methods=['DELETE'])
@require_admin
def delete_location(loc_id):
    query('DELETE FROM locations WHERE id = ?', (loc_id,), commit=True)
    return jsonify({'ok': True})

# ===== IMAGENES =====
@app.route('/api/upload', methods=['POST'])
def upload_image():
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'No se envió archivo'}), 400
    file = request.files['file']
    try:
        result = cloudinary.uploader.upload(
            file,
            folder='dreambed',
            transformation=[{'width': 800, 'crop': 'limit'}]
        )
        return jsonify({'ok': True, 'url': result['secure_url']})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ===== HEALTH CHECK =====
@app.route('/')
def index():
    return jsonify({'status': 'DreamBed API corriendo OK'})

def expire_old_reservations():
    now = datetime.now().isoformat()
    expired = query(
        "SELECT * FROM reservations WHERE status = 'pending' AND expires_at < ?",
        (now,), fetchall=True
    )
    if expired:
        for res in expired:
            query('UPDATE products SET stock = stock + ? WHERE id = ?',
                (res.get('quantity', 1), res['product_id']), commit=True)
        query(
            "UPDATE reservations SET status = 'expired' WHERE status = 'pending' AND expires_at < ?",
            (now,), commit=True
        )

init_db()

if __name__ == '__main__':
    app.run(debug=True)
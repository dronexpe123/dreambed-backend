from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import requests
import os
import uuid
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# ===== CONFIGURACION =====
TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
DB_PATH = os.environ.get('DB_PATH', 'dreambed.db')

# ===== BASE DE DATOS =====
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        size TEXT,
        price REAL NOT NULL,
        stock INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        colors TEXT DEFAULT '[]',
        image TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS reservations (
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

    c.execute('''CREATE TABLE IF NOT EXISTS locations (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        address TEXT NOT NULL,
        cost REAL DEFAULT 0
    )''')

    conn.commit()
    conn.close()

# ===== TELEGRAM =====
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print('Telegram no configurado, saltando notificación')
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'Markdown'
        }, timeout=10)
        print('Telegram enviado OK')
    except Exception as e:
        print(f'Error enviando Telegram: {e}')

# ===== PRODUCTOS =====
@app.route('/api/products', methods=['GET'])
def get_products():
    conn = get_db()
    products = conn.execute(
        'SELECT * FROM products WHERE active = 1 ORDER BY created_at DESC'
    ).fetchall()
    conn.close()
    return jsonify([dict(p) for p in products])

@app.route('/api/products', methods=['POST'])
def create_product():
    data = request.json
    conn = get_db()
    product_id = str(uuid.uuid4())[:8]
    conn.execute('''INSERT INTO products 
        (id, name, type, size, price, stock, colors, image)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (product_id, data['name'], data['type'], data.get('size',''),
         data['price'], data.get('stock', 0),
         data.get('colors', '[]'), data.get('image', ''))
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'id': product_id})

@app.route('/api/products/<product_id>', methods=['PUT'])
def update_product(product_id):
    data = request.json
    conn = get_db()
    conn.execute('''UPDATE products SET
        name=?, type=?, size=?, price=?, stock=?, colors=?, image=?, active=?
        WHERE id=?''',
        (data['name'], data['type'], data.get('size',''),
         data['price'], data.get('stock', 0),
         data.get('colors','[]'), data.get('image',''),
         data.get('active', 1), product_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/products/<product_id>', methods=['DELETE'])
def delete_product(product_id):
    conn = get_db()
    conn.execute('UPDATE products SET active = 0 WHERE id = ?', (product_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ===== RESERVAS =====
@app.route('/api/reservations', methods=['GET'])
def get_reservations():
    conn = get_db()
    reservations = conn.execute(
        'SELECT * FROM reservations ORDER BY created_at DESC'
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in reservations])

@app.route('/api/reservations/lookup', methods=['GET'])
def lookup_reservations():
    phone = request.args.get('phone', '')
    conn = get_db()
    reservations = conn.execute(
        'SELECT * FROM reservations WHERE client_phone = ? ORDER BY created_at DESC',
        (phone,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in reservations])

@app.route('/api/reservations', methods=['POST'])
def create_reservation():
    data = request.json

    # validar campos
    required = ['product_id', 'client_name', 'client_phone', 'location', 'color']
    for field in required:
        if not data.get(field):
            return jsonify({'ok': False, 'error': f'Falta el campo {field}'}), 400

    conn = get_db()

    # verificar stock
    product = conn.execute(
        'SELECT * FROM products WHERE id = ? AND active = 1', 
        (data['product_id'],)
    ).fetchone()

    if not product:
        conn.close()
        return jsonify({'ok': False, 'error': 'Producto no encontrado'}), 404

    if product['stock'] <= 0:
        conn.close()
        return jsonify({'ok': False, 'error': 'Sin stock disponible'}), 400

    # crear reserva
    reservation_id = 'RES-' + str(uuid.uuid4())[:6].upper()
    days = data.get('days', 3)
    expires_at = (datetime.now() + timedelta(days=days)).isoformat()

    conn.execute('''INSERT INTO reservations
        (id, product_id, product_name, color, client_name, client_phone,
         location, quantity, price, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (reservation_id, data['product_id'], product['name'],
         data['color'], data['client_name'], data['client_phone'],
         data['location'], data.get('quantity', 1),
         product['price'], expires_at)
    )

    # descontar stock
    conn.execute(
        'UPDATE products SET stock = stock - 1 WHERE id = ?',
        (data['product_id'],)
    )

    conn.commit()
    conn.close()

    # notificar admin por WhatsApp
    msg = (
        f"🛏️ *Nueva reserva DreamBed*\n"
        f"ID: {reservation_id}\n"
        f"Producto: {product['name']} - {data['color']}\n"
        f"Cliente: {data['client_name']}\n"
        f"Teléfono: {data['client_phone']}\n"
        f"Punto de entrega: {data['location']}\n"
        f"Precio: Bs {product['price']}\n"
        f"Válida hasta: {expires_at[:10]}"
    )
    send_telegram(msg)

    return jsonify({
        'ok': True,
        'reservation_id': reservation_id,
        'expires_at': expires_at
    })

@app.route('/api/reservations/<res_id>/confirm', methods=['PUT'])
def confirm_reservation(res_id):
    conn = get_db()
    conn.execute(
        "UPDATE reservations SET status = 'confirmed' WHERE id = ?", (res_id,)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/reservations/<res_id>', methods=['DELETE'])
def delete_reservation(res_id):
    conn = get_db()
    # devolver stock
    res = conn.execute(
        'SELECT * FROM reservations WHERE id = ?', (res_id,)
    ).fetchone()
    if res:
        conn.execute(
            'UPDATE products SET stock = stock + 1 WHERE id = ?',
            (res['product_id'],)
        )
    conn.execute('DELETE FROM reservations WHERE id = ?', (res_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ===== UBICACIONES =====
@app.route('/api/locations', methods=['GET'])
def get_locations():
    conn = get_db()
    locations = conn.execute('SELECT * FROM locations').fetchall()
    conn.close()
    return jsonify([dict(l) for l in locations])

@app.route('/api/locations', methods=['POST'])
def create_location():
    data = request.json
    conn = get_db()
    loc_id = str(uuid.uuid4())[:8]
    conn.execute(
        'INSERT INTO locations (id, name, address, cost) VALUES (?, ?, ?, ?)',
        (loc_id, data['name'], data['address'], data.get('cost', 0))
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'id': loc_id})

@app.route('/api/locations/<loc_id>', methods=['PUT'])
def update_location(loc_id):
    data = request.json
    conn = get_db()
    conn.execute(
        'UPDATE locations SET name=?, address=?, cost=? WHERE id=?',
        (data['name'], data['address'], data.get('cost', 0), loc_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/locations/<loc_id>', methods=['DELETE'])
def delete_location(loc_id):
    conn = get_db()
    conn.execute('DELETE FROM locations WHERE id = ?', (loc_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ===== HEALTH CHECK =====
@app.route('/')
def index():
    return jsonify({'status': 'DreamBed API corriendo OK'})

# ===== INIT =====
if __name__ == '__main__':
    init_db()
    app.run(debug=True)

init_db()
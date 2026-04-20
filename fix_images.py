import psycopg2

conn = psycopg2.connect('postgresql://postgres:ZKJcUAKnHZniRWrmKMwaFIKgkkXaHNGI@switchyard.proxy.rlwy.net:11843/railway')
cur = conn.cursor()

# ver todos los productos y sus imágenes
cur.execute("SELECT id, name, image FROM products")
rows = cur.fetchall()
print("Productos actuales:")
for row in rows:
    print(f"  ID: {row[0]} | Nombre: {row[1]} | Image: {repr(row[2])}")

# limpiar imágenes corruptas
cur.execute("""
    UPDATE products 
    SET image = '[]' 
    WHERE image IS NULL 
       OR image = '' 
       OR image = '["["]'
       OR (image NOT LIKE '[%' AND image NOT LIKE 'http%')
""")
conn.commit()
print(f"\nFilas corregidas: {cur.rowcount}")

conn.close()
print("Listo.")
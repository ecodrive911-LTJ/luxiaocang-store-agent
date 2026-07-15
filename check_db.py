import sqlite3
conn = sqlite3.connect(r"C:\Users\13522\diancanmou\database.db")
conn.row_factory = sqlite3.Row

user = conn.execute("SELECT * FROM users WHERE username='guangan'").fetchone()
print("guangan:", dict(user) if user else "NOT FOUND")

stores = conn.execute("SELECT * FROM stores").fetchall()
for s in stores:
    print("Store:", dict(s))

bindings = conn.execute("SELECT * FROM user_stores").fetchall()
for b in bindings:
    print("Binding:", dict(b))

conn.close()

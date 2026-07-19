import paramiko

host = '120.26.176.215'
user = 'root'
pwd = 'DOWson1108'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pwd, timeout=10)

cmd = """python3 -c "
import sqlite3
conn = sqlite3.connect('/opt/luxiaocang/database.db')
conn.row_factory = sqlite3.Row

# Check guangan user
u = conn.execute('SELECT id, username, role FROM users WHERE username=?', ('guangan',)).fetchone()
print('guangan user:', dict(u) if u else 'NOT FOUND')

# Check user_stores bindings
bindings = conn.execute('SELECT * FROM user_stores').fetchall()
print('All bindings:', [dict(b) for b in bindings])

# Check stores
stores = conn.execute('SELECT id, name FROM stores').fetchall()
print('All stores:', [dict(s) for s in stores])

conn.close()
"
"""

stdin, stdout, stderr = client.exec_command(cmd)
print('STDOUT:', stdout.read().decode())
print('STDERR:', stderr.read().decode())
client.close()

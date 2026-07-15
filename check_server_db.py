import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("120.26.176.215", username="root", password="DOWson1108")

cmd = """python3 -c "
import sqlite3; conn = sqlite3.connect('/opt/luxiaocang/database.db'); conn.row_factory = sqlite3.Row
user = conn.execute(\\\"SELECT * FROM users WHERE username='guangan'\\\").fetchone()
print('guangan:', dict(user) if user else 'NOT FOUND')
stores = conn.execute('SELECT * FROM stores').fetchall()
for s in stores: print('Store:', dict(s))
bindings = conn.execute('SELECT * FROM user_stores').fetchall()
for b in bindings: print('Binding:', dict(b))
conn.close()
"
"""
stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode())
print(stderr.read().decode())
ssh.close()

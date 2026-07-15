import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("120.26.176.215", username="root", password="DOWson1108")

cmd = """python3 -c "
import sqlite3; conn = sqlite3.connect('/opt/luxiaocang/database.db')
# Bind guangan to 广安店
conn.execute(\\\"INSERT OR REPLACE INTO user_stores (user_id, store_id, role) VALUES ('c04f37e0-70a2-462f-b826-5811764ea3b6', 'f67b4c21-2529-4d96-a2e8-0749451e5295', 'store_owner')\\\")
conn.commit()
# Verify
conn.row_factory = sqlite3.Row
b = conn.execute(\\\"SELECT * FROM user_stores WHERE user_id='c04f37e0-70a2-462f-b826-5811764ea3b6'\\\").fetchone()
print('guangan NOW binding:', dict(b) if b else 'FAILED')
conn.close()
"
"""
stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode())
print(stderr.read().decode())
ssh.close()

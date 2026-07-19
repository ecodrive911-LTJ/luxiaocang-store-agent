import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('120.26.176.215', username='root', password='DOWson1108')

cmd = (
    "cd /opt/luxiaocang && python3 -c \""
    "import sqlite3,sys; sys.path.insert(0,'.'); import auth; "
    "DB=auth.DB_PATH; conn=sqlite3.connect(DB); c=conn.cursor(); "
    "uid=c.execute(\\\"SELECT id FROM users WHERE username='owner_e2e'\\\").fetchone()[0]; "
    "sid='f67b4c21-2529-4d96-a2e8-0749451e5295'; "
    "c.execute(\\\"INSERT OR IGNORE INTO user_stores (user_id,store_id,role) VALUES (?,?,?)\\\",(uid,sid,'owner')); "
    "conn.commit(); "
    "print('BOUND',uid,sid,'rowcount',c.rowcount)\""
)
stdin, stdout, stderr = ssh.exec_command(cmd)
print("OUT:", stdout.read().decode())
print("ERR:", stderr.read().decode())
ssh.close()

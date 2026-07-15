import sqlite3
c = sqlite3.connect('/opt/luxiaocang/app.db')
c.row_factory = sqlite3.Row
sql = """SELECT u.*, ti.product_name, ti.product_spec, ti.expected_price,
                usr.username as uploader_name, c.task_name, s.name as store_name
         FROM collect_uploads u
         JOIN collect_tasks c ON u.task_id = c.id
         LEFT JOIN collect_task_items ti ON u.task_item_id = ti.id
         LEFT JOIN users usr ON u.uploaded_by = usr.id
         LEFT JOIN stores s ON c.store_id = s.id
         WHERE u.status IN (?,?,?)
         ORDER BY u.uploaded_at DESC LIMIT 100"""
try:
    rows = c.execute(sql, ('done','failed','analyzing')).fetchall()
    print("OK rows:", len(rows))
except Exception as e:
    print("SQL ERROR:", repr(e))

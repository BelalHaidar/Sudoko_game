import sqlite3
from datetime import datetime

class Database:
    def __init__(self, db_name='sudoku.db'):
        self.db_name = db_name
        self.init_db()
    
    def get_connection(self):
        # إضافة timeout لانتظار فتح القفل في حال وجود عمليات متزامنة من البوت والموقع
        return sqlite3.connect(self.db_name, timeout=20)
    
    def init_db(self):
        conn = self.get_connection()
        # تفعيل وضع WAL للسماح بالقراءة والكتابة المتزامنة دون قفل الملف
        conn.execute('PRAGMA journal_mode=WAL;')
        cursor = conn.cursor()
        
        # جدول المستخدمين
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                username TEXT,
                first_name TEXT,
                points INTEGER DEFAULT 100,
                games_played INTEGER DEFAULT 0,
                games_won INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        ''')

        # جدول المسؤولين
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

        # جدول طلبات الشحن
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS charge_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                points INTEGER,
                method TEXT,
                phone TEXT,
                status TEXT DEFAULT 'pending',
                processed_by INTEGER,
                processed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # جدول الألعاب
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                game_data TEXT,
                difficulty TEXT,
                status TEXT DEFAULT 'active',
                score INTEGER DEFAULT 0,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # جدول المعاملات المالية
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                transaction_type TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def create_user(self, telegram_id, username, first_name):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
        user = cursor.fetchone()
        if not user:
            cursor.execute('''
                INSERT INTO users (telegram_id, username, first_name, points, created_at, last_login)
                VALUES (?, ?, ?, 100, ?, ?)
            ''', (telegram_id, username, first_name, datetime.now(), datetime.now()))
            user_id = cursor.lastrowid
            cursor.execute('INSERT INTO transactions (user_id, amount, transaction_type, description) VALUES (?, 100, "bonus", "نقاط ترحيبية")', (user_id,))
            conn.commit()
            conn.close()
            return user_id
        else:
            cursor.execute('UPDATE users SET last_login = ? WHERE telegram_id = ?', (datetime.now(), telegram_id))
            conn.commit()
            conn.close()
            return user[0]

    def get_user_by_telegram_id(self, telegram_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
        user = cursor.fetchone()
        conn.close()
        return user

    def get_user_points(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT points FROM users WHERE id = ?', (user_id,))
        res = cursor.fetchone()
        conn.close()
        return res[0] if res else 0

    def add_points(self, user_id, amount, description):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET points = points + ? WHERE id = ?', (amount, user_id))
        cursor.execute('INSERT INTO transactions (user_id, amount, transaction_type, description) VALUES (?, ?, "earn", ?)', (user_id, amount, description))
        conn.commit()
        conn.close()

    def deduct_points(self, user_id, amount, description):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT points FROM users WHERE id = ?', (user_id,))
        points_row = cursor.fetchone()
        if points_row and points_row[0] >= amount:
            cursor.execute('UPDATE users SET points = points - ? WHERE id = ?', (amount, user_id))
            cursor.execute('INSERT INTO transactions (user_id, amount, transaction_type, description) VALUES (?, ?, "spend", ?)', (user_id, -amount, description))
            conn.commit()
            conn.close()
            return True
        conn.close()
        return False

    def create_charge_request(self, user_id, amount, points, method, phone):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO charge_requests (user_id, amount, points, method, phone, created_at) VALUES (?, ?, ?, ?, ?, ?)', (user_id, amount, points, method, phone, datetime.now()))
        request_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return request_id

    def get_charge_request_details(self, request_id):
        """جلب تفاصيل الطلب مع بيانات المستخدم لإرسال الإشعارات"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT cr.id, cr.user_id, cr.amount, cr.points, cr.method, cr.phone, u.telegram_id, u.first_name 
            FROM charge_requests cr 
            JOIN users u ON cr.user_id = u.id 
            WHERE cr.id = ?
        ''', (request_id,))
        res = cursor.fetchone()
        conn.close()
        return res

    def update_charge_status(self, request_id, status, admin_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE charge_requests SET status = ?, processed_by = ?, processed_at = ? WHERE id = ?', (status, admin_id, datetime.now(), request_id))
        if status == 'approved':
            cursor.execute('SELECT user_id, points, method FROM charge_requests WHERE id = ?', (request_id,))
            req = cursor.fetchone()
            if req:
                # يتم استخدام دالة داخلية لإضافة النقاط لضمان استخدام نفس الاتصال إذا لزم الأمر
                cursor.execute('UPDATE users SET points = points + ? WHERE id = ?', (req[1], req[0]))
                cursor.execute('INSERT INTO transactions (user_id, amount, transaction_type, description) VALUES (?, ?, "earn", ?)', (req[0], req[1], f"شحن رصيد ({req[2]})"))
        conn.commit()
        conn.close()

    def get_system_stats(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        stats = {}
        cursor.execute('SELECT COUNT(*) FROM users')
        stats['total_users'] = cursor.fetchone()[0]
        cursor.execute('SELECT SUM(points) FROM users')
        stats['total_points'] = cursor.fetchone()[0] or 0
        cursor.execute('SELECT COUNT(*) FROM charge_requests WHERE status = "pending"')
        stats['pending_charges'] = cursor.fetchone()[0]
        conn.close()
        return stats

    def is_admin(self, telegram_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM admins JOIN users ON admins.user_id = users.id WHERE users.telegram_id = ?', (telegram_id,))
        res = cursor.fetchone()
        conn.close()
        return res is not None

    def can_claim_daily(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT created_at FROM transactions WHERE user_id = ? AND description = "مكافأة يومية" ORDER BY created_at DESC LIMIT 1', (user_id,))
        last = cursor.fetchone()
        conn.close()
        if not last: return True
        # التحقق من مرور 24 ساعة
        try:
            last_time = datetime.fromisoformat(last[0])
            return (datetime.now() - last_time).total_seconds() > 86400
        except:
            return True

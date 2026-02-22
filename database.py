import sqlite3
from datetime import datetime

class Database:
    def __init__(self, db_name='sudoku.db'):
        self.db_name = db_name
        self.init_db()
    
    def get_connection(self):
        return sqlite3.connect(self.db_name)
    
    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
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

        # جدول المشرفين
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
                amount INTEGER,  -- المبلغ بالليرة
                points INTEGER,   -- عدد النقاط المطلوبة
                method TEXT,      -- طريقة الدفع (syriatel, mtn, sham)
                phone TEXT,       -- رقم الهاتف
                status TEXT DEFAULT 'pending',  -- pending, approved, rejected
                processed_by INTEGER,
                processed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (processed_by) REFERENCES users (id)
            )
        ''')
        
        # إضافة مشرف افتراضي (أول مستخدم)
        cursor.execute('''
            INSERT OR IGNORE INTO admins (user_id, added_by)
            SELECT id, id FROM users ORDER BY id ASC LIMIT 1
        ''')
        
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
            cursor.execute('''
                INSERT INTO transactions (user_id, amount, transaction_type, description)
                VALUES (?, 100, 'bonus', 'نقاط ترحيبية')
            ''', (user_id,))
            
            conn.commit()
            conn.close()
            return user_id
        else:
            cursor.execute('UPDATE users SET last_login = ? WHERE telegram_id = ?', 
                         (datetime.now(), telegram_id))
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
        points = cursor.fetchone()
        conn.close()
        return points[0] if points else 0
    
    def add_points(self, user_id, amount, description):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('UPDATE users SET points = points + ? WHERE id = ?', (amount, user_id))
        cursor.execute('''
            INSERT INTO transactions (user_id, amount, transaction_type, description)
            VALUES (?, ?, 'earn', ?)
        ''', (user_id, amount, description))
        
        conn.commit()
        conn.close()
    
    def deduct_points(self, user_id, amount, description):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT points FROM users WHERE id = ?', (user_id,))
        current_points = cursor.fetchone()[0]
        
        if current_points >= amount:
            cursor.execute('UPDATE users SET points = points - ? WHERE id = ?', (amount, user_id))
            cursor.execute('''
                INSERT INTO transactions (user_id, amount, transaction_type, description)
                VALUES (?, ?, 'spend', ?)
            ''', (user_id, -amount, description))
            conn.commit()
            conn.close()
            return True
        else:
            conn.close()
            return False
    
    def save_game(self, user_id, game_data, difficulty):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO games (user_id, game_data, difficulty, status, started_at)
            VALUES (?, ?, ?, 'active', ?)
        ''', (user_id, game_data, difficulty, datetime.now()))
        game_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return game_id
    
    def complete_game(self, game_id, score):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE games 
            SET status = 'completed', completed_at = ?, score = ?
            WHERE id = ?
        ''', (datetime.now(), score, game_id))
        
        cursor.execute('''
            UPDATE users 
            SET games_played = games_played + 1,
                games_won = games_won + 1
            WHERE id = (SELECT user_id FROM games WHERE id = ?)
        ''', (game_id,))
        
        conn.commit()
        conn.close()
    
    def get_leaderboard(self, limit=10):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT username, points, games_played, games_won 
            FROM users 
            ORDER BY points DESC 
            LIMIT ?
        ''', (limit,))
        leaders = cursor.fetchall()
        conn.close()
        return leaders
    
    def get_last_daily(self, user_id):
        """الحصول على تاريخ آخر مكافأة يومية"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT created_at FROM transactions 
            WHERE user_id = ? AND transaction_type = 'daily' 
            ORDER BY created_at DESC LIMIT 1
        ''', (user_id,))
        last = cursor.fetchone()
        conn.close()
        return last[0] if last else None

    def can_claim_daily(self, user_id):
        """التحقق مما إذا كان يمكن للمستخدم المطالبة بالمكافأة اليومية"""
        last = self.get_last_daily(user_id)
        if not last:
            return True
        
        # التحقق من مرور 24 ساعة
        from datetime import datetime, timedelta
        last_date = datetime.fromisoformat(last)
        return datetime.now() - last_date > timedelta(hours=24)
    
    def get_all_users(self, page=1, per_page=20):
        """الحصول على قائمة جميع المستخدمين مع pagination"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        offset = (page - 1) * per_page
        cursor.execute('''
            SELECT id, telegram_id, username, first_name, points, 
                games_played, games_won, created_at, last_login
            FROM users 
            ORDER BY points DESC
            LIMIT ? OFFSET ?
        ''', (per_page, offset))
        
        users = cursor.fetchall()
        
        # الحصول على العدد الإجمالي
        cursor.execute('SELECT COUNT(*) FROM users')
        total = cursor.fetchone()[0]
        
        conn.close()
        return users, total

    def search_users(self, query):
        """البحث عن مستخدمين بالاسم أو المعرف"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        search_term = f'%{query}%'
        cursor.execute('''
            SELECT id, telegram_id, username, first_name, points, 
                games_played, games_won, created_at
            FROM users 
            WHERE username LIKE ? OR first_name LIKE ? OR telegram_id LIKE ?
            ORDER BY points DESC
            LIMIT 50
        ''', (search_term, search_term, search_term))
        
        users = cursor.fetchall()
        conn.close()
        return users

    def get_user_transactions(self, user_id, limit=50):
        """الحصول على جميع معاملات مستخدم معين"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, amount, transaction_type, description, created_at
            FROM transactions 
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (user_id, limit))
        
        transactions = cursor.fetchall()
        conn.close()
        return transactions

    def get_all_transactions(self, page=1, per_page=50, transaction_type=None):
        """الحصول على جميع المعاملات مع فلترة حسب النوع"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        offset = (page - 1) * per_page
        query = '''
            SELECT t.id, t.user_id, u.username, u.first_name, 
                t.amount, t.transaction_type, t.description, t.created_at
            FROM transactions t
            JOIN users u ON t.user_id = u.id
        '''
        
        params = []
        if transaction_type:
            query += ' WHERE t.transaction_type = ?'
            params.append(transaction_type)
        
        query += ' ORDER BY t.created_at DESC LIMIT ? OFFSET ?'
        params.extend([per_page, offset])
        
        cursor.execute(query, params)
        transactions = cursor.fetchall()
        
        # العدد الإجمالي
        count_query = 'SELECT COUNT(*) FROM transactions'
        if transaction_type:
            count_query += ' WHERE transaction_type = ?'
            cursor.execute(count_query, [transaction_type] if transaction_type else [])
        else:
            cursor.execute(count_query)
        total = cursor.fetchone()[0]
        
        conn.close()
        return transactions, total

    def get_charge_requests(self, status='pending'):
        """الحصول على طلبات الشحن حسب الحالة"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT cr.id, cr.user_id, u.username, u.first_name, 
                cr.amount, cr.points, cr.method, cr.phone, cr.status, cr.created_at
            FROM charge_requests cr
            JOIN users u ON cr.user_id = u.id
            WHERE cr.status = ?
            ORDER BY cr.created_at DESC
        ''', (status,))
        
        requests = cursor.fetchall()
        conn.close()
        return requests

    def create_charge_request(self, user_id, amount, points, method, phone):
        """إنشاء طلب شحن جديد"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO charge_requests (user_id, amount, points, method, phone, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
        ''', (user_id, amount, points, method, phone, datetime.now()))
        
        request_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return request_id

    def update_charge_status(self, request_id, status, admin_id=None):
        """تحديث حالة طلب الشحن"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE charge_requests 
            SET status = ?, processed_by = ?, processed_at = ?
            WHERE id = ?
        ''', (status, admin_id, datetime.now(), request_id))
        
        # إذا تمت الموافقة، أضف النقاط
        if status == 'approved':
            cursor.execute('''
                SELECT user_id, points FROM charge_requests WHERE id = ?
            ''', (request_id,))
            request = cursor.fetchone()
            if request:
                self.add_points(request[0], request[1], f"شحن رصيد عبر {request[2] if len(request)>2 else 'شحن'}")
        
        conn.commit()
        conn.close()

    def get_system_stats(self):
        """إحصائيات عامة للنظام"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        # عدد المستخدمين
        cursor.execute('SELECT COUNT(*) FROM users')
        stats['total_users'] = cursor.fetchone()[0]
        
        # إجمالي النقاط
        cursor.execute('SELECT SUM(points) FROM users')
        stats['total_points'] = cursor.fetchone()[0] or 0
        
        # متوسط النقاط
        cursor.execute('SELECT AVG(points) FROM users')
        stats['avg_points'] = round(cursor.fetchone()[0] or 0, 2)
        
        # إجمالي المعاملات
        cursor.execute('SELECT COUNT(*) FROM transactions')
        stats['total_transactions'] = cursor.fetchone()[0]
        
        # إجمالي الألعاب
        cursor.execute('SELECT COUNT(*) FROM games')
        stats['total_games'] = cursor.fetchone()[0]
        
        # الألعاب المكتملة
        cursor.execute('SELECT COUNT(*) FROM games WHERE status = "completed"')
        stats['completed_games'] = cursor.fetchone()[0]
        
        # طلبات الشحن المعلقة
        cursor.execute('SELECT COUNT(*) FROM charge_requests WHERE status = "pending"')
        stats['pending_charges'] = cursor.fetchone()[0]
        
        # المستخدمين النشطين اليوم
        today = datetime.now().date()
        cursor.execute('''
            SELECT COUNT(*) FROM users 
            WHERE DATE(last_login) = ?
        ''', (today,))
        stats['active_today'] = cursor.fetchone()[0]
        
        conn.close()
        return stats

    def add_admin(self, user_id, added_by=None):
        """إضافة مشرف جديد"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR IGNORE INTO admins (user_id, added_by, added_at)
            VALUES (?, ?, ?)
        ''', (user_id, added_by, datetime.now()))
        
        conn.commit()
        conn.close()

    def remove_admin(self, user_id):
        """إزالة مشرف"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

    def is_admin(self, user_id):
        """التحقق مما إذا كان المستخدم مشرفاً"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM admins WHERE user_id = ?', (user_id,))
        result = cursor.fetchone() is not None
        conn.close()
        return result

    def adjust_user_points(self, user_id, amount, reason, admin_id=None):
        """تعديل نقاط مستخدم يدوياً (إضافة أو خصم)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if amount > 0:
            cursor.execute('UPDATE users SET points = points + ? WHERE id = ?', (amount, user_id))
            trans_type = 'admin_add'
        else:
            cursor.execute('UPDATE users SET points = points - ? WHERE id = ?', (abs(amount), user_id))
            trans_type = 'admin_remove'
        
        cursor.execute('''
            INSERT INTO transactions (user_id, amount, transaction_type, description)
            VALUES (?, ?, ?, ?)
        ''', (user_id, amount, trans_type, f"{reason} (بواسطة المشرف {admin_id})"))
        
        conn.commit()
        conn.close()

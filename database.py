import sqlite3
import json
import os
import logging
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path=None):
        self.db_path = db_path or os.environ.get('DATABASE_PATH', 'sudoku.db')
        self._init_db()
    
    @contextmanager
    def get_connection(self):
        """✅ إدارة اتصال آمن مع إغلاق تلقائي"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
            conn.row_factory = sqlite3.Row
            # ✅ تحسينات أمان SQLite
            conn.execute('PRAGMA foreign_keys = ON')
            conn.execute('PRAGMA journal_mode = WAL')
            conn.execute('PRAGMA busy_timeout = 30000')
            conn.execute('PRAGMA secure_delete = ON')
            yield conn
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()
    
    def _init_db(self):
        """✅ تهيئة قاعدة البيانات مع منع SQL Injection"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                # جدول المستخدمين - ✅ جميع الكلمات بدون مسافات
                cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    points INTEGER DEFAULT 100,
                    agreed_terms INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

                # جدول الشحن - ✅ تصحيح I NTEGER → INTEGER
                cursor.execute('''CREATE TABLE IF NOT EXISTS charge_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount_ls INTEGER NOT NULL,
                    points INTEGER NOT NULL,
                    method TEXT,
                    sender_phone TEXT,
                    trans_id TEXT,
                    status TEXT DEFAULT 'pending',
                    processed_by INTEGER,
                    processed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id))''')
                
                # جدول السحب
                cursor.execute('''CREATE TABLE IF NOT EXISTS withdrawal_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount_points INTEGER NOT NULL,
                    amount_money REAL NOT NULL,
                    final_amount REAL NOT NULL,
                    method TEXT,
                    receiver_phone TEXT,
                    status TEXT DEFAULT 'pending',
                    processed_by INTEGER,
                    processed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id))''')
                
                # جدول الألعاب
                cursor.execute('''CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    difficulty TEXT NOT NULL,
                    puzzle_data TEXT,
                    solution_data TEXT,
                    status TEXT DEFAULT 'playing',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id))''')
                
                # جدول السجل
                cursor.execute('''CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    description TEXT,
                    points_change INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id))''')
                
                # إضافة الأعمدة المفقودة بأمان (بدون SQL Injection)
                self._safe_add_column(cursor, 'users', 'agreed_terms', 'INTEGER DEFAULT 0')
                self._safe_add_column(cursor, 'charge_requests', 'processed_by', 'INTEGER')
                self._safe_add_column(cursor, 'charge_requests', 'processed_at', 'TIMESTAMP')
                self._safe_add_column(cursor, 'withdrawal_requests', 'processed_by', 'INTEGER')
                self._safe_add_column(cursor, 'withdrawal_requests', 'processed_at', 'TIMESTAMP')
                self._safe_add_column(cursor, 'games', 'puzzle_data', 'TEXT')
                self._safe_add_column(cursor, 'games', 'solution_data', 'TEXT')
                
                conn.commit()
                logger.info("Database initialized successfully")
            except sqlite3.Error as e:
                logger.error(f"Failed to initialize database: {e}")
                raise
    
    def _safe_add_column(self, cursor, table, column, definition):
        """✅ إضافة عمود بأمان مع منع SQL Injection"""
        # ✅ قائمة بيضاء للجداول والأعمدة المسموح بها
        allowed_tables = ['users', 'charge_requests', 'withdrawal_requests', 'games', 'activity_log']
        allowed_columns = {
            'users': ['agreed_terms'],
            'charge_requests': ['processed_by', 'processed_at'],
            'withdrawal_requests': ['processed_by', 'processed_at'],
            'games': ['puzzle_data', 'solution_data', 'status', 'completed_at'],
            'activity_log': []
        }
        
        if table not in allowed_tables or column not in allowed_columns.get(table, []):
            logger.warning(f"Attempted to add unauthorized column: {table}.{column}")
            return
        
        try:
            cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
            logger.info(f"Added column {table}.{column}")
        except sqlite3.OperationalError:
            # العمود موجود بالفعل - هذا طبيعي
            pass
    
    def create_user(self, telegram_id, username, first_name):
        """✅ إنشاء مستخدم مع منع SQL Injection"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR IGNORE INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)',
                (telegram_id, username, first_name)
            )
            conn.commit()
    
    def get_user_by_telegram_id(self, telegram_id):
        """✅ جلب مستخدم بأمان"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
            res = cursor.fetchone()
            return dict(res) if res else None
    
    def update_terms(self, telegram_id, status):
        """✅ تحديث الموافقة على الشروط"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET agreed_terms = ? WHERE telegram_id = ?', (status, telegram_id))
            conn.commit()
    
    def create_charge_request(self, user_id, amount_ls, points, method, sender_phone, trans_id):
        """✅ إنشاء طلب شحن مع التحقق من المدخلات"""
        # ✅ التحقق من صحة المدخلات
        if not all([isinstance(user_id, int), isinstance(amount_ls, int), isinstance(points, int)]):
            raise ValueError("Invalid input types")
        if amount_ls <= 0 or points <= 0:
            raise ValueError("Amount and points must be positive")
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''INSERT INTO charge_requests 
                             (user_id, amount_ls, points, method, sender_phone, trans_id) 
                             VALUES (?, ?, ?, ?, ?, ?)''',
                          (user_id, amount_ls, points, method, sender_phone, trans_id))
            rid = cursor.lastrowid
            conn.commit()
            return rid
    
    def create_withdrawal_request(self, user_id, amount_points, amount_money, final_amount, method, receiver_phone):
        """✅ إنشاء طلب سحب مع التحقق"""
        if not all([isinstance(user_id, int), isinstance(amount_points, int), 
                   isinstance(amount_money, (int, float)), isinstance(final_amount, (int, float))]):
            raise ValueError("Invalid input types")
        if amount_points <= 0 or final_amount <= 0:
            raise ValueError("Amounts must be positive")
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''INSERT INTO withdrawal_requests 
                             (user_id, amount_points, amount_money, final_amount, method, receiver_phone) 
                             VALUES (?, ?, ?, ?, ?, ?)''',
                          (user_id, amount_points, amount_money, final_amount, method, receiver_phone))
            rid = cursor.lastrowid
            conn.commit()
            return rid
    
    def get_charge_request_details(self, request_id):
        """✅ جلب تفاصيل الشحن بأمان"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''SELECT cr.*, u.telegram_id, u.first_name, u.username 
                             FROM charge_requests cr 
                             JOIN users u ON cr.user_id = u.id 
                             WHERE cr.id = ?''', (request_id,))
            res = cursor.fetchone()
            return dict(res) if res else None
    
    def get_withdraw_details(self, request_id):
        """✅ جلب تفاصيل السحب"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''SELECT wr.*, u.telegram_id, u.first_name 
                             FROM withdrawal_requests wr 
                             JOIN users u ON wr.user_id = u.id 
                             WHERE wr.id = ?''', (request_id,))
            res = cursor.fetchone()
            return dict(res) if res else None
    
    def update_charge_status(self, request_id, status, admin_id):
        """✅ تحديث حالة الشحن مع إضافة النقاط بأمان"""
        allowed_statuses = ['pending', 'approved', 'rejected']
        if status not in allowed_statuses:
            raise ValueError(f"Invalid status: {status}")
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('BEGIN IMMEDIATE')
            try:
                cursor.execute('''UPDATE charge_requests 
                                 SET status = ?, processed_by = ?, processed_at = ? 
                                 WHERE id = ?''',
                              (status, admin_id, datetime.now(), request_id))
                
                if status == 'approved':
                    cursor.execute('SELECT user_id, points FROM charge_requests WHERE id = ?', (request_id,))
                    req = cursor.fetchone()
                    if req:
                        # ✅ تحديث النقاط باستعلام آمن
                        cursor.execute('UPDATE users SET points = points + ? WHERE id = ?',
                                     (req['points'], req['user_id']))
                        self._log_activity_internal(cursor, req['user_id'], 'charge_approved',
                                                  f'تم قبول شحن {req["points"]} نقطة', req['points'])
                elif status == 'rejected':
                    cursor.execute('SELECT user_id FROM charge_requests WHERE id = ?', (request_id,))
                    req = cursor.fetchone()
                    if req:
                        self._log_activity_internal(cursor, req['user_id'], 'charge_rejected',
                                                  'تم رفض طلب الشحن', 0)
                conn.commit()
            except:
                conn.rollback()
                raise
    
    def update_withdraw_status(self, request_id, status):
        """✅ تحديث حالة السحب"""
        allowed_statuses = ['pending', 'approved', 'rejected']
        if status not in allowed_statuses:
            raise ValueError(f"Invalid status: {status}")
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''UPDATE withdrawal_requests 
                             SET status = ?, processed_at = ? 
                             WHERE id = ?''',
                          (status, datetime.now(), request_id))
            conn.commit()
    
    def deduct_points(self, user_id, amount):
        """✅ خصم النقاط مع التحقق"""
        if not isinstance(amount, int) or amount <= 0:
            raise ValueError("Amount must be positive integer")
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET points = points - ? WHERE id = ? AND points >= ?',
                          (amount, user_id, amount))
            success = conn.total_changes > 0
            if success:
                self._log_activity_internal(cursor, user_id, 'points_deducted',
                                          f'تم خصم {amount} نقطة', -amount)
            conn.commit()
            return success
    
    def add_points(self, user_id, amount, description=''):
        """✅ إضافة نقاط"""
        if not isinstance(amount, int) or amount < 0:
            raise ValueError("Amount must be non-negative integer")
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET points = points + ? WHERE id = ?', (amount, user_id))
            if description:
                self._log_activity_internal(cursor, user_id, 'points_added', description, amount)
            conn.commit()
    
    def save_game(self, user_id, difficulty, puzzle=None, solution=None):
        """✅ حفظ لعبة مع تخزين JSON بأمان"""
        allowed_difficulties = ['easy', 'medium', 'hard', 'expert']
        if difficulty not in allowed_difficulties:
            raise ValueError(f"Invalid difficulty: {difficulty}")
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # ✅ تحويل المصفوفات إلى JSON للتخزين الآمن
            puzzle_json = json.dumps(puzzle) if puzzle else None
            solution_json = json.dumps(solution) if solution else None
            
            cursor.execute('''INSERT INTO games 
                             (user_id, difficulty, puzzle_data, solution_data) 
                             VALUES (?, ?, ?, ?)''',
                          (user_id, difficulty, puzzle_json, solution_json))
            gid = cursor.lastrowid
            conn.commit()
            return gid
    
    def complete_game(self, game_id, status='completed'):
        """✅ إكمال لعبة"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE games SET status = ?, completed_at = ? WHERE id = ?',
                          (status, datetime.now(), game_id))
            conn.commit()
    
    def get_game(self, game_id):
        """✅ جلب لعبة مع فك JSON"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM games WHERE id = ?', (game_id,))
            res = cursor.fetchone()
            if res:
                data = dict(res)
                # ✅ فك JSON عند القراءة
                if data.get('puzzle_data'):
                    try:
                        data['puzzle'] = json.loads(data['puzzle_data'])
                    except:
                        data['puzzle'] = None
                if data.get('solution_data'):
                    try:
                        data['solution'] = json.loads(data['solution_data'])
                    except:
                        data['solution'] = None
                return data
            return None
    
    def _log_activity_internal(self, cursor, user_id, action_type, description, points_change):
        """✅ تسجيل نشاط داخلي (ضمن معاملة)"""
        cursor.execute('''INSERT INTO activity_log (user_id, action_type, description, points_change) 
                         VALUES (?, ?, ?, ?)''',
                      (user_id, action_type, description, points_change))
    
    def get_user_history(self, user_id, limit=20):
        """✅ جلب سجل المستخدم"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 'charge' as type, amount_ls as amount, points, status, created_at 
                FROM charge_requests WHERE user_id = ?
                UNION ALL
                SELECT 'withdrawal' as type, amount_money as amount, points, status, created_at 
                FROM withdrawal_requests WHERE user_id = ?
                UNION ALL
                SELECT action_type as type, points_change as amount, 0 as points, description as status, created_at
                FROM activity_log WHERE user_id = ? AND action_type NOT IN ('charge_approved','charge_rejected','withdrawal_approved')
                ORDER BY created_at DESC LIMIT ?
            ''', (user_id, user_id, user_id, limit))
            return [dict(row) for row in cursor.fetchall()]

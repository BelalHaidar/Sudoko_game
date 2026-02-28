import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
import logging
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_url=None):
        self.db_url = db_url or os.environ.get('DATABASE_URL')
        self._init_db()
    
    @contextmanager
    def get_connection(self):
        conn = None
        try:
            # الاتصال بـ PostgreSQL مع تفعيل SSL للأمان
            conn = psycopg2.connect(self.db_url, sslmode='require')
            yield conn
        except Exception as e:
            logger.error(f"Database error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()
    
    def _init_db(self):
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # جدول المستخدمين
                cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    points INTEGER DEFAULT 100,
                    agreed_terms INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

                # جدول الشحن
                cursor.execute('''CREATE TABLE IF NOT EXISTS charge_requests (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    amount_ls INTEGER NOT NULL,
                    points INTEGER NOT NULL,
                    method TEXT,
                    sender_phone TEXT,
                    trans_id TEXT,
                    status TEXT DEFAULT 'pending',
                    processed_by BIGINT,
                    processed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

                # جدول الألعاب
                cursor.execute('''CREATE TABLE IF NOT EXISTS games (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    difficulty TEXT NOT NULL,
                    puzzle_data TEXT,
                    solution_data TEXT,
                    hints_used INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'playing',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP)''')
                
                conn.commit()

    def get_user_by_telegram_id(self, telegram_id):
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute('SELECT * FROM users WHERE telegram_id = %s', (telegram_id,))
                res = cursor.fetchone()
                return dict(res) if res else None

    def create_user(self, telegram_id, username, first_name):
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO users (telegram_id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (telegram_id) DO NOTHING',
                    (telegram_id, username, first_name)
                )
                conn.commit()

    # ✅ دالة إضافة النقاط (تُستخدم عند الفوز أو عند قبول الشحن)
    def add_points(self, user_id, amount, reason=""):
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE users SET points = points + %s WHERE id = %s', (amount, user_id))
                conn.commit()
                logger.info(f"Added {amount} points to user {user_id}. Reason: {reason}")

    def deduct_points(self, user_id, amount):
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE users SET points = points - %s WHERE id = %s AND points >= %s', (amount, user_id, amount))
                conn.commit()
                return cursor.rowcount > 0

    # ✅ دالة إنشاء طلب شحن (التي يستدعيها ملف app.py)
    def create_charge_request(self, user_id, amount_ls, points, method, sender_phone, trans_id):
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('''INSERT INTO charge_requests (user_id, amount_ls, points, method, sender_phone, trans_id) 
                                 VALUES (%s, %s, %s, %s, %s, %s) RETURNING id''', 
                              (user_id, amount_ls, points, method, sender_phone, trans_id))
                rid = cursor.fetchone()[0]
                conn.commit()
                return rid

    def save_game(self, user_id, difficulty, puzzle, solution):
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO games (user_id, difficulty, puzzle_data, solution_data) VALUES (%s, %s, %s, %s) RETURNING id',
                    (user_id, difficulty, json.dumps(puzzle), json.dumps(solution))
                )
                gid = cursor.fetchone()[0]
                conn.commit()
                return gid

    def get_game(self, game_id):
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute('SELECT * FROM games WHERE id = %s', (game_id,))
                res = cursor.fetchone()
                if res:
                    res = dict(res)
                    res['puzzle'] = json.loads(res['puzzle_data'])
                    res['solution'] = json.loads(res['solution_data'])
                return res

    def increment_hints(self, game_id):
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE games SET hints_used = hints_used + 1 WHERE id = %s', (game_id,))
                conn.commit()

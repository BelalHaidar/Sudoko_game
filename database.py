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
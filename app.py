import os
import json
import logging
from flask import Flask, render_template, request, jsonify
from flask_talisman import Talisman
from dotenv import load_dotenv

from database import Database
from sudoku import SudokuGenerator

# ✅ الإعدادات الأساسية
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())

# تأمين الرابط لـ Render (إجباري لضمان عمل HTTPS)
Talisman(app, force_https=False, content_security_policy=None)

# ربط قاعدة البيانات والمولد
db = Database()
generator = SudokuGenerator()

# ==================== مسارات Flask ====================

@app.route('/')
def home():
    return "Sudoku Game Engine is Running!", 200

@app.route('/play')
def play():
    try:
        tg_id = request.args.get('user')
        difficulty = request.args.get('difficulty', 'medium')
        
        if not tg_id:
            return "User ID is required", 400

        user = db.get_user_by_telegram_id(int(tg_id))
        if user and user['points'] >= 100:
            db.deduct_points(user['id'], 100)
            puzzle, solution = generator.generate_puzzle(difficulty)
            game_id = db.save_game(user['id'], difficulty, puzzle, solution)
            
            return render_template('game.html', 
                                 puzzle_json=json.dumps(puzzle), 
                                 game_id=game_id, 
                                 tg_id=tg_id, 
                                 difficulty=difficulty, 
                                 user_points=user['points']-100)
        
        return render_template('no_points.html', points=user['points'] if user else 0)
    except Exception as e:
        logger.error(f"Error in play route: {e}")
        return "Internal Server Error", 500

@app.route('/check_solution', methods=['POST'])
def check_solution():
    try:
        data = request.get_json()
        game_id = data.get('game_id')
        user_board = data.get('board') # تأكد أن الواجهة ترسل board (المصفوفة كاملة)

        game = db.get_game(game_id)
        if not game:
            return jsonify({'success': False, 'error': 'اللعبة غير موجودة'}), 404

        # مقارنة مصفوفة اللاعب مع الحل المخزن
        if user_board == game['solution']:
            points_map = {'easy': 500, 'medium': 1000, 'hard': 1500, 'expert': 5000}
            reward = points_map.get(game['difficulty'], 0)
            db.add_points(game['user_id'], reward, reason=f"Won {game['difficulty']} game")
            return jsonify({'success': True, 'reward': reward})
        else:
            return jsonify({'success': False, 'error': 'الحل غير صحيح، حاول مجدداً!'})

    except Exception as e:
        logger.error(f"Error in check_solution: {e}")
        return jsonify({'success': False, 'error': 'خطأ داخلي في السيرفر'}), 500

@app.route('/health')
def health():
    return "OK", 200

if __name__ == '__main__':
    # على Render يتم استخدام Gunicorn عادة، ولكن هذا للتشغيل المحلي
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

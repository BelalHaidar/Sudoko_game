import os
import json
import logging
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from database import Database
from sudoku import SudokuGenerator

# ✅ تحميل متغيرات البيئة
load_dotenv()

# ✅ إعداد التسجيل الآمن (بدون تسريب أسرار)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ✅ تهيئة التطبيق
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # جلسة لمدة ساعة

# ✅ حماية HTTPS وHeaders الأمان
Talisman(app,
         force_https=True,
         strict_transport_security=True,
         strict_transport_security_max_age=31536000,
         content_security_policy={
             'default-src': "'self'",
             'script-src': "'self'",
             'style-src': "'self' 'unsafe-inline'",
             'img-src': "'self' data:",
             'font-src': "'self'",
             'connect-src': "'self'"
         },
         frame_options='DENY',
         x_content_type_options=True,
         x_xss_protection=True)

# ✅ تحديد معدل الطلبات (Rate Limiting)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# ✅ تهيئة المكونات
db = Database()
generator = SudokuGenerator()

# ✅ ثوابت من متغيرات البيئة
REWARDS = {'easy': 500, 'medium': 1000, 'hard': 1500, 'expert': 5000}
HINT_COST = int(os.environ.get('HINT_COST', 50))
GAME_COST = int(os.environ.get('GAME_COST', 100))
POINTS_PER_SYP = int(os.environ.get('POINTS_PER_SYP', 10))
INTERNAL_API_KEY = os.environ.get('INTERNAL_API_KEY')

if not INTERNAL_API_KEY:
    logger.warning("⚠️ INTERNAL_API_KEY not set - internal endpoints unprotected!")

# ✅ Decorator لحماية المسارات الداخلية
def require_internal_api(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not INTERNAL_API_KEY:
            return jsonify({'error': 'Internal API not configured'}), 500
        
        api_key = request.headers.get('X-Internal-Key')
        if not api_key or api_key != INTERNAL_API_KEY:
            logger.warning(f"Unauthorized API access attempt from {request.remote_addr}")
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

# ✅ Headers أمان إضافية
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    response.headers['Pragma'] = 'no-cache'
    return response

# ✅ صفحة رئيسية بسيطة
@app.route('/')
def index():
    return jsonify({'status': 'ok', 'message': 'Sudoku Game API is running'})

# ✅ مسار اللعبة الرئيسي
@app.route('/play')
@limiter.limit("30 per minute")  # ✅ منع الإساءة
def play():
    try:
        tg_id = request.args.get('user')
        difficulty = request.args.get('difficulty', 'medium')
        
        # ✅ التحقق من صحة المدخلات
        if not tg_id or not tg_id.isdigit():
            return jsonify({'error': 'معرف المستخدم غير صالح'}), 400
        
        tg_id = int(tg_id)
        if difficulty not in REWARDS:
            difficulty = 'medium'
        
        user = db.get_user_by_telegram_id(tg_id)
        
        if not user:
            return render_template('no_points.html', points=0, error='user_not_found')
        
        if user['points'] < GAME_COST:
            return render_template('no_points.html', 
                                 points=user['points'], 
                                 needed=GAME_COST - user['points'])

        if db.deduct_points(user['id'], GAME_COST):
            puzzle, solution = generator.generate_puzzle(difficulty)
            game_id = db.save_game(user['id'], difficulty, puzzle, solution)
            
            puzzle_json = json.dumps(puzzle)
            solution_json = json.dumps(solution)
            
            return render_template('game.html', 
                                 puzzle_json=puzzle_json,
                                 solution_json=solution_json,
                                 game_id=game_id, 
                                 tg_id=tg_id, 
                                 difficulty=difficulty, 
                                 user_points=user['points'] - GAME_COST,
                                 hint_cost=HINT_COST)
        
        return render_template('no_points.html', 
                             points=user['points'], 
                             needed=GAME_COST - user['points'])
                             
    except Exception as e:
        logger.error(f"Error in /play: {e}", exc_info=True)
        # ✅ لا نكشف تفاصيل الخطأ للمستخدم
        return jsonify({'error': 'حدث خطأ داخلي'}), 500

# ✅ مسار التلميح - محمي بمفتاح API داخلي
@app.route('/get_hint', methods=['POST'])
@limiter.limit("10 per minute")
@require_internal_api
def get_hint():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'بيانات غير صالحة'}), 400
        
        game_id = data.get('game_id')
        tg_id = data.get('tg_id')
        
        if not game_id or not tg_id:
            return jsonify({'success': False, 'error': 'معرفات مفقودة'}), 400
        
        user = db.get_user_by_telegram_id(int(tg_id))
        if not user or user['points'] < HINT_COST:
            return jsonify({'success': False, 'error': 'رصيد غير كافي'})
        
        game = db.get_game(game_id)
        if not game:
            return jsonify({'success': False, 'error': 'اللعبة غير موجودة'}), 404
        
        puzzle = game.get('puzzle')
        solution = game.get('solution')
        
        if not puzzle or not solution:
            return jsonify({'success': False, 'error': 'بيانات اللعبة غير متوفرة'})
        
        hint = generator.get_hint(puzzle, solution)
        if hint and db.deduct_points(user['id'], HINT_COST):
            return jsonify({'success': True, 'hint': hint, 'new_points': user['points'] - HINT_COST})
        
        return jsonify({'success': False, 'error': 'لا توجد خلايا فارغة'})
        
    except Exception as e:
        logger.error(f"Error in /get_hint: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'خطأ داخلي'}), 500

# ✅ مسار التحقق من الحل - محمي بمفتاح API داخلي
@app.route('/check_solution', methods=['POST'])
@limiter.limit("20 per minute")
@require_internal_api
def check_solution():
    try:
        data = request.get_json()
        if not data or 'board' not in data:
            return jsonify({'success': False, 'error': 'بيانات غير صالحة'}), 400
        
        board = data.get('board')
        if not isinstance(board, list) or len(board) != 9:
            return jsonify({'success': False, 'error': 'لوحة غير صالحة'}), 400
        
        if SudokuGenerator.check_solution(board):
            game = db.get_game(data.get('game_id'))
            if not game:
                return jsonify({'success': False, 'error': 'اللعبة غير موجودة'}), 404
            
            points = REWARDS.get(game['difficulty'], 500)
            db.add_points(game['user_id'], points)
            db.complete_game(data.get('game_id'), 'won')
            
            return jsonify({'success': True, 'reward': points, 'message': '🎉 مبروك! حل صحيح'})
        
        db.complete_game(data.get('game_id'), 'lost')
        return jsonify({'success': False, 'message': '❌ الحل غير صحيح'})
        
    except Exception as e:
        logger.error(f"Error in /check_solution: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'خطأ داخلي'}), 500

# ✅ مسار لعبة جديدة - محمي بمفتاح API داخلي
@app.route('/new_game', methods=['POST'])
@limiter.limit("10 per minute")
@require_internal_api
def new_game():
    try:
        data = request.get_json()
        tg_id = data.get('tg_id')
        difficulty = data.get('difficulty', 'medium')
        
        if not tg_id or difficulty not in REWARDS:
            return jsonify({'success': False, 'error': 'بيانات غير صالحة'}), 400
        
        user = db.get_user_by_telegram_id(int(tg_id))
        if not user or user['points'] < GAME_COST:
            return jsonify({'success': False, 'error': 'رصيد غير كافي'})
        
        if db.deduct_points(user['id'], GAME_COST):
            puzzle, solution = generator.generate_puzzle(difficulty)
            game_id = db.save_game(user['id'], difficulty, puzzle, solution)
            
            return jsonify({
                'success': True, 
                'game_id': game_id,
                'puzzle': puzzle,
                'solution': solution,
                'new_points': user['points'] - GAME_COST
            })
        
        return jsonify({'success': False, 'error': 'فشل في بدء اللعبة'})
        
    except Exception as e:
        logger.error(f"Error in /new_game: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'خطأ داخلي'}), 500

# ✅ مسار الصحة للتحقق من عمل الخادم
@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'database': 'sqlite'}), 200

# ✅ معالجة الأخطاء العامة
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal error: {e}", exc_info=True)
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({'error': 'Too many requests, please try again later'}), 429

if __name__ == '__main__':
    # ✅ في التطوير فقط - في الإنتاج استخدم gunicorn
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') != 'production'
    app.run(host='0.0.0.0', port=port, debug=debug)

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from database import Database
from sudoku import SudokuGenerator
import json
import os
import random  # تم نقل الاستيراد للأعلى لضمان كفاءة الأداء
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-this-in-production-2024'  # يجب تغيير هذا في بيئة الإنتاج

db = Database()
generator = SudokuGenerator()

# Decorator للتحقق من صلاحيات المشرف
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        admin_id = session.get('admin_id')
        if not admin_id:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/play')
def play():
    # استلام الـ Telegram ID من الرابط
    tg_id = request.args.get('user')
    difficulty = request.args.get('difficulty', 'medium')
    
    if not tg_id:
        return "❌ خطأ: لم يتم توفير معرف المستخدم."
    
    # البحث عن المستخدم في قاعدة البيانات باستخدام Telegram ID
    user_data = db.get_user_by_telegram_id(int(tg_id))
    
    if not user_data:
        # محاولة أخيرة: إذا لم يوجد، نقوم بإنشائه (لزيادة الأمان)
        return "❌ المستخدم غير موجود. يرجى العودة للبوت والضغط على /start مجدداً."
    
    # استخراج البيانات بناءً على ترتيب الأعمدة في database.py
    # (id, telegram_id, username, first_name, points, ...)
    user_db_id = user_data[0]
    points = user_data[4]
    
    if points < 100:
        return render_template('no_points.html', user_id=tg_id)
    
    # خصم النقاط وبدء اللعبة
    db.deduct_points(user_db_id, 100, f"بدء لعبة {difficulty}")
    puzzle, solution = generator.generate_puzzle(difficulty)
    
    game_data = {'puzzle': puzzle, 'solution': solution, 'difficulty': difficulty}
    game_id = db.save_game(user_db_id, json.dumps(game_data), difficulty)
    
    return render_template('game.html', 
                         puzzle=puzzle, 
                         game_id=game_id, 
                         user_id=user_db_id, # نمرر الـ ID الداخلي للعمليات اللاحقة
                         tg_id=tg_id,
                         difficulty=difficulty, 
                         user_points=points-100)

@app.route('/check_solution', methods=['POST'])
def check_solution():
    data = request.json
    board = data['board']
    
    # استخدام الدالة الثابتة للتحقق من الحل
    if SudokuGenerator.check_solution(board):
        return jsonify({
            'success': True,
            'message': '🎉 الحل صحيح!'
        })
    else:
        return jsonify({
            'success': False,
            'message': '❌ الحل غير صحيح'
        })

@app.route('/complete_game', methods=['POST'])
def complete_game():
    data = request.json
    user_id = data['user_id']
    points_earned = data['points']
    difficulty = data['difficulty']
    
    # إضافة النقاط للمستخدم
    db.add_points(user_id, points_earned, f"إكمال مستوى {difficulty}")
    
    # الحصول على النقاط الجديدة
    new_points = db.get_user_points(user_id)
    
    return jsonify({
        'success': True,
        'new_points': new_points
    })

@app.route('/get_hint', methods=['POST'])
def get_hint():
    data = request.json
    user_id = data['user_id']
    game_id = data['game_id']
    current_board = data.get('current_board') # استلام الحالة الحالية للوحة لتقديم تلميح ذكي
    
    # التحقق من وجود نقاط كافية للتلميح
    points = db.get_user_points(user_id)
    if points < 50:
        return jsonify({
            'success': False,
            'message': '❌ لا تملك نقاط كافية (تحتاج 50 نقطة)'
        })
    
    # الحصول على الحل الصحيح من قاعدة البيانات
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT game_data FROM games WHERE id = ?', (game_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return jsonify({
            'success': False,
            'message': '❌ لم يتم العثور على اللعبة'
        })
    
    game_data = json.loads(result[0])
    solution = game_data['solution']

    # منطق محسّن: اختيار خلية فارغة عشوائياً من الخلايا التي لم يحلها المستخدم بعد
    empty_cells = []
    if current_board:
        empty_cells = [(r, c) for r in range(9) for c in range(9) if current_board[r][c] == 0]
    
    if not empty_cells:
        # إذا لم يتم إرسال اللوحة أو كانت ممتلئة، نختار عشوائياً تماماً
        row, col = random.randint(0, 8), random.randint(0, 8)
    else:
        row, col = random.choice(empty_cells)
    
    hint_value = solution[row][col]
    
    # خصم نقاط التلميح
    db.deduct_points(user_id, 50, "شراء تلميح")
    new_points = db.get_user_points(user_id)
    
    return jsonify({
        'success': True,
        'row': row,
        'col': col,
        'value': hint_value,
        'new_points': new_points
    })

@app.route('/charge_points')
def charge_points():
    user_id = request.args.get('user')
    return render_template('charge.html', user_id=user_id)

@app.route('/create_charge_request', methods=['POST'])
def create_charge_request():
    data = request.json
    user_id = data['user_id']
    method = data['method']
    amount = data['amount']
    phone = data.get('phone', '')
    
    points_to_add = {
        '1000': 100,
        '2500': 250,
        '5000': 500,
        '10000': 1100
    }.get(amount, 100)
    
    request_id = db.create_charge_request(user_id, int(amount), points_to_add, method, phone)
    
    return jsonify({
        'success': True,
        'request_id': request_id,
        'message': 'تم إرسال طلب الشحن بنجاح'
    })

# ==================== مسارات الإدارة ====================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == 'admin123': # يجب تغييرها لكلمة سر قوية
            session['admin_id'] = 1
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html', error='كلمة المرور غير صحيحة')
    return render_template('admin_login.html')

@app.route('/admin')
@admin_required
def admin_dashboard():
    page = int(request.args.get('page', 1))
    stats = db.get_system_stats()
    users, total = db.get_all_users(page=page)
    charge_requests = db.get_charge_requests('pending')
    transactions, _ = db.get_all_transactions(page=1, per_page=20)
    
    total_pages = (total + 19) // 20
    
    return render_template('admin.html',
                         stats=stats,
                         users=users,
                         charge_requests=charge_requests,
                         transactions=transactions,
                         current_page=page,
                         total_pages=total_pages)

@app.route('/admin/approve_charge/<int:request_id>', methods=['POST'])
@admin_required
def admin_approve_charge(request_id):
    db.update_charge_status(request_id, 'approved', session.get('admin_id'))
    return jsonify({'success': True})

@app.route('/admin/adjust_points', methods=['POST'])
@admin_required
def admin_adjust_points():
    data = request.json
    db.adjust_user_points(data['user_id'], data['points'], 'تعديل يدوي', session.get('admin_id'))
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)

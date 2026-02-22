from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from database import Database
from sudoku import SudokuGenerator
import json
import os
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-this-in-production-2024'

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
    user_id = request.args.get('user')
    difficulty = request.args.get('difficulty', 'medium')
    
    if not user_id:
        return "❌ الرجاء الدخول عبر بوت تيليغرام"
    
    # التحقق من وجود نقاط كافية
    user_data = db.get_user_by_telegram_id(int(user_id))
    if not user_data:
        return "❌ المستخدم غير موجود"
    
    points = user_data[5]
    user_db_id = user_data[0]
    
    # خصم 100 نقطة لبدء اللعبة
    if points < 100:
        return render_template('no_points.html', user_id=user_id)
    
    db.deduct_points(user_db_id, 100, f"بدء لعبة {difficulty}")
    
    # توليد لغز جديد
    puzzle, solution = generator.generate_puzzle(difficulty)
    
    # حفظ اللعبة في قاعدة البيانات
    game_data = {
        'puzzle': puzzle,
        'solution': solution,
        'difficulty': difficulty
    }
    game_id = db.save_game(user_db_id, json.dumps(game_data), difficulty)
    
    return render_template('game.html', 
                         puzzle=puzzle, 
                         game_id=game_id,
                         user_id=user_id,
                         difficulty=difficulty,
                         user_points=points-100)

@app.route('/check_solution', methods=['POST'])
def check_solution():
    data = request.json
    board = data['board']
    game_id = data['game_id']
    user_id = data['user_id']
    
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
    time_taken = data.get('time', 0)
    
    # إضافة النقاط للمستخدم
    db.add_points(user_id, points_earned, f"إكمال مستوى {difficulty} في {time_taken} ثانية")
    
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
    
    # التحقق من وجود نقاط كافية للتلميح
    points = db.get_user_points(user_id)
    
    if points < 50:
        return jsonify({
            'success': False,
            'message': '❌ لا تملك 50 نقطة كافية للتلميح'
        })
    
    # خصم نقاط التلميح
    db.deduct_points(user_id, 50, "شراء تلميح")
    
    # الحصول على تلميح عشوائي
    import random
    row = random.randint(0, 8)
    col = random.randint(0, 8)
    
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
    hint_value = game_data['solution'][row][col]
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
    """إنشاء طلب شحن جديد"""
    data = request.json
    user_id = data['user_id']
    method = data['method']
    amount = data['amount']
    phone = data.get('phone', '')
    
    # تحويل المبلغ إلى نقاط
    points_to_add = {
        '1000': 100,
        '2500': 250,
        '5000': 500,
        '10000': 1100
    }.get(amount, 100)
    
    # إنشاء طلب الشحن
    request_id = db.create_charge_request(user_id, int(amount), points_to_add, method, phone)
    
    return jsonify({
        'success': True,
        'request_id': request_id,
        'message': 'تم إرسال طلب الشحن بنجاح'
    })

@app.route('/profile/<int:user_id>')
def profile(user_id):
    user = db.get_user_by_telegram_id(user_id)
    if user:
        transactions = db.get_user_transactions(user[0], 20)
        return render_template('profile.html', user=user, transactions=transactions)
    return "المستخدم غير موجود"

@app.route('/leaderboard')
def leaderboard():
    leaders = db.get_leaderboard(10)
    return render_template('leaderboard.html', leaders=leaders)

# ==================== مسارات الإدارة ====================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """صفحة دخول المشرف"""
    if request.method == 'POST':
        password = request.form.get('password')
        # غير كلمة المرور هذه بكلمة قوية
        if password == 'admin123':
            session['admin_id'] = 1
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html', error='كلمة المرور غير صحيحة')
    
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    """تسجيل خروج المشرف"""
    session.pop('admin_id', None)
    return redirect(url_for('admin_login'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    """لوحة تحكم المشرف الرئيسية"""
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

@app.route('/admin/search_users')
@admin_required
def admin_search_users():
    """البحث عن مستخدمين"""
    query = request.args.get('q', '')
    users = db.search_users(query)
    return jsonify({'users': users})

@app.route('/admin/approve_charge/<int:request_id>', methods=['POST'])
@admin_required
def admin_approve_charge(request_id):
    """الموافقة على طلب شحن"""
    db.update_charge_status(request_id, 'approved', session.get('admin_id'))
    return jsonify({'success': True})

@app.route('/admin/reject_charge/<int:request_id>', methods=['POST'])
@admin_required
def admin_reject_charge(request_id):
    """رفض طلب شحن"""
    db.update_charge_status(request_id, 'rejected', session.get('admin_id'))
    return jsonify({'success': True})

@app.route('/admin/adjust_points', methods=['POST'])
@admin_required
def admin_adjust_points():
    """تعديل نقاط مستخدم"""
    data = request.json
    user_id = data['user_id']
    points = data['points']
    
    db.adjust_user_points(user_id, points, 'تعديل يدوي', session.get('admin_id'))
    return jsonify({'success': True})

@app.route('/admin/user/<int:user_id>')
@admin_required
def admin_user_detail(user_id):
    """تفاصيل مستخدم معين"""
    user = db.get_user_by_telegram_id(user_id)
    if not user:
        return "المستخدم غير موجود"
    
    transactions = db.get_user_transactions(user[0], 50)
    charge_requests = db.get_charge_requests_by_user(user[0])
    
    return render_template('admin_user.html', 
                         user=user, 
                         transactions=transactions,
                         charge_requests=charge_requests)

@app.route('/admin/stats')
@admin_required
def admin_stats_json():
    """إحصائيات النظام بصيغة JSON"""
    stats = db.get_system_stats()
    return jsonify(stats)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)

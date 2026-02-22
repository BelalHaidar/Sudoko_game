from flask import Flask, render_template, request, jsonify, session
from database import Database
from sudoku import SudokuGenerator
import json

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

db = Database()
generator = SudokuGenerator()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/play')
def play():
    user_id = request.args.get('user')
    difficulty = request.args.get('difficulty', 'medium')
    
    if not user_id:
        return "❌ الرجاء الدخول عبر بوت تيليغرام"
    
    # توليد لغز جديد
    puzzle, solution = generator.generate_puzzle(difficulty)
    
    # حفظ اللعبة في قاعدة البيانات
    game_id = db.save_game(user_id, json.dumps(puzzle), difficulty)
    
    return render_template('game.html', 
                         puzzle=puzzle, 
                         game_id=game_id,
                         user_id=user_id,
                         difficulty=difficulty)

@app.route('/check_solution', methods=['POST'])
def check_solution():
    data = request.json
    board = data['board']
    game_id = data['game_id']
    user_id = data['user_id']
    
    if SudokuGenerator.check_solution(board):
        # حساب النقاط حسب الصعوبة
        difficulty_points = {
            'easy': 20,
            'medium': 40,
            'hard': 60
        }
        
        # الحصول على صعوبة اللعبة من قاعدة البيانات
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT difficulty FROM games WHERE id = ?', (game_id,))
        difficulty = cursor.fetchone()[0]
        conn.close()
        
        points = difficulty_points.get(difficulty, 20)
        
        # إضافة النقاط
        db.add_points(user_id, points, f"إكمال لغز {difficulty}")
        db.complete_game(game_id, points)
        
        return jsonify({
            'success': True,
            'points': points,
            'message': f'🎉 تهانينا! أكملت اللغز وحصلت على {points} نقطة!'
        })
    else:
        return jsonify({
            'success': False,
            'message': '❌ الحل غير صحيح. حاول مرة أخرى!'
        })

@app.route('/profile/<int:user_id>')
def profile(user_id):
    user = db.get_user_by_telegram_id(user_id)
    if user:
        return render_template('profile.html', user=user)
    return "المستخدم غير موجود"

@app.route('/leaderboard')
def leaderboard():
    leaders = db.get_leaderboard()
    return render_template('leaderboard.html', leaders=leaders)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
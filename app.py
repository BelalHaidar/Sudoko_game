import os
import json
import logging
import asyncio
import threading
import time
from functools import wraps
from datetime import datetime

from flask import Flask, render_template, request, jsonify
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

# مكتبات تيليجرام
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, MessageHandler, filters, ConversationHandler
)
from telegram.error import BadRequest, Conflict

# استيراد المكونات المحلية
from database import Database
from sudoku import SudokuGenerator

# تحميل الإعدادات
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- إعدادات تطبيق Flask ---
app = Flask(__name__, template_folder='.')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())

Talisman(app, force_https=True, frame_options='DENY')
limiter = Limiter(app=app, key_func=get_remote_address, storage_uri="memory://")

# تهيئة قاعدة البيانات بالمسار المطلق لتجنب أخطاء الوصول
db_path = os.environ.get('DATABASE_PATH', os.path.join(os.getcwd(), 'sudoku.db'))
db = Database(db_path=db_path)
generator = SudokuGenerator()

# الثوابت المعتمدة (نظام النقاط والأسعار)
REWARDS = {'easy': 500, 'medium': 1000, 'hard': 1500, 'expert': 5000}
GAME_COST = 100
HINT_COST = 50
POINTS_PER_SYP = 10
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GAME_URL = os.environ.get('GAME_URL', '').rstrip('/')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))

# حالات المحادثة
C_PKG, C_METH, C_PHONE, C_TRANS = range(4)
W_AMT, W_PHONE = range(10, 12)

# باقات الشحن والسحب المطلوبة
CHARGE_PACKAGES = [(50, 500), (100, 1000), (300, 3000), (500, 5000), (1000, 10000)]
WITHDRAW_PACKAGES = [100, 300, 500, 1000]

# --- مسارات Flask (الموقع الإلكتروني) ---

@app.route('/')
def index():
    return jsonify({'service': 'Sudoku Game & Bot', 'status': 'online'})

@app.route('/play')
def play():
    try:
        tg_id = request.args.get('user')
        difficulty = request.args.get('difficulty', 'medium')
        if not tg_id or not tg_id.isdigit(): return "معرف غير صالح", 400
        
        user = db.get_user_by_telegram_id(int(tg_id))
        if not user or user['points'] < GAME_COST:
            return render_template('no_points.html', points=user['points'] if user else 0, needed=GAME_COST-(user['points'] if user else 0))

        if db.deduct_points(user['id'], GAME_COST):
            puzzle, solution = generator.generate_puzzle(difficulty)
            game_id = db.save_game(user['id'], difficulty, puzzle, solution)
            return render_template('game.html', puzzle_json=json.dumps(puzzle), solution_json=json.dumps(solution), game_id=game_id, tg_id=tg_id, difficulty=difficulty, user_points=user['points'] - GAME_COST, hint_cost=HINT_COST)
    except Exception as e:
        logger.error(f"Play error: {e}")
        return "Internal Error", 500

@app.route('/check_solution', methods=['POST'])
def check_solution():
    data = request.get_json()
    board = data.get('board')
    if SudokuGenerator.check_solution(board):
        game = db.get_game(data.get('game_id'))
        reward = REWARDS.get(game['difficulty'], 500)
        db.add_points(game['user_id'], reward, f"Won {game['difficulty']} game")
        db.complete_game(data.get('game_id'), 'won')
        return jsonify({'success': True, 'reward': reward, 'message': 'حل صحيح! 🎉', 'reset_timer': True})
    return jsonify({'success': False, 'message': 'الحل غير صحيح، حاول مجدداً', 'reset_timer': True})

# --- وظائف البوت المساعدة ---

async def safe_edit(update, text, reply_markup=None):
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    except BadRequest: pass

async def show_main_menu(update):
    uid = update.effective_user.id if not update.callback_query else update.callback_query.from_user.id
    user = db.get_user_by_telegram_id(uid)
    text = f"🧩 **القائمة الرئيسية**\n💰 رصيدك: {user['points']} نقطة"
    kb = [[InlineKeyboardButton("🎯 ابدأ اللعب", callback_data='choose_level')],
          [InlineKeyboardButton("💳 شحن", callback_data='start_charge'), InlineKeyboardButton("💰 سحب", callback_data='start_withdraw')],
          [InlineKeyboardButton("👤 حسابي", callback_data='profile'), InlineKeyboardButton("📜 السجل", callback_data='history')]]
    await safe_edit(update, text, InlineKeyboardMarkup(kb))

# --- نظام الشحن والسحب وتفاصيل الحساب ---

async def charge_trans_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.message.text
    pkg = context.user_data['c_pkg'].split('_')
    user = db.get_user_by_telegram_id(update.effective_user.id)
    rid = db.create_charge_request(user['id'], int(pkg[1]), int(pkg[2]), context.user_data['c_meth'], context.user_data['c_phone'], tid)
    
    admin_msg = f"🔔 **شحن جديد #{rid}**\n👤 {update.effective_user.first_name}\n🆔 `{update.effective_user.id}`\n📦 {pkg[1]}ل.س\n📱 {context.user_data['c_phone']}\n🔢 `{tid}`"
    admin_kb = [[InlineKeyboardButton("✅ قبول", callback_data=f"appc_{rid}"), InlineKeyboardButton("❌ رفض", callback_data=f"rejc_{rid}")]]
    await context.bot.send_message(ADMIN_ID, admin_msg, reply_markup=InlineKeyboardMarkup(admin_kb), parse_mode='Markdown')
    await update.message.reply_text("✅ تم استلام طلبك! سيتم تحديث رصيدك بعد التحقق.")
    return ConversationHandler.END

async def handle_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, rid = query.data[:4], int(query.data[5:])
    await query.answer()
    if action == "appc":
        db.update_charge_status(rid, 'approved', query.from_user.id)
        info = db.get_charge_request_details(rid)
        await context.bot.send_message(info['telegram_id'], f"🎉 تم قبول شحن {info['points']} نقطة!")
    elif action == "rejc":
        db.update_charge_status(rid, 'rejected', query.from_user.id)
        info = db.get_charge_request_details(rid)
        await context.bot.send_message(info['telegram_id'], "❌ يرجى التأكد من رقم العملية.")
    await query.edit_message_text(f"✅ تم تنفيذ الإجراء على الطلب #{rid}")

# --- تشغيل البوت في خيط خلفي مع معالجة الـ Conflict ---
def run_bot_loop():
    while True:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            application = Application.builder().token(BOT_TOKEN).build()
            
            # (تضاف هنا كافة الـ handlers الخاصة بـ ConversationHandler و CommandHandler)
            application.add_handler(CommandHandler("start", lambda u,c: db.create_user(u.effective_user.id, u.effective_user.username, u.effective_user.first_name) or asyncio.run_coroutine_threadsafe(show_main_menu(u), loop)))
            application.add_handler(CallbackQueryHandler(handle_admin, pattern='^(appc|rejc)_'))
            application.add_handler(CallbackQueryHandler(lambda u,c: asyncio.run_coroutine_threadsafe(show_main_menu(u), loop), pattern='^back_to_menu$'))
            
            logger.info("🤖 Bot worker starting...")
            application.run_polling(drop_pending_updates=True, stop_signals=None, close_loop=False)
        except Conflict:
            time.sleep(10) # انتظار إغلاق النسخة القديمة
        except Exception as e:
            logger.error(f"Bot Error: {e}")
            time.sleep(5)

threading.Thread(target=run_bot_loop, name="BotThread", daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

import os
import json
import logging
import asyncio
import threading
import time
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

# --- إعدادات Flask ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__, template_folder=BASE_DIR)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', '46815f999dedfe11163165db67aa86d645fb9b4ed4fcd45d9358e6b019cc5165')

Talisman(app, force_https=True, frame_options='DENY')
limiter = Limiter(app=app, key_func=get_remote_address, storage_uri="memory://")

# تهيئة قاعدة البيانات
db_path = os.environ.get('DATABASE_PATH', os.path.join(BASE_DIR, 'sudoku.db'))
db = Database(db_path=db_path)
generator = SudokuGenerator()

# الثوابت
REWARDS = {'easy': 500, 'medium': 1000, 'hard': 1500, 'expert': 5000}
GAME_COST = 100
HINT_COST = 50
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GAME_URL = os.environ.get('GAME_URL', '').rstrip('/')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '8492865250'))

# حالات المحادثة
C_PKG, C_METH, C_PHONE, C_TRANS = range(4)
W_AMT, W_PHONE = range(10, 12)

CHARGE_PACKAGES = [(50, 500), (100, 1000), (300, 3000), (500, 5000), (1000, 10000)]
WITHDRAW_PACKAGES = [100, 300, 500, 1000]

# --- مسارات Flask ---

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
            
            # ✅ تمرير البيانات كـ JSON آمن للمتصفح لضمان ظهور الأرقام
            return render_template('game.html', 
                                 puzzle_json=json.dumps(puzzle), 
                                 solution_json=json.dumps(solution), 
                                 game_id=game_id, tg_id=tg_id, 
                                 difficulty=difficulty, 
                                 user_points=user['points'] - GAME_COST, 
                                 hint_cost=HINT_COST)
    except Exception as e:
        logger.error(f"Play error: {e}")
        return "Internal Error", 500

@app.route('/check_solution', methods=['POST'])
def check_solution():
    data = request.get_json()
    if SudokuGenerator.check_solution(data.get('board')):
        game = db.get_game(data.get('game_id'))
        reward = REWARDS.get(game['difficulty'], 500)
        db.add_points(game['user_id'], reward, f"فوز بمستوى {game['difficulty']}")
        db.complete_game(data.get('game_id'), 'won')
        return jsonify({'success': True, 'reward': reward, 'message': 'حل صحيح! 🎉', 'reset_timer': True})
    return jsonify({'success': False, 'message': 'الحل غير صحيح', 'reset_timer': True})

# --- وظائف البوت ---

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_user_by_telegram_id(user_id)
    text = f"🧩 **القائمة الرئيسية**\n💰 رصيدك: {user['points']} نقطة"
    kb = [
        [InlineKeyboardButton("🎯 ابدأ اللعب", callback_data='choose_level')],
        [InlineKeyboardButton("💳 شحن", callback_data='start_charge'), InlineKeyboardButton("💰 سحب", callback_data='start_withdraw')],
        [InlineKeyboardButton("👤 حسابي", callback_data='profile'), InlineKeyboardButton("📜 السجل", callback_data='history')]
    ]
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

# --- نظام الشحن (Conversation) ---

async def start_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(f"📦 {s}ل.س ({p}ن)", callback_data=f"cp_{s}_{p}")] for s, p in CHARGE_PACKAGES]
    kb.append([InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')])
    await update.callback_query.edit_message_text("💳 اختر باقة الشحن:", reply_markup=InlineKeyboardMarkup(kb))
    return C_PKG

async def charge_pkg_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_pkg'] = update.callback_query.data
    kb = [[InlineKeyboardButton("🇸🇾 سيرياتيل كاش", callback_data='cm_Syriatel')], [InlineKeyboardButton("🟡 MTN كاش", callback_data='cm_MTN')]]
    await update.callback_query.edit_message_text("🏦 اختر طريقة الدفع:", reply_markup=InlineKeyboardMarkup(kb))
    return C_METH

async def charge_trans_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.message.text
    pkg = context.user_data.get('c_pkg', '').split('_')
    user = db.get_user_by_telegram_id(update.effective_user.id)
    rid = db.create_charge_request(user['id'], int(pkg[1]), int(pkg[2]), context.user_data.get('c_meth'), context.user_data.get('c_phone'), tid)
    
    admin_msg = f"🔔 **شحن جديد #{rid}**\n👤 {update.effective_user.first_name}\n🆔 `{update.effective_user.id}`\n📦 {pkg[1]}ل.س\n📱 {context.user_data.get('c_phone')}\n🔢 `{tid}`"
    admin_kb = [[InlineKeyboardButton("✅ قبول", callback_data=f"appc_{rid}"), InlineKeyboardButton("❌ رفض", callback_data=f"rejc_{rid}")]]
    await context.bot.send_message(ADMIN_ID, admin_msg, reply_markup=InlineKeyboardMarkup(admin_kb), parse_mode='Markdown')
    await update.message.reply_text("✅ تم استلام طلبك! سيتم تحديث رصيدك بعد التحقق.")
    return ConversationHandler.END

# --- تشغيل البوت في خيط خلفي ---
def run_bot_worker():
    while True:
        try:
            # إنشاء حلقة أحداث جديدة لكل محاولة لتجنب Future Error
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            application = Application.builder().token(BOT_TOKEN).build()
            
            charge_h = ConversationHandler(
                entry_points=[CallbackQueryHandler(start_charge, pattern='^start_charge$')],
                states={
                    C_PKG: [CallbackQueryHandler(charge_pkg_selected, pattern='^cp_')],
                    C_METH: [CallbackQueryHandler(lambda u,c: c.user_data.update({'c_meth':u.callback_query.data.split('_')[1]}) or u.callback_query.edit_message_text("📱 أرسل رقم هاتف المحول منه:") or C_PHONE, pattern='^cm_')],
                    C_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: c.user_data.update({'c_phone':u.message.text}) or u.message.reply_text("🔢 أرسل رقم العملية:") or C_TRANS)],
                    C_TRANS: [MessageHandler(filters.TEXT & ~filters.COMMAND, charge_trans_received)]
                },
                fallbacks=[CallbackQueryHandler(show_main_menu, pattern='^back_to_menu$')]
            )

            application.add_handler(charge_h)
            application.add_handler(CommandHandler("start", lambda u,c: db.create_user(u.effective_user.id, u.effective_user.username, u.effective_user.first_name) or asyncio.run_coroutine_threadsafe(show_main_menu(u, c), loop)))
            application.add_handler(CallbackQueryHandler(show_main_menu, pattern='^back_to_menu$'))
            application.add_handler(CallbackQueryHandler(lambda u,c: u.callback_query.edit_message_text("🎯 اختر المستوى:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🥉 سهل", url=f"{GAME_URL}/play?user={u.effective_user.id}&difficulty=easy")],[InlineKeyboardButton("🥈 متوسط", url=f"{GAME_URL}/play?user={u.effective_user.id}&difficulty=medium")],[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]])), pattern='^choose_level$'))
            
            logger.info("🤖 Bot worker initialized.")
            application.run_polling(drop_pending_updates=True, stop_signals=None, close_loop=False)
        except Conflict:
            logger.warning("Conflict! Waiting 15s...")
            time.sleep(15)
        except Exception as e:
            logger.error(f"Bot crash: {e}")
            time.sleep(5)

threading.Thread(target=run_bot_worker, name="BotThread", daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

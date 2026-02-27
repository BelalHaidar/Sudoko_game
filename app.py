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
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__, template_folder=BASE_DIR)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())

Talisman(app, force_https=True, frame_options='DENY')
limiter = Limiter(app=app, key_func=get_remote_address, storage_uri="memory://")

# تهيئة قاعدة البيانات بالمسار المطلق
db_path = os.environ.get('DATABASE_PATH', os.path.join(BASE_DIR, 'sudoku.db'))
db = Database(db_path=db_path)
generator = SudokuGenerator()

# الثوابت
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

CHARGE_PACKAGES = [(50, 500), (100, 1000), (300, 3000), (500, 5000), (1000, 10000)]
WITHDRAW_PACKAGES = [100, 300, 500, 1000]

# --- مسارات Flask (الموقع) ---

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
            
            # التأكد من إرسال البيانات بشكل آمن ومحمي
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
    board = data.get('board')
    if SudokuGenerator.check_solution(board):
        game = db.get_game(data.get('game_id'))
        reward = REWARDS.get(game['difficulty'], 500)
        db.add_points(game['user_id'], reward, f"فوز بمستوى {game['difficulty']}")
        db.complete_game(data.get('game_id'), 'won')
        return jsonify({'success': True, 'reward': reward, 'message': 'حل صحيح! 🎉', 'reset_timer': True})
    return jsonify({'success': False, 'message': 'الحل غير صحيح، حاول مجدداً', 'reset_timer': True})

# --- وظائف البوت ---

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

# --- نظام الشحن (Conversation) ---

async def start_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(f"📦 {s}ل.س ({p}ن)", callback_data=f"cp_{s}_{p}")] for s, p in CHARGE_PACKAGES]
    kb.append([InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')])
    await safe_edit(update, "💳 اختر باقة الشحن:", InlineKeyboardMarkup(kb))
    return C_PKG

async def charge_pkg_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_pkg'] = update.callback_query.data # تصحيح الخطأ: تحديث وليس استبدال
    kb = [[InlineKeyboardButton("🇸🇾 سيرياتيل كاش", callback_data='cm_Syriatel')], [InlineKeyboardButton("🟡 MTN كاش", callback_data='cm_MTN')]]
    await safe_edit(update, "🏦 اختر طريقة الدفع:", InlineKeyboardMarkup(kb))
    return C_METH

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

# --- نظام السحب ---

async def start_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(f"💰 {s} ل.س ({s*10}ن)", callback_data=f"wa_{s}_{s*10}")] for s in WITHDRAW_PACKAGES]
    kb.append([InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')])
    await safe_edit(update, "💰 اختر مبلغ السحب:", InlineKeyboardMarkup(kb))
    return W_AMT

async def withdraw_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    data = context.user_data
    user = db.get_user_by_telegram_id(update.effective_user.id)
    if user['points'] < int(data['w_pts']):
        await update.message.reply_text("❌ رصيدك غير كافٍ!")
        return ConversationHandler.END
    
    db.deduct_points(user['id'], int(data['w_pts']))
    rid = db.create_withdrawal_request(user['id'], int(data['w_pts']), int(data['w_syp']), int(data['w_syp']), "Cash", phone)
    
    admin_msg = f"💸 **طلب سحب جديد #{rid}**\n👤 {update.effective_user.first_name}\n🆔 `{update.effective_user.id}`\n💰 المبلغ: {data['w_syp']}ل.س\n📱 هاتف المستلم: {phone}"
    admin_kb = [[InlineKeyboardButton("✅ تنفيذ", callback_data=f"appw_{rid}"), InlineKeyboardButton("❌ رفض", callback_data=f"rejw_{rid}")]]
    await context.bot.send_message(ADMIN_ID, admin_msg, reply_markup=InlineKeyboardMarkup(admin_kb), parse_mode='Markdown')
    await update.message.reply_text("✅ تم إرسال طلب السحب للأدمن!")
    return ConversationHandler.END

# --- تشغيل البوت في خيط خلفي ---
def run_bot_loop():
    while True:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            application = Application.builder().token(BOT_TOKEN).build()
            
            charge_h = ConversationHandler(
                entry_points=[CallbackQueryHandler(start_charge, pattern='^start_charge$')],
                states={
                    C_PKG: [CallbackQueryHandler(charge_pkg_selected, pattern='^cp_')],
                    C_METH: [CallbackQueryHandler(lambda u,c: c.user_data.update({'c_meth':u.callback_query.data.split('_')[1]}) or safe_edit(u, "📱 أرسل رقم هاتف المحول منه:") or C_PHONE, pattern='^cm_')],
                    C_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: c.user_data.update({'c_phone':u.message.text}) or u.message.reply_text("🔢 أرسل رقم العملية:") or C_TRANS)],
                    C_TRANS: [MessageHandler(filters.TEXT & ~filters.COMMAND, charge_trans_received)]
                },
                fallbacks=[CallbackQueryHandler(lambda u,c: show_main_menu(u), pattern='^back_to_menu$')]
            )

            withdraw_h = ConversationHandler(
                entry_points=[CallbackQueryHandler(start_withdraw, pattern='^start_withdraw$')],
                states={
                    W_AMT: [CallbackQueryHandler(lambda u,c: c.user_data.update({'w_syp':u.callback_query.data.split('_')[1], 'w_pts':u.callback_query.data.split('_')[2]}) or safe_edit(u, "📱 أرسل رقم هاتفك لاستلام المبلغ:") or W_PHONE, pattern='^wa_')],
                    W_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_phone_received)]
                },
                fallbacks=[CallbackQueryHandler(lambda u,c: show_main_menu(u), pattern='^back_to_menu$')]
            )

            application.add_handler(charge_h)
            application.add_handler(withdraw_h)
            application.add_handler(CommandHandler("start", lambda u,c: db.create_user(u.effective_user.id, u.effective_user.username, u.effective_user.first_name) or asyncio.run_coroutine_threadsafe(show_main_menu(u), loop)))
            application.add_handler(CallbackQueryHandler(lambda u,c: db.update_terms(u.effective_user.id, 1) or show_main_menu(u), pattern='^terms_accept$'))
            application.add_handler(CallbackQueryHandler(lambda u,c: show_main_menu(u), pattern='^back_to_menu$'))
            application.add_handler(CallbackQueryHandler(lambda u,c: safe_edit(u, "🎯 اختر مستوى الصعوبة:", InlineKeyboardMarkup([[InlineKeyboardButton("🥉 سهل", url=f"{GAME_URL}/play?user={u.effective_user.id}&difficulty=easy")],[InlineKeyboardButton("🥈 متوسط", url=f"{GAME_URL}/play?user={u.effective_user.id}&difficulty=medium")],[InlineKeyboardButton("🥇 صعب", url=f"{GAME_URL}/play?user={u.effective_user.id}&difficulty=hard")],[InlineKeyboardButton("👑 خبير", url=f"{GAME_URL}/play?user={u.effective_user.id}&difficulty=expert")],[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]])), pattern='^choose_level$'))
            
            logger.info("🤖 Bot worker starting...")
            application.run_polling(drop_pending_updates=True, stop_signals=None, close_loop=False)
        except Conflict:
            time.sleep(10)
        except Exception as e:
            logger.error(f"Bot Error: {e}")
            time.sleep(5)

threading.Thread(target=run_bot_loop, name="BotThread", daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

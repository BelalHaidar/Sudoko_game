import os
import json
import logging
import asyncio
import threading
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

# استيراد المكونات المحلية
from database import Database
from sudoku import SudokuGenerator
import multiprocessing

# تحميل الإعدادات
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- إعدادات Flask ---
app = Flask(__name__, template_folder='.') # القوالب في المجلد الرئيسي لحل مشكلة المسارات
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())

Talisman(app, force_https=True, frame_options='DENY')
limiter = Limiter(app=app, key_func=get_remote_address, storage_uri="memory://")

db = Database()
generator = SudokuGenerator()

# الثوابت والقيم
REWARDS = {'easy': 500, 'medium': 1000, 'hard': 1500, 'expert': 5000}
GAME_COST = int(os.environ.get('GAME_COST', 100))
HINT_COST = int(os.environ.get('HINT_COST', 50))
POINTS_PER_SYP = int(os.environ.get('POINTS_PER_SYP', 10))
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GAME_URL = os.environ.get('GAME_URL')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
INTERNAL_API_KEY = os.environ.get('INTERNAL_API_KEY')

# حالات المحادثة للبوت
C_PKG, C_METH, C_PHONE, C_TRANS, C_CONFIRM = range(5)
W_METH, W_AMT, W_PHONE, W_CONFIRM = range(10, 14)
CHARGE_PACKAGES = [(50, 500), (100, 1000), (300, 3000), (500, 5000), (1000, 10000)]
WITHDRAW_PACKAGES = [100, 300, 500, 1000]

# --- مسارات Flask (الموقع) ---

@app.route('/')
def index():
    return jsonify({'status': 'online', 'service': 'Sudoku Game & Bot'})

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
            return render_template('game.html', puzzle_json=json.dumps(puzzle), 
                                 solution_json=json.dumps(solution), game_id=game_id, 
                                 tg_id=tg_id, difficulty=difficulty, 
                                 user_points=user['points'] - GAME_COST, hint_cost=HINT_COST)
    except Exception as e:
        logger.error(f"Error in play: {e}")
        return "Internal Error", 500

@app.route('/get_hint', methods=['POST'])
def get_hint():
    data = request.get_json()
    user = db.get_user_by_telegram_id(int(data.get('tg_id')))
    if user and user['points'] >= HINT_COST:
        game = db.get_game(data.get('game_id'))
        hint = generator.get_hint(game['puzzle'], game['solution'])
        if hint and db.deduct_points(user['id'], HINT_COST):
            return jsonify({'success': True, 'hint': hint, 'new_points': user['points'] - HINT_COST})
    return jsonify({'success': False, 'error': 'رصيد غير كافٍ'})

@app.route('/check_solution', methods=['POST'])
def check_solution():
    data = request.get_json()
    board = data.get('board')
    if SudokuGenerator.check_solution(board):
        game = db.get_game(data.get('game_id'))
        reward = REWARDS.get(game['difficulty'], 500)
        db.add_points(game['user_id'], reward, f"فوز بمستوى {game['difficulty']}")
        db.complete_game(data.get('game_id'), 'won')
        return jsonify({'success': True, 'reward': reward, 'message': 'حل صحيح!'})
    db.complete_game(data.get('game_id'), 'lost')
    return jsonify({'success': False, 'message': 'الحل غير صحيح'})

# --- وظائف البوت (Telegram Bot) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.create_user(user.id, user.username or user.first_name, user.first_name)
    user_data = db.get_user_by_telegram_id(user.id)
    
    if not user_data.get('agreed_terms'):
        text = "🎮 **تحدي السودوكو**\nكل نقطة = 10 ل.س\nتكلفة اللعبة: 100ن\n\n✅ هل توافق على الشروط؟"
        kb = [[InlineKeyboardButton("✅ موافق", callback_data='terms_accept')],
              [InlineKeyboardButton("❌ رفض", callback_data='terms_reject')]]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        await show_main_menu(update)

async def terms_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "terms_accept":
        db.update_terms(query.from_user.id, 1)
        await show_main_menu(update, is_query=True)
    else:
        await query.edit_message_text("يرجى الموافقة للبدء.")

async def show_main_menu(update, is_query=False):
    user_id = update.effective_user.id if not is_query else update.callback_query.from_user.id
    user = db.get_user_by_telegram_id(user_id)
    text = f"🎮 **القائمة**\n💰 رصيدك: {user['points']} نقطة"
    kb = [[InlineKeyboardButton("🎯 لعب", callback_data='choose_level')],
          [InlineKeyboardButton("💳 شحن", callback_data='start_charge'), InlineKeyboardButton("💰 سحب", callback_data='start_withdraw')],
          [InlineKeyboardButton("👤 حسابي", callback_data='profile')]]
    
    if is_query: await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def choose_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [[InlineKeyboardButton("🥉 سهل", url=f"{GAME_URL}/play?user={query.from_user.id}&difficulty=easy")],
          [InlineKeyboardButton("🥈 متوسط", url=f"{GAME_URL}/play?user={query.from_user.id}&difficulty=medium")],
          [InlineKeyboardButton("🥇 صعب", url=f"{GAME_URL}/play?user={query.from_user.id}&difficulty=hard")],
          [InlineKeyboardButton("👑 خبير", url=f"{GAME_URL}/play?user={query.from_user.id}&difficulty=expert")],
          [InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    await query.edit_message_text("🎯 اختر مستوى الصعوبة:", reply_markup=InlineKeyboardMarkup(kb))

# --- نظام الشحن ---
async def start_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [[InlineKeyboardButton(f"📦 {syp}ل.س ({pts}ن)", callback_data=f"cp_{syp}_{pts}")] for syp, pts in CHARGE_PACKAGES]
    kb.append([InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')])
    await query.edit_message_text("💳 اختر باقة الشحن:", reply_markup=InlineKeyboardMarkup(kb))
    return C_PKG

async def charge_pkg_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['c_pkg'] = query.data
    kb = [[InlineKeyboardButton("🇸🇾 سيرياتيل كاش", callback_data='cm_Syriatel')], [InlineKeyboardButton("🟡 MTN كاش", callback_data='cm_MTN')]]
    await query.edit_message_text("🏦 اختر طريقة الدفع:", reply_markup=InlineKeyboardMarkup(kb))
    return C_METH

async def charge_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_phone'] = update.message.text
    await update.message.reply_text("🔢 أرسل رقم العملية:")
    return C_TRANS

async def charge_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trans_id = update.message.text
    pkg = context.user_data['c_pkg'].split('_')
    user = db.get_user_by_telegram_id(update.effective_user.id)
    rid = db.create_charge_request(user['id'], int(pkg[1]), int(pkg[2]), context.user_data['c_meth'], context.user_data['c_phone'], trans_id)
    
    admin_kb = [[InlineKeyboardButton("✅ قبول", callback_data=f"appc_{rid}"), InlineKeyboardButton("❌ رفض", callback_data=f"rejc_{rid}")]]
    await context.bot.send_message(ADMIN_ID, f"🔔 شحن جديد #{rid}\n👤 {update.effective_user.first_name}\n📦 {pkg[1]}ل.س\n🔢 {trans_id}", reply_markup=InlineKeyboardMarkup(admin_kb))
    await update.message.reply_text("✅ تم استلام طلبك!")
    return ConversationHandler.END

# --- تشغيل البوت و Flask معاً ---
def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    application = Application.builder().token(BOT_TOKEN).build()
    
    charge_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_charge, pattern='^start_charge$')],
        states={
            C_PKG: [CallbackQueryHandler(charge_pkg_selected, pattern='^cp_')],
            C_METH: [CallbackQueryHandler(lambda u,c: (setattr(c,'user_data', {**c.user_data, 'c_meth': u.callback_query.data.split('_')[1]}), u.callback_query.edit_message_text("📱 أرسل رقم الهاتف المحول منه:"))[1], pattern='^cm_')],
            C_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, charge_phone_input)],
            C_TRANS: [MessageHandler(filters.TEXT & ~filters.COMMAND, charge_final)]
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    application.add_handler(charge_h)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(terms_handler, pattern='^terms_'))
    application.add_handler(CallbackQueryHandler(choose_level, pattern='^choose_level$'))
    application.add_handler(CallbackQueryHandler(lambda u,c: show_main_menu(u, True), pattern='^back_to_menu$'))
    
    logger.info("Starting Bot...")
    application.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == '__main__':

    bot_process = multiprocessing.Process(target=run_bot, daemon=True)
    bot_process.start()

    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))


def start_bot_on_gunicorn():
    # التأكد من تشغيل البوت مرة واحدة فقط
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true': # لمنع التشغيل المزدوج في وضع Debug
        bot_process = multiprocessing.Process(target=run_bot, daemon=True)
        bot_process.start()

# استدعاء الوظيفة عند تحميل الملف بواسطة Gunicorn
start_bot_on_gunicorn()

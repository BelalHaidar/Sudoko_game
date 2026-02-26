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
from telegram.error import BadRequest

# استيراد المكونات المحلية
from database import Database
from sudoku import SudokuGenerator

# تحميل الإعدادات
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- إعدادات Flask ---
app = Flask(__name__, template_folder='.')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())

Talisman(app, force_https=True, frame_options='DENY')
limiter = Limiter(app=app, key_func=get_remote_address, storage_uri="memory://")

db = Database()
generator = SudokuGenerator()

# الثوابت
REWARDS = {'easy': 500, 'medium': 1000, 'hard': 1500, 'expert': 5000}
GAME_COST = 100
HINT_COST = 50
POINTS_PER_SYP = 10
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GAME_URL = os.environ.get('GAME_URL')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))

# حالات المحادثة
C_PKG, C_METH, C_PHONE, C_TRANS = range(4)
W_METH, W_AMT, W_PHONE = range(10, 13)

# الباقات بناءً على المتطلبات
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
            return render_template('game.html', puzzle_json=json.dumps(puzzle), 
                                 solution_json=json.dumps(solution), game_id=game_id, 
                                 tg_id=tg_id, difficulty=difficulty, 
                                 user_points=user['points'] - GAME_COST, hint_cost=HINT_COST)
    except Exception as e:
        logger.error(f"Error: {e}")
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

# --- وظائف البوت ---

async def show_main_menu(update, is_query=False):
    uid = update.effective_user.id if not is_query else update.callback_query.from_user.id
    user = db.get_user_by_telegram_id(uid)
    text = f"🧩 **القائمة الرئيسية**\n💰 رصيدك: {user['points']} نقطة"
    kb = [[InlineKeyboardButton("🎯 ابدأ اللعب", callback_data='choose_level')],
          [InlineKeyboardButton("💳 شحن", callback_data='start_charge'), InlineKeyboardButton("💰 سحب", callback_data='start_withdraw')],
          [InlineKeyboardButton("👤 حسابي", callback_data='profile'), InlineKeyboardButton("📜 السجل", callback_data='history')]]
    try:
        if is_query: await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    except BadRequest: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.create_user(user.id, user.username or user.first_name, user.first_name)
    user_data = db.get_user_by_telegram_id(user.id)
    if not user_data.get('agreed_terms'):
        text = "🎮 **أهلاً بك في تحدي السودوكو!**\n\nنظام النقاط:\nسهل: +500 | متوسط: +1000 | صعب: +1500 | خبير: +5000\n\n✅ هل توافق على الشروط؟"
        kb = [[InlineKeyboardButton("✅ موافق", callback_data='terms_accept')], [InlineKeyboardButton("❌ رفض", callback_data='terms_reject')]]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: await show_main_menu(update)

# --- نظام الشحن ---
async def start_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(f"📦 {syp}ل.س ({pts}ن)", callback_data=f"cp_{syp}_{pts}")] for syp, pts in CHARGE_PACKAGES]
    kb.append([InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')])
    await update.callback_query.edit_message_text("💳 اختر باقة الشحن:", reply_markup=InlineKeyboardMarkup(kb))
    return C_PKG

async def charge_trans_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.message.text
    pkg = context.user_data['c_pkg'].split('_')
    user = db.get_user_by_telegram_id(update.effective_user.id)
    rid = db.create_charge_request(user['id'], int(pkg[1]), int(pkg[2]), context.user_data['c_meth'], context.user_data['c_phone'], tid)
    
    # رسالة الأدمن مع معرف التيليجرام
    admin_kb = [[InlineKeyboardButton("✅ قبول", callback_data=f"appc_{rid}"), InlineKeyboardButton("❌ رفض", callback_data=f"rejc_{rid}")]]
    await context.bot.send_message(ADMIN_ID, f"🔔 **طلب شحن جديد #{rid}**\n👤 الاسم: {update.effective_user.first_name}\n🆔 المعرف: `{update.effective_user.id}`\n📦 الباقة: {pkg[1]}ل.س\n📱 هاتف المحول: {context.user_data['c_phone']}\n🔢 رقم العملية: `{tid}`", reply_markup=InlineKeyboardMarkup(admin_kb), parse_mode='Markdown')
    await update.message.reply_text("✅ تم استلام طلبك! سيتم الإشعار عند القبول.")
    return ConversationHandler.END

# --- نظام السحب ---
async def start_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(f"💰 {syp} ل.س ({syp*10}ن)", callback_data=f"wa_{syp}_{syp*10}")] for syp in WITHDRAW_PACKAGES]
    kb.append([InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')])
    await update.callback_query.edit_message_text("💰 اختر مبلغ السحب:", reply_markup=InlineKeyboardMarkup(kb))
    return W_AMT

async def withdraw_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    data = context.user_data
    user = db.get_user_by_telegram_id(update.effective_user.id)
    if user['points'] < int(data['w_pts']):
        await update.message.reply_text("❌ رصيدك غير كافٍ!")
        return ConversationHandler.END
    
    db.deduct_points(user['id'], int(data['w_pts']))
    rid = db.create_withdrawal_request(user['id'], int(data['w_pts']), int(data['w_syp']), int(data['w_syp']), "كاش", phone)
    
    # رسالة الأدمن للسحب مع معرف اللاعب
    admin_kb = [[InlineKeyboardButton("✅ قبول", callback_data=f"appw_{rid}"), InlineKeyboardButton("❌ رفض", callback_data=f"rejw_{rid}")]]
    await context.bot.send_message(ADMIN_ID, f"💸 **طلب سحب جديد #{rid}**\n👤 الاسم: {update.effective_user.first_name}\n🆔 المعرف: `{update.effective_user.id}`\n💰 المبلغ: {data['w_syp']}ل.س\n📱 رقم المستلم: {phone}", reply_markup=InlineKeyboardMarkup(admin_kb), parse_mode='Markdown')
    await update.message.reply_text("✅ تم إرسال طلب السحب للأدمن!")
    return ConversationHandler.END

# --- الإدارة ---
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

# --- تشغيل البوت ---
def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    application = Application.builder().token(BOT_TOKEN).build()
    
    charge_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_charge, pattern='^start_charge$')],
        states={
            C_PKG: [CallbackQueryHandler(lambda u,c: setattr(c,'user_data',{'c_pkg':u.callback_query.data}) or u.callback_query.edit_message_text("🏦 اختر طريقة الدفع:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🇸🇾 سيرياتيل", callback_data='cm_Syriatel')],[InlineKeyboardButton("🟡 MTN", callback_data='cm_MTN')]])) or C_METH, pattern='^cp_')],
            C_METH: [CallbackQueryHandler(lambda u,c: setattr(c,'user_data',{**c.user_data,'c_meth':u.callback_query.data.split('_')[1]}) or u.callback_query.edit_message_text("📱 أرسل رقم الهاتف الذي حولت منه:") or C_PHONE, pattern='^cm_')],
            C_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: setattr(c,'user_data',{**c.user_data,'c_phone':u.message.text}) or u.message.reply_text("🔢 أرسل رقم العملية:") or C_TRANS)],
            C_TRANS: [MessageHandler(filters.TEXT & ~filters.COMMAND, charge_trans_received)]
        },
        fallbacks=[CallbackQueryHandler(lambda u,c: show_main_menu(u, True), pattern='^back_to_menu$')]
    )

    withdraw_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_withdraw, pattern='^start_withdraw$')],
        states={
            W_AMT: [CallbackQueryHandler(lambda u,c: setattr(c,'user_data',{'w_syp':u.callback_query.data.split('_')[1], 'w_pts':u.callback_query.data.split('_')[2]}) or u.callback_query.edit_message_text("📱 أرسل رقم الهاتف لاستلام المبلغ:") or W_PHONE, pattern='^wa_')],
            W_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_phone_received)]
        },
        fallbacks=[CallbackQueryHandler(lambda u,c: show_main_menu(u, True), pattern='^back_to_menu$')]
    )

    application.add_handler(charge_h)
    application.add_handler(withdraw_h)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(lambda u,c: db.update_terms(u.effective_user.id, 1) or show_main_menu(u, True), pattern='^terms_accept$'))
    application.add_handler(CallbackQueryHandler(lambda u,c: show_main_menu(u, True), pattern='^back_to_menu$'))
    application.add_handler(CallbackQueryHandler(lambda u,c: u.callback_query.edit_message_text("🎯 اختر مستوى الصعوبة:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🥉 سهل", url=f"{GAME_URL}/play?user={u.effective_user.id}&difficulty=easy")],[InlineKeyboardButton("🥈 متوسط", url=f"{GAME_URL}/play?user={u.effective_user.id}&difficulty=medium")],[InlineKeyboardButton("🥇 صعب", url=f"{GAME_URL}/play?user={u.effective_user.id}&difficulty=hard")],[InlineKeyboardButton("👑 خبير", url=f"{GAME_URL}/play?user={u.effective_user.id}&difficulty=expert")],[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]])), pattern='^choose_level$'))
    application.add_handler(CallbackQueryHandler(handle_admin, pattern='^(appc|rejc|appw|rejw)_'))
    application.add_handler(CallbackQueryHandler(lambda u,c: (setattr(u.callback_query, 'user', db.get_user_by_telegram_id(u.effective_user.id)) or u.callback_query.edit_message_text(f"👤 **حسابي**\n🆔 `{u.effective_user.id}`\n💰 رصيدك: {db.get_user_by_telegram_id(u.effective_user.id)['points']}ن\n💵 {db.get_user_by_telegram_id(u.effective_user.id)['points']*10:,} ل.س", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]), parse_mode='Markdown')), pattern='^profile$'))

    application.run_polling(drop_pending_updates=True, stop_signals=None)

threading.Thread(target=run_bot, name="BotThread", daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

import os
import json
import logging
import asyncio
import threading
import time
import warnings
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

# ✅ تحميل الإعدادات وكتم التحذيرات
load_dotenv()
warnings.filterwarnings("ignore", category=UserWarning, module='telegram.ext')
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- إعدادات تطبيق Flask ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())

# في ملف app.py تأكد من تعديل هذا السطر قبل الرفع:
Talisman(
    app,
    force_https=False, # نغيرها لـ True عند الرفع
    content_security_policy={
        'default-src': "'self'",
        'script-src': "'self' 'unsafe-inline'",
        'style-src': "'self' 'unsafe-inline'",
        'img-src': '*'
    },
    frame_options='DENY'
)
limiter = Limiter(app=app, key_func=get_remote_address, storage_uri="memory://")

db = Database(db_path=os.path.join(BASE_DIR, 'sudoku.db'))
generator = SudokuGenerator()

# ✅ الإعدادات من متغيرات البيئة
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GAME_URL = os.environ.get('GAME_URL', 'https://sudoko-game-s4dt.onrender.com').rstrip('/')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
POINTS_PER_SYP = int(os.environ.get('POINTS_PER_SYP', 10))

WELCOME_TEXT = (
    "🎮 **أهلاً بك في تحدي السودوكو!**\n\n"
    "💡 **نظام النقاط:**\n"
    "سهل: +500 | متوسط: +1000 | صعب: +1500 | خبير: +5000\n\n"
    "💰 **القيمة:** كل 10 نقاط = 1 ليرة سورية\n"
    "🎮 تكلفة اللعبة: 100 نقطة\n\n"
    "✅ **هل توافق على الشروط للبدء؟**"
)

# حالات المحادثة
C_PKG, C_METH, C_PHONE, C_TRANS, C_CONFIRM = range(5)
W_METH, W_AMT, W_PHONE, W_CONFIRM = range(10, 14)

CHARGE_PACKAGES = [(50, 500), (100, 1000), (300, 3000), (500, 5000), (1000, 10000)]
WITHDRAW_PACKAGES = [100, 300, 500, 1000] 

# --- مسارات Flask (الموقع الإلكتروني) ---

@app.route('/')
def index():
    return jsonify({'service': 'Sudoku Game & Bot', 'status': 'online'})

import json

@app.route('/play')
def play():
    try:
        tg_id = request.args.get('user')
        difficulty = request.args.get('difficulty', 'medium')
        user = db.get_user_by_telegram_id(int(tg_id))
        
        if user and db.deduct_points(user['id'], 100):
            puzzle, solution = generator.generate_puzzle(difficulty)
            game_id = db.save_game(user['id'], difficulty, puzzle, solution)
            
            return render_template('game.html', 
                                 puzzle_json=json.dumps(puzzle), 
                                 solution_json=json.dumps(solution),
                                 game_id=game_id, 
                                 tg_id=tg_id, 
                                 difficulty=difficulty, 
                                 user_points=user['points'] - 100,
                                 hint_cost=50)
    except Exception as e:
        logger.error(f"Play error: {e}")
        return "Internal Error", 500

@app.route('/get_hint', methods=['POST'])
def get_hint():
    try:
        data = request.get_json()
        game_id = data.get('game_id')
        tg_id = data.get('tg_id')
        
        user = db.get_user_by_telegram_id(int(tg_id))
        game = db.get_game(game_id)
        hint_cost = 50 # مأخوذ من ملف الإعدادات 

        if not game:
            return jsonify({'success': False, 'error': 'اللعبة غير موجودة '})

        # 🛑 فرض القيد: التحقق من عدد التلميحات 
        hints_used = game.get('hints_used', 0)
        if hints_used >= 5:
            return jsonify({'success': False, 'error': '❌ انتهت تلميحات هذه اللعبة (الحد 5) '})

        if user['points'] < hint_cost:
            return jsonify({'success': False, 'error': f'❌ رصيد غير كافٍ ({hint_cost}ن) '})

        # معالجة بيانات المصفوفة (حل مشكلة TypeError) 
        p_data, s_data = game['puzzle'], game['solution']
        puzzle_list = json.loads(p_data) if isinstance(p_data, (str, bytes)) else p_data
        solution_list = json.loads(s_data) if isinstance(s_data, (str, bytes)) else s_data

        hint = generator.get_hint(puzzle_list, solution_list)
        
        if hint and db.deduct_points(user['id'], hint_cost):
            # ✅ حفظ التلميح المستخدم يدوياً في قاعدة البيانات لضمان الالتزام 
            import sqlite3
            conn = sqlite3.connect(os.path.join(BASE_DIR, 'sudoku.db'))
            conn.execute("UPDATE games SET hints_used = hints_used + 1 WHERE id = ?", (game_id,))
            conn.commit()
            conn.close()

            return jsonify({
                'success': True, 
                'hint': hint, 
                'new_points': user['points'] - hint_cost,
                'hints_remaining': 5 - (hints_used + 1)
            })
            
    except Exception as e:
        logger.error(f"Hint error: {e} ")
        return jsonify({'success': False, 'error': 'حدث خطأ فني '})
    
    return jsonify({'success': False, 'error': 'لا توجد خلايا فارغة '})

@app.route('/check_solution', methods=['POST'])
def check_solution():
    data = request.get_json()
    if SudokuGenerator.check_solution(data.get('board')):
        game = db.get_game(data.get('game_id'))
        reward = {'easy':500, 'medium':1000, 'hard':1500, 'expert':5000}.get(game['difficulty'], 500)
        db.add_points(game['user_id'], reward, "Win")
        return jsonify({'success': True, 'reward': reward})
    return jsonify({'success': False})

@app.route('/new_game', methods=['POST'])
def new_game_route():
    data = request.get_json()
    # يتم استدعاء هذه الدالة عند طلب "لعبة جديدة" من داخل الصفحة
    return jsonify({'success': True}) # سيؤدي هذا لعمل location.reload() في المتصفح

# --- وظائف البوت العامة ---

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_user_by_telegram_id(user_id)
    text = f"🎮 **القائمة الرئيسية**\n👤 {update.effective_user.first_name}\n💰 الرصيد: {user['points']} نقطة"
    kb = [
        [InlineKeyboardButton("🎯 ابدأ اللعب", callback_data='choose_level')],
        [InlineKeyboardButton("💳 شحن نقاط", callback_data='start_charge'), InlineKeyboardButton("💰 سحب رصيد", callback_data='start_withdraw')],
        [InlineKeyboardButton("👤 حسابي", callback_data='profile'), InlineKeyboardButton("📞 الدعم", url="https://t.me/AskBelal")]
    ]
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return ConversationHandler.END

# ========== نظام الشحن (Charge) ==========

async def start_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(f"📦 {s}ل.س ({p}ن)", callback_data=f"cp_{s}_{p}")] for s, p in CHARGE_PACKAGES]
    kb.append([InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')])
    await update.callback_query.edit_message_text("💳 **اختر باقة الشحن:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return C_PKG

async def charge_pkg_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['c_pkg'] = query.data
    kb = [[InlineKeyboardButton("🇸🇾 سيرياتيل", callback_data='cm_Syriatel')], [InlineKeyboardButton("🟡 MTN", callback_data='cm_MTN')], [InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')]]
    await query.edit_message_text("🏦 **اختر طريقة الدفع:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return C_METH

async def charge_meth_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.split('_')[1]
    context.user_data['c_meth'] = method
    instr = "✅ **سيرياتيل:**\:\nحوّل إلى أحد الأرقام التالية بطريقة التحويل اليدوي حصراً **\n `49725859`**\n `22866918`" if method == 'Syriatel' else "✅ **MTN:**\nحوّل إلى أحد الأرقام التالية بطريقة التحويل اليدوي حصراً **\n `8598040534523762`**\n `8428121421124329`"
    await query.edit_message_text(f"{instr}\n\n📱 **أرسل رقم الهاتف** الذي حوّلت منه:", parse_mode='Markdown')
    return C_PHONE

async def charge_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_phone'] = update.message.text.strip()
    await update.message.reply_text("🔢 **أرسل رقم العملية (Transaction ID)**:", parse_mode='Markdown')
    return C_TRANS

async def charge_trans_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_trans'] = update.message.text.strip()
    pkg = context.user_data['c_pkg'].split('_')
    kb = [[InlineKeyboardButton("✅ تأكيد", callback_data='c_confirm')], [InlineKeyboardButton("❌ إلغاء", callback_data='back_to_menu')]]
    await update.message.reply_text(f"📋 **تأكيد الشحن:**\n📦 {pkg[1]}ل.س = {pkg[2]}ن\n🏦 {context.user_data['c_meth']}\n📱 `{context.user_data['c_phone']}`\n🔢 `{context.user_data['c_trans']}`", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return C_CONFIRM

async def charge_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ud = context.user_data
    pkg = ud['c_pkg'].split('_')
    user_db = db.get_user_by_telegram_id(query.from_user.id)
    rid = db.create_charge_request(user_db['id'], int(pkg[1]), int(pkg[2]), ud['c_meth'], ud['c_phone'], ud['c_trans'])
    
    admin_kb = [[InlineKeyboardButton("✅ قبول", callback_data=f"appc_{rid}"), InlineKeyboardButton("❌ رفض", callback_data=f"rejc_{rid}")]]
    await context.bot.send_message(ADMIN_ID, f"🔔 **شحن #{rid}**\n👤 {query.from_user.first_name}\n🆔 `{query.from_user.id}`\n📦 {pkg[1]}ل.س\n📱 {ud['c_phone']}\n🔢 {ud['c_trans']}", reply_markup=InlineKeyboardMarkup(admin_kb), parse_mode='Markdown')
    await query.edit_message_text("✅ **تم استلام الطلب!** سيتم إخطارك عند التنفيذ.")
    return ConversationHandler.END

# ========== نظام السحب (Withdraw) ==========

async def start_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("🇸🇾 سيرياتيل كاش", callback_data='wm_Syriatel'), InlineKeyboardButton("🟡 MTN كاش", callback_data='wm_MTN')], [InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')]]
    await update.callback_query.edit_message_text("🏦 **اختر طريقة استلام المبلغ:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return W_METH

async def withdraw_meth_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['w_meth'] = query.data.split('_')[1]
    kb = [[InlineKeyboardButton(f"{s} ل.س ({s*10} نقطة)", callback_data=f"wa_{s}_{s*10}")] for s in WITHDRAW_PACKAGES]
    kb.append([InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')])
    await query.edit_message_text("💰 **اختر المبلغ:**\n(عمولة السحب 10% تُخصم تلقائياً)", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return W_AMT

async def withdraw_amt_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, syp, pts = query.data.split('_')
    final_amt = int(int(syp) * 0.9)
    context.user_data.update({'w_syp': int(syp), 'w_pts': int(pts), 'w_final': final_amt})
    await query.edit_message_text(f"📱 **أرسل رقم الهاتف** لاستلام مبلغ {final_amt} ل.س:")
    return W_PHONE

async def withdraw_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['w_phone'] = update.message.text.strip()
    ud = context.user_data
    kb = [[InlineKeyboardButton("✅ تأكيد السحب", callback_data='w_confirm')], [InlineKeyboardButton("❌ إلغاء", callback_data='back_to_menu')]]
    await update.message.reply_text(f"📋 **تأكيد طلب السحب:**\n💰 المبلغ: {ud['w_syp']} ل.س\n✅ سيصلك: {ud['w_final']} ل.س\n📊 الخصم: {ud['w_pts']} نقطة\n📱 الرقم: `{ud['w_phone']}`", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return W_CONFIRM

async def withdraw_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ud = context.user_data
    user_db = db.get_user_by_telegram_id(query.from_user.id)
    if user_db['points'] < ud['w_pts']:
        await query.edit_message_text("❌ رصيدك غير كافٍ!")
        return ConversationHandler.END

    db.deduct_points(user_db['id'], ud['w_pts'])
    rid = db.create_withdrawal_request(user_db['id'], ud['w_pts'], ud['w_syp'], ud['w_final'], ud['w_meth'], ud['w_phone'])
    admin_kb = [[InlineKeyboardButton("✅ تنفيذ", callback_data=f"appw_{rid}"), InlineKeyboardButton("❌ رفض", callback_data=f"rejw_{rid}")]]
    await context.bot.send_message(ADMIN_ID, f"💸 **طلب سحب #{rid}**\n🆔 `{query.from_user.id}`\n💰 {ud['w_final']} ل.س\n🏦 {ud['w_meth']}\n📱 `{ud['w_phone']}`", reply_markup=InlineKeyboardMarkup(admin_kb), parse_mode='Markdown')
    await query.edit_message_text("✅ **تم إرسال الطلب!** سيتم إخطارك عند التحويل.")
    return ConversationHandler.END

# ========== قرارات الأدمن (Admin) ==========

async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    action, rid = data[:4], int(data[5:])
    await query.answer()
    
    if action == "appc":
        db.update_charge_status(rid, 'approved', query.from_user.id)
        req = db.get_charge_request_details(rid)
        await context.bot.send_message(req['telegram_id'], f"🎉 **تم قبول شحنك!**\n✅ أُضيف **{req['points']} نقطة**")
        await query.edit_message_text(f"✅ تم قبول شحن #{rid}")
    elif action == "rejc":
        db.update_charge_status(rid, 'rejected', query.from_user.id)
        req = db.get_charge_request_details(rid)
        await context.bot.send_message(req['telegram_id'], "❌ **رفض طلب الشحن**\n⚠️ تأكد من البيانات.")
        await query.edit_message_text(f"❌ تم رفض شحن #{rid}")
    elif action == "appw":
        db.update_withdraw_status(rid, 'approved')
        req = db.get_withdraw_details(rid)
        await context.bot.send_message(req['telegram_id'], "💸 **تم تنفيذ السحب بنجاح!**")
        await query.edit_message_text(f"✅ تم تنفيذ سحب #{rid}")
    elif action == "rejw":
        req = db.get_withdraw_details(rid)
        db.add_points(req['user_id'], req['amount_points'], "Refunded")
        db.update_withdraw_status(rid, 'rejected')
        await context.bot.send_message(req['telegram_id'], "❌ **رفض السحب**\nتمت إعادة النقاط.")
        await query.edit_message_text(f"❌ رفض سحب #{rid}")

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # إنشاء المستخدم في قاعدة البيانات
    db.create_user(user.id, user.username, user.first_name)
    
    # إرسال رسالة الترحيب مع زر "موافق"
    keyboard = [[InlineKeyboardButton("✅ أوافق، ابدأ الآن", callback_data='back_to_menu')]]
    await update.message.reply_text(
        WELCOME_TEXT,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# --- تشغيل البوت ---

def run_bot():
    while True:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            app_tg = Application.builder().token(BOT_TOKEN).build()

            charge_h = ConversationHandler(
                entry_points=[CallbackQueryHandler(start_charge, pattern='^start_charge$')],
                states={
                    C_PKG: [CallbackQueryHandler(charge_pkg_selected, pattern='^cp_')],
                    C_METH: [CallbackQueryHandler(charge_meth_selected, pattern='^cm_')],
                    C_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, charge_phone_input)],
                    C_TRANS: [MessageHandler(filters.TEXT & ~filters.COMMAND, charge_trans_input)],
                    C_CONFIRM: [CallbackQueryHandler(charge_final, pattern='^c_confirm$')]
                },
                fallbacks=[CallbackQueryHandler(show_main_menu, pattern='^back_to_menu$')]
            )

            withdraw_h = ConversationHandler(
                entry_points=[CallbackQueryHandler(start_withdraw, pattern='^start_withdraw$')],
                states={
                    W_METH: [CallbackQueryHandler(withdraw_meth_selected, pattern='^wm_')],
                    W_AMT: [CallbackQueryHandler(withdraw_amt_selected, pattern='^wa_')],
                    W_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_phone_input)],
                    W_CONFIRM: [CallbackQueryHandler(withdraw_final, pattern='^w_confirm$')]
                },
                fallbacks=[CallbackQueryHandler(show_main_menu, pattern='^back_to_menu$')]
            )

            app_tg.add_handler(charge_h)
            app_tg.add_handler(withdraw_h)
            app_tg.add_handler(CommandHandler("start", start_handler))
            app_tg.add_handler(CallbackQueryHandler(admin_decision, pattern='^(appc|rejc|appw|rejw)_'))
            app_tg.add_handler(CallbackQueryHandler(show_main_menu, pattern='^back_to_menu$'))
            app_tg.add_handler(CallbackQueryHandler(lambda u,c: u.callback_query.edit_message_text("🎯 **اختر المستوى:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🥉 سهل", url=f"{GAME_URL}/play?user={u.effective_user.id}&difficulty=easy")],[InlineKeyboardButton("🥈 متوسط", url=f"{GAME_URL}/play?user={u.effective_user.id}&difficulty=medium")],[InlineKeyboardButton("🥇 صعب", url=f"{GAME_URL}/play?user={u.effective_user.id}&difficulty=hard")],[InlineKeyboardButton("👑 خبير", url=f"{GAME_URL}/play?user={u.effective_user.id}&difficulty=expert")],[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]), parse_mode='Markdown'), pattern='^choose_level$'))
            app_tg.add_handler(CallbackQueryHandler(lambda u,c: u.callback_query.edit_message_text(f"👤 **حسابي**\n🆔 `{u.effective_user.id}`\n💰 رصيدك: {db.get_user_by_telegram_id(u.effective_user.id)['points']}ن", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]), parse_mode='Markdown'), pattern='^profile$'))

            app_tg.run_polling(drop_pending_updates=True, stop_signals=None, close_loop=False)
        except Conflict: time.sleep(15)
        except Exception as e:
            logger.error(f"Bot crash: {e}")
            time.sleep(5)

threading.Thread(target=run_bot, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
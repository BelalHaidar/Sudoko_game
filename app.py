import os
import json
import logging
import asyncio
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from asgiref.sync import async_to_sync
import threading

# مكتبات تيليجرام
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    ContextTypes, MessageHandler, filters, ConversationHandler
)

from database import Database
from sudoku import SudokuGenerator

# ✅ الإعدادات الأساسية
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())

# تأمين الرابط لـ Render (تفعيل HTTPS)
Talisman(app, force_https=False, content_security_policy=None)
limiter = Limiter(app=app, key_func=get_remote_address, storage_uri="memory://")

# ربط قاعدة البيانات والمولد
db = Database()
generator = SudokuGenerator()

BOT_TOKEN = os.environ.get('BOT_TOKEN')
GAME_URL = os.environ.get('GAME_URL', '').rstrip('/')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))

# ✅ الثوابت والرسائل
WELCOME_TEXT = (
    "🎮 **أهلاً بك في تحدي السودوكو!**\n\n"
    "💡 **نظام النقاط:**\n"
    "سهل: +500 | متوسط: +1000 | صعب: +1500 | خبير: +5000\n\n"
    "💰 **القيمة:** كل 10 نقاط = 1 ليرة سورية\n"
    "🎮 تكلفة اللعبة: 100 نقطة\n\n"
    "💰 **تخصم عمولة 10% على كل عملية سحب من البوت\n"
    "🎮 أي خطأ في اختيار رقم الهاتف أو باقة الشحن أو السحب على مسؤولية اللاعب فقط\n\n"
    "✅ **هل توافق على الشروط للبدء؟**"
)

CHARGE_PACKAGES = [(50, 500), (100, 1000), (300, 3000), (500, 5000), (1000, 10000)]
WITHDRAW_PACKAGES = [100, 300, 500, 1000]

# حالات المحادثة
C_PKG, C_METH, C_PHONE, C_TRANS, C_CONFIRM = range(5)
W_METH, W_AMT, W_PHONE, W_CONFIRM = range(10, 14)

# --- إعداد البوت (Webhook) ---
bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

# ✅ القائمة الرئيسية
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_user_by_telegram_id(user_id)
    if not user:
        db.create_user(user_id, update.effective_user.username, update.effective_user.first_name)
        user = db.get_user_by_telegram_id(user_id)
    
    text = f"🎮 **القائمة الرئيسية**\n👤 {update.effective_user.first_name}\n💰 الرصيد: {user['points']} نقطة"
    kb = [
        [InlineKeyboardButton("🎯 ابدأ اللعب", callback_data='choose_level')],
        [InlineKeyboardButton("💳 شحن نقاط", callback_data='start_charge'), InlineKeyboardButton("💰 سحب رصيد", callback_data='start_withdraw')],
        [InlineKeyboardButton("👤 حسابي", callback_data='profile')],
        [InlineKeyboardButton("📞 الدعم", url="https://t.me/AskBelal")]
    ]
    reply_markup = InlineKeyboardMarkup(kb)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    return ConversationHandler.END

# ========== نظام الشحن (Charge) ==========
async def start_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(f"📦 {s}ل.س ({p}ن)", callback_data=f"cp_{s}_{p}")] for s, p in CHARGE_PACKAGES]
    kb.append([InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')])
    await update.callback_query.edit_message_text("💳 **اختر باقة الشحن:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return C_PKG

async def charge_pkg_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data['c_pkg'] = query.data
    kb = [[InlineKeyboardButton("🇸🇾 سيرياتيل", callback_data='cm_Syriatel')], [InlineKeyboardButton("🟡 MTN", callback_data='cm_MTN')], [InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')]]
    await query.edit_message_text("🏦 **اختر طريقة الدفع:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return C_METH

async def charge_meth_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    method = query.data.split('_')[1]
    context.user_data['c_meth'] = method
    instr = "✅ **سيرياتيل:** حوّل إلى: `49725859`" if method == 'Syriatel' else "✅ **MTN:** حوّل إلى: `8598040534523762`"
    await query.edit_message_text(f"{instr}\n\n📱 **أرسل رقم الهاتف** الذي حوّلت منه:")
    return C_PHONE

async def charge_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_phone'] = update.message.text.strip()
    await update.message.reply_text("🔢 **أرسل رقم العملية (Transaction ID):**")
    return C_TRANS

async def charge_trans_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_trans'] = update.message.text.strip()
    pkg = context.user_data['c_pkg'].split('_')
    kb = [[InlineKeyboardButton("✅ تأكيد", callback_data='c_confirm')], [InlineKeyboardButton("❌ إلغاء", callback_data='back_to_menu')]]
    await update.message.reply_text(f"📋 **تأكيد الشحن:**\n📦 {pkg[1]}ل.س\n📱 `{context.user_data['c_phone']}`", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return C_CONFIRM

async def charge_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    ud = context.user_data
    pkg = ud['c_pkg'].split('_')
    user_db = db.get_user_by_telegram_id(query.from_user.id)
    rid = db.create_charge_request(user_db['id'], int(pkg[1]), int(pkg[2]), ud['c_meth'], ud['c_phone'], ud['c_trans'])
    admin_kb = [[InlineKeyboardButton("✅ قبول", callback_data=f"appc_{rid}"), InlineKeyboardButton("❌ رفض", callback_data=f"rejc_{rid}")]]
    await context.bot.send_message(ADMIN_ID, f"🔔 **شحن جديد #{rid}**\n👤 {query.from_user.first_name}\n📦 {pkg[1]}ل.س", reply_markup=InlineKeyboardMarkup(admin_kb))
    await query.edit_message_text("✅ **تم استلام الطلب!** سيتم مراجعته قريباً.")
    return ConversationHandler.END

# ========== نظام السحب (Withdraw) ==========
async def start_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("🇸🇾 سيرياتيل كاش", callback_data='wm_Syriatel'), InlineKeyboardButton("🟡 MTN كاش", callback_data='wm_MTN')], [InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')]]
    await update.callback_query.edit_message_text("🏦 **اختر طريقة السحب:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return W_METH

async def withdraw_meth_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data['w_meth'] = query.data.split('_')[1]
    kb = [[InlineKeyboardButton(f"{s} ل.س", callback_data=f"wa_{s}_{s*10}")] for s in WITHDRAW_PACKAGES]
    await query.edit_message_text("💰 **اختر المبلغ:**", reply_markup=InlineKeyboardMarkup(kb))
    return W_AMT

async def withdraw_amt_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, syp, pts = query.data.split('_')
    context.user_data.update({'w_syp': int(syp), 'w_pts': int(pts)})
    await query.edit_message_text(f"📱 **أرسل رقم الهاتف** لاستلام المبلغ:")
    return W_PHONE

async def withdraw_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['w_phone'] = update.message.text.strip()
    ud = context.user_data
    text = f"📋 **تأكيد سحب {ud['w_syp']} ل.س؟**\n📱 الرقم: {ud['w_phone']}"
    kb = [[InlineKeyboardButton("✅ تأكيد", callback_data='w_confirm')], [InlineKeyboardButton("❌ إلغاء", callback_data='back_to_menu')]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return W_CONFIRM

async def withdraw_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_db = db.get_user_by_telegram_id(query.from_user.id)
    ud = context.user_data
    if user_db['points'] < ud['w_pts']:
        await query.edit_message_text("❌ رصيدك غير كافٍ!")
        return ConversationHandler.END
    
    db.deduct_points(user_db['id'], ud['w_pts'])
    admin_text = f"💰 **طلب سحب رصيد جديد**\n👤 {query.from_user.first_name}\n📱 `{ud['w_phone']}`\n💵 {ud['w_syp']} ل.س"
    await context.bot.send_message(ADMIN_ID, admin_text) # تم الإصلاح هنا
    await query.edit_message_text("✅ **تم إرسال طلب السحب!**")
    return ConversationHandler.END

# --- مسارات Flask ---

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def telegram_webhook():
    try:
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, bot_app.bot)
        
        # إنشاء دالة للمعالجة في خيط منفصل
        def thread_target(u):
            # إنشاء حلقة أحداث جديدة تماماً لهذا الخيط
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # التأكد من تشغيل البوت
                if not bot_app.running:
                    loop.run_until_complete(bot_app.initialize())
                
                # تنفيذ التحديث بالكامل وانتظار النتيجة
                loop.run_until_complete(bot_app.process_update(u))
            except Exception as e:
                logger.error(f"Error in thread: {e}")
            finally:
                loop.close()

        # تشغيل المعالجة في الخلفية وإرجاع OK فوراً لتيليجرام
        threading.Thread(target=thread_target, args=(update,)).start()
        
        return 'OK', 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'OK', 200 # نرسل OK دائماً لتيليجرام لمنع تكرار الإرسال
@app.route('/play')
def play():
    tg_id = request.args.get('user')
    difficulty = request.args.get('difficulty', 'medium')
    user = db.get_user_by_telegram_id(int(tg_id))
    if user and user['points'] >= 100:
        db.deduct_points(user['id'], 100)
        puzzle, solution = generator.generate_puzzle(difficulty)
        game_id = db.save_game(user['id'], difficulty, puzzle, solution)
        return render_template('game.html', puzzle_json=json.dumps(puzzle), solution_json=json.dumps(solution), 
                             game_id=game_id, tg_id=tg_id, difficulty=difficulty, user_points=user['points']-100)
    return render_template('no_points.html', points=user['points'] if user else 0)

# --- تسجيل المعالجات (Handlers) ---

charge_handler = ConversationHandler(
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

withdraw_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_withdraw, pattern='^start_withdraw$')],
    states={
        W_METH: [CallbackQueryHandler(withdraw_meth_selected, pattern='^wm_')],
        W_AMT: [CallbackQueryHandler(withdraw_amt_selected, pattern='^wa_')],
        W_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_phone_input)],
        W_CONFIRM: [CallbackQueryHandler(withdraw_final, pattern='^w_confirm$')]
    },
    fallbacks=[CallbackQueryHandler(show_main_menu, pattern='^back_to_menu$')]
)

# ✅ الترتيب الصحيح والكامل:
bot_app.add_handler(charge_handler)
bot_app.add_handler(withdraw_handler)
bot_app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text(WELCOME_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ موافق", callback_data='back_to_menu')]]), parse_mode='Markdown')))

# دوال عامة
async def choose_level(update, context):
    user_id = update.effective_user.id
    kb = [[InlineKeyboardButton("🥉 سهل", url=f"{GAME_URL}/play?user={user_id}&difficulty=easy")],[InlineKeyboardButton("🥈 متوسط", url=f"{GAME_URL}/play?user={user_id}&difficulty=medium")],[InlineKeyboardButton("🥇 صعب", url=f"{GAME_URL}/play?user={user_id}&difficulty=hard")],[InlineKeyboardButton("👑 خبير", url=f"{GAME_URL}/play?user={user_id}&difficulty=expert")],[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    await update.callback_query.edit_message_text("🎯 **اختر المستوى:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def profile_view(update, context):
    user = db.get_user_by_telegram_id(update.effective_user.id)
    text = f"👤 **حسابي**\n💰 الرصيد: {user['points']} نقطة\n🆔 معرفك: `{user['telegram_id']}`"
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]), parse_mode='Markdown')

bot_app.add_handler(CallbackQueryHandler(show_main_menu, pattern='^back_to_menu$'))
bot_app.add_handler(CallbackQueryHandler(choose_level, pattern='^choose_level$'))
bot_app.add_handler(CallbackQueryHandler(profile_view, pattern='^profile$'))

@app.before_request
def init_webhook():
    if not hasattr(app, 'webhook_initialized'):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(bot_app.bot.set_webhook(url=f"{GAME_URL}/{BOT_TOKEN}"))
            app.webhook_initialized = True
        except Exception as e:
            logger.error(f"Webhook error: {e}")

@app.route('/')
def home():
    return "Sudoku Bot is Running!", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)




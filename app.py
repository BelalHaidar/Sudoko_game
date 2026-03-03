import os
import json
import logging
import asyncio
from flask import Flask, render_template, request, jsonify
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
import threading
import nest_asyncio

# تطبيق nest_asyncio للسماح بتداخل حلقات الأحداث
nest_asyncio.apply()

# مكتبات تيليجرام
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, MessageHandler, filters, ConversationHandler
)
from telegram.request import HTTPXRequest

from database import Database
from sudoku import SudokuGenerator

# ✅ الإعدادات الأساسية
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())

# تأمين الرابط لـ Render
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

# ==================== إعداد البوت بشكل صحيح ====================

# إنشاء حلقة أحداث دائمة للتطبيق
bot_loop = asyncio.new_event_loop()
asyncio.set_event_loop(bot_loop)

# إنشاء تطبيق البوت
request_obj = HTTPXRequest(connection_pool_size=8)
bot_app = Application.builder().token(BOT_TOKEN).request(request_obj).build()

# ==================== جميع handlers هنا ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /start"""
    logger.info(f"User {update.effective_user.id} started the bot")
    await update.message.reply_text(
        WELCOME_TEXT,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ موافق", callback_data='back_to_menu')]]),
        parse_mode='Markdown'
    )

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض القائمة الرئيسية"""
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

async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض الملف الشخصي"""
    query = update.callback_query
    user_id = query.from_user.id
    user = db.get_user_by_telegram_id(user_id)
    
    text = f"👤 **معلومات الحساب**\n\n🆔 معرفك: `{user_id}`\n💰 رصيدك: {user['points'] if user else 0} نقطة\n🎮 الحالة: نشط"
    kb = [[InlineKeyboardButton("🔙 عودة للقائمة", callback_data='back_to_menu')]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def choose_level_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار مستوى الصعوبة"""
    user_id = update.effective_user.id
    kb = [
        [InlineKeyboardButton("🥉 سهل", url=f"{GAME_URL}/play?user={user_id}&difficulty=easy")],
        [InlineKeyboardButton("🥈 متوسط", url=f"{GAME_URL}/play?user={user_id}&difficulty=medium")],
        [InlineKeyboardButton("🥇 صعب", url=f"{GAME_URL}/play?user={user_id}&difficulty=hard")],
        [InlineKeyboardButton("👑 خبير", url=f"{GAME_URL}/play?user={user_id}&difficulty=expert")],
        [InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]
    ]
    await update.callback_query.edit_message_text("🎯 **اختر مستوى التحدي:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

# ========== نظام الشحن ==========
async def start_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء عملية الشحن"""
    kb = [[InlineKeyboardButton(f"📦 {s}ل.س ({p}ن)", callback_data=f"cp_{s}_{p}")] for s, p in CHARGE_PACKAGES]
    kb.append([InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')])
    await update.callback_query.edit_message_text("💳 **اختر باقة الشحن:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return C_PKG

async def charge_pkg_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار باقة الشحن"""
    query = update.callback_query
    context.user_data['c_pkg'] = query.data
    kb = [[InlineKeyboardButton("🇸🇾 سيرياتيل", callback_data='cm_Syriatel')], 
          [InlineKeyboardButton("🟡 MTN", callback_data='cm_MTN')], 
          [InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')]]
    await query.edit_message_text("🏦 **اختر طريقة الدفع:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return C_METH

async def charge_meth_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار طريقة الدفع"""
    query = update.callback_query
    method = query.data.split('_')[1]
    context.user_data['c_meth'] = method
    instr = "✅ **سيرياتيل:** حوّل إلى: `49725859`" if method == 'Syriatel' else "✅ **MTN:** حوّل إلى: `8598040534523762`"
    await query.edit_message_text(f"{instr}\n\n📱 **أرسل رقم الهاتف** الذي حوّلت منه:")
    return C_PHONE

async def charge_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال رقم الهاتف"""
    context.user_data['c_phone'] = update.message.text.strip()
    await update.message.reply_text("🔢 **أرسل رقم العملية (Transaction ID):**")
    return C_TRANS

async def charge_trans_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال رقم العملية"""
    context.user_data['c_trans'] = update.message.text.strip()
    pkg = context.user_data['c_pkg'].split('_')
    kb = [[InlineKeyboardButton("✅ تأكيد", callback_data='c_confirm')], [InlineKeyboardButton("❌ إلغاء", callback_data='back_to_menu')]]
    await update.message.reply_text(f"📋 **تأكيد الشحن:**\n📦 {pkg[1]}ل.س\n📱 `{context.user_data['c_phone']}`", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return C_CONFIRM

async def charge_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تأكيد الشحن وإرسال إشعار للأدمن"""
    query = update.callback_query
    ud = context.user_data
    pkg = ud['c_pkg'].split('_')
    user_db = db.get_user_by_telegram_id(query.from_user.id)
    rid = db.create_charge_request(user_db['id'], int(pkg[1]), int(pkg[2]), ud['c_meth'], ud['c_phone'], ud['c_trans'])
    admin_kb = [[InlineKeyboardButton("✅ قبول", callback_data=f"appc_{rid}"), InlineKeyboardButton("❌ رفض", callback_data=f"rejc_{rid}")]]
    await context.bot.send_message(ADMIN_ID, f"🔔 **شحن جديد #{rid}**\n👤 {query.from_user.first_name}\n📦 {pkg[1]}ل.س", reply_markup=InlineKeyboardMarkup(admin_kb))
    await query.edit_message_text("✅ **تم استلام الطلب!** سيتم مراجعته قريباً.")
    return ConversationHandler.END

# ========== نظام السحب ==========
async def start_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء عملية السحب"""
    kb = [[InlineKeyboardButton("🇸🇾 سيرياتيل كاش", callback_data='wm_Syriatel'), InlineKeyboardButton("🟡 MTN كاش", callback_data='wm_MTN')], [InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')]]
    await update.callback_query.edit_message_text("🏦 **اختر طريقة السحب:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return W_METH

async def withdraw_meth_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار طريقة السحب"""
    query = update.callback_query
    context.user_data['w_meth'] = query.data.split('_')[1]
    kb = [[InlineKeyboardButton(f"{s} ل.س", callback_data=f"wa_{s}_{s*10}")] for s in WITHDRAW_PACKAGES]
    await query.edit_message_text("💰 **اختر المبلغ:**", reply_markup=InlineKeyboardMarkup(kb))
    return W_AMT

async def withdraw_amt_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار المبلغ"""
    query = update.callback_query
    _, syp, pts = query.data.split('_')
    context.user_data.update({'w_syp': int(syp), 'w_pts': int(pts)})
    await query.edit_message_text(f"📱 **أرسل رقم الهاتف** لاستلام المبلغ:")
    return W_PHONE

async def withdraw_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال رقم الهاتف للسحب"""
    context.user_data['w_phone'] = update.message.text.strip()
    ud = context.user_data
    text = f"📋 **تأكيد سحب {ud['w_syp']} ل.س؟**\n📱 الرقم: {ud['w_phone']}"
    kb = [[InlineKeyboardButton("✅ تأكيد", callback_data='w_confirm')], [InlineKeyboardButton("❌ إلغاء", callback_data='back_to_menu')]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return W_CONFIRM

async def withdraw_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تأكيد السحب"""
    query = update.callback_query
    user_db = db.get_user_by_telegram_id(query.from_user.id)
    ud = context.user_data

    if user_db['points'] < ud['w_pts']:
        await query.edit_message_text("❌ رصيدك غير كافٍ لإتمام هذه العملية.")
        return ConversationHandler.END
    
    db.deduct_points(user_db['id'], ud['w_pts'])
    
    admin_text = (
        f"💰 **طلب سحب جديد**\n"
        f"👤 المستخدم: {query.from_user.first_name}\n"
        f"🆔 المعرف: `{query.from_user.id}`\n"
        f"📱 الرقم: `{ud['w_phone']}`\n"
        f"💵 المبلغ: {ud['w_syp']} ل.س\n"
        f"📉 النقاط المخصومة: {ud['w_pts']}"
    )
    await context.bot.send_message(ADMIN_ID, admin_text)
    
    await query.edit_message_text("✅ **تم استلام طلب السحب بنجاح!** سيتم تحويل المبلغ خلال 24 ساعة.")
    return ConversationHandler.END

# ==================== تسجيل المعالجات ====================

def setup_handlers():
    """إعداد جميع معالجات البوت"""
    
    # معالج أمر /start
    bot_app.add_handler(CommandHandler("start", start_command))
    
    # معالج الشحن
    charge_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_charge, pattern='^start_charge$')],
        states={
            C_PKG: [CallbackQueryHandler(charge_pkg_selected, pattern='^cp_')],
            C_METH: [CallbackQueryHandler(charge_meth_selected, pattern='^cm_')],
            C_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, charge_phone_input)],
            C_TRANS: [MessageHandler(filters.TEXT & ~filters.COMMAND, charge_trans_input)],
            C_CONFIRM: [CallbackQueryHandler(charge_final, pattern='^c_confirm$')]
        },
        fallbacks=[CallbackQueryHandler(show_main_menu, pattern='^back_to_menu$')],
        per_message=False,
        name="charge_conversation"
    )
    bot_app.add_handler(charge_conv)
    
    # معالج السحب
    withdraw_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_withdraw, pattern='^start_withdraw$')],
        states={
            W_METH: [CallbackQueryHandler(withdraw_meth_selected, pattern='^wm_')],
            W_AMT: [CallbackQueryHandler(withdraw_amt_selected, pattern='^wa_')],
            W_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_phone_input)],
            W_CONFIRM: [CallbackQueryHandler(withdraw_final, pattern='^w_confirm$')]
        },
        fallbacks=[CallbackQueryHandler(show_main_menu, pattern='^back_to_menu$')],
        per_message=False,
        name="withdraw_conversation"
    )
    bot_app.add_handler(withdraw_conv)
    
    # معالجات callback_query العامة
    bot_app.add_handler(CallbackQueryHandler(show_main_menu, pattern='^back_to_menu$'))
    bot_app.add_handler(CallbackQueryHandler(choose_level_handler, pattern='^choose_level$'))
    bot_app.add_handler(CallbackQueryHandler(profile_handler, pattern='^profile$'))

# تهيئة المعالجات
setup_handlers()

# ==================== تهيئة البوت في حلقة الأحداث الدائمة ====================

async def initialize_bot():
    """تهيئة البوت وتعيين webhook"""
    await bot_app.initialize()
    success = await bot_app.bot.set_webhook(url=f"{GAME_URL}/{BOT_TOKEN}")
    if success:
        logger.info(f"✅ Webhook set to {GAME_URL}/{BOT_TOKEN}")
    else:
        logger.error("❌ Failed to set webhook")

# تشغيل التهيئة في حلقة الأحداث
bot_loop.run_until_complete(initialize_bot())

# ==================== مسارات Flask ====================

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    """استقبال تحديثات تيليجرام - يتم معالجتها في حلقة الأحداث الدائمة"""
    try:
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, bot_app.bot)
        
        # معالجة التحديث في حلقة الأحداث الدائمة
        future = asyncio.run_coroutine_threadsafe(
            bot_app.process_update(update), 
            bot_loop
        )
        
        # انتظار النتيجة (مع timeout)
        future.result(timeout=5)
        logger.debug(f"Processed update {update.update_id}")
        
    except Exception as e:
        logger.error(f"Error processing update: {e}")
    
    return 'OK', 200

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

@app.route('/check_solution', methods=['POST'])
def check_solution():
    try:
        data = request.get_json()
        game_id = data.get('game_id')
        user_solution = data.get('solution')

        game = db.get_game(game_id)
        if not game:
            return jsonify({'success': False, 'error': 'اللعبة غير موجودة'}), 404

        correct_solution = game['solution']

        if user_solution == correct_solution:
            points_map = {'easy': 500, 'medium': 1000, 'hard': 1500, 'expert': 5000}
            reward = points_map.get(game['difficulty'], 0)
            db.add_points(game['user_id'], reward, reason=f"Won {game['difficulty']} game")
            return jsonify({'success': True, 'reward': reward})
        else:
            return jsonify({'success': False, 'error': 'الحل غير صحيح، حاول مجدداً!'})

    except Exception as e:
        logger.error(f"Error in check_solution: {e}")
        return jsonify({'success': False, 'error': 'خطأ داخلي في السيرفر'}), 500

@app.route('/')
def home():
    return "Sudoku Bot is Running!", 200

# ==================== تشغيل التطبيق ====================

def run_flask():
    """تشغيل Flask في الخيط الرئيسي"""
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

def run_bot_loop():
    """تشغيل حلقة الأحداث في خيط منفصل"""
    asyncio.set_event_loop(bot_loop)
    bot_loop.run_forever()

if __name__ == '__main__':
    # تشغيل حلقة الأحداث في خيط منفصل
    bot_thread = threading.Thread(target=run_bot_loop, daemon=True)
    bot_thread.start()
    
    # تشغيل Flask في الخيط الرئيسي
    run_flask()

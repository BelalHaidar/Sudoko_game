import os
import logging
import warnings
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    MessageHandler, filters, ConversationHandler,
)
from dotenv import load_dotenv
from database import Database

# ✅ تحميل متغيرات البيئة
load_dotenv()

# ✅ كتم تحذيرات PTB
warnings.filterwarnings("ignore", category=UserWarning, module='telegram.ext')

# ✅ إعداد التسجيل الآمن
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ✅ قراءة الإعدادات من متغيرات البيئة فقط
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GAME_URL = os.environ.get('GAME_URL', 'https://sudoko-game-s4dt.onrender.com')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
POINTS_PER_SYP = int(os.environ.get('POINTS_PER_SYP', 10))
INTERNAL_API_KEY = os.environ.get('INTERNAL_API_KEY')

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not set in environment variables!")

db = Database()

# حالات المحادثة
C_PKG, C_METH, C_PHONE, C_TRANS, C_CONFIRM = range(5)
W_METH, W_AMT, W_PHONE, W_CONFIRM = range(10, 14)

CHARGE_PACKAGES = [(50, 500), (100, 1000), (300, 3000), (500, 5000), (1000, 10000)]
WITHDRAW_PACKAGES = [100, 300, 500, 1000]

WELCOME_TEXT = (
    "🎮 **أهلاً بك في تحدي السودوكو!**\n\n"
    "💡 **نظام النقاط:**\n"
    "سهل: +500 | متوسط: +1000 | صعب: +1500 | خبير: +5000\n\n"
    "💰 **القيمة:** كل نقطة = 10 ليرات سورية\n"
    "🎮 تكلفة اللعبة: 100 نقطة\n\n"
    "✅ **هل توافق على الشروط للبدء؟**"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.create_user(user.id, user.username or user.first_name, user.first_name)
    user_data = db.get_user_by_telegram_id(user.id)
    
    welcome_text = f"🎮 **مرحباً بك يا {user.first_name}!**\n💰 رصيدك: {user_data['points']} نقطة"
    
    keyboard = [
        [InlineKeyboardButton("🎯 ابدأ اللعب", callback_data='choose_level')],
        [
            InlineKeyboardButton("💳 شحن نقاط", callback_data='start_charge'),
            InlineKeyboardButton("💰 سحب رصيد", callback_data='start_withdraw')
        ],
        [InlineKeyboardButton("👤 معلومات حسابي", callback_data='profile')],
        [InlineKeyboardButton("📞 الدعم الفني", url="https://t.me/AskBelal")]
    ]
    
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def terms_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "terms_accept":
        db.update_terms(query.from_user.id, 1)
        await show_main_menu(update, is_query=True)

async def show_main_menu(update, is_query=False):
    user_id = update.effective_user.id if hasattr(update, 'effective_user') else update.callback_query.from_user.id
    user = db.get_user_by_telegram_id(user_id)
    text = f"🎮 **القائمة**\n👤 {user.get('first_name', 'لاعب')}\n💰 الرصيد: {user['points']} نقطة" if user else "❌ خطأ"
    kb = [
        [InlineKeyboardButton("🎯 لعب", callback_data='choose_level')],
        [InlineKeyboardButton("💳 شحن", callback_data='start_charge'),
         InlineKeyboardButton("💰 سحب", callback_data='start_withdraw')],
        [InlineKeyboardButton("👤 حسابي", callback_data='profile')],
        [InlineKeyboardButton("📞 الدعم", url="https://t.me/AskBelal")]
    ]
    if is_query and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    elif update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def choose_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("🥉 سهل", url=f"{GAME_URL}/play?user={query.from_user.id}&difficulty=easy")],
        [InlineKeyboardButton("🥈 متوسط", url=f"{GAME_URL}/play?user={query.from_user.id}&difficulty=medium")],
        [InlineKeyboardButton("🥇 صعب", url=f"{GAME_URL}/play?user={query.from_user.id}&difficulty=hard")],
        [InlineKeyboardButton("👑 خبير", url=f"{GAME_URL}/play?user={query.from_user.id}&difficulty=expert")],
        [InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]
    ]
    await query.edit_message_text("🎯 **اختر مستوى الصعوبة:**\n(تكلفة: 100 نقطة)", 
                                   reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

# ========== نظام الشحن ==========
async def start_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton(f"📦 {syp}ل.س ({pts} نقطة)", callback_data=f"cp_{syp}_{pts}")] 
        for syp, pts in CHARGE_PACKAGES
    ]
    keyboard.append([InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')])
    await query.edit_message_text("💳 **اختر باقة الشحن:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return C_PKG

async def charge_method_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['c_pkg'] = query.data
    keyboard = [
        [InlineKeyboardButton("🇸🇾 سيرياتيل", callback_data='cm_Syriatel')],
        [InlineKeyboardButton("🟡 MTN", callback_data='cm_MTN')],
        [InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')]
    ]
    await query.edit_message_text("🏦 **اختر طريقة الدفع:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return C_METH

async def charge_method_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.split('_')[1]
    context.user_data['c_meth'] = method
    instr = "✅ **سيرياتيل:**\nحوّل إلى: `49725859` أو `22866918`" if method == 'Syriatel' else "✅ **MTN:**\nحوّل إلى: `8598040534523762`"
    await query.edit_message_text(f"{instr}\n\n📱 **أرسل رقم الهاتف** الذي حوّلت منه:", parse_mode='Markdown')
    return C_PHONE

async def charge_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not phone.isdigit() or len(phone) < 7:
        await update.message.reply_text("❌ رقم غير صالح. أرسل الرقم مرة أخرى:")
        return C_PHONE
    context.user_data['c_phone'] = phone
    await update.message.reply_text("🔢 **أرسل رقم العملية (Transaction ID)**:")
    return C_TRANS

async def charge_trans_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trans_id = update.message.text.strip()
    context.user_data['c_trans'] = trans_id
    phone = context.user_data['c_phone']
    pkg = context.user_data['c_pkg'].split('_')
    amount_syp, points = int(pkg[1]), int(pkg[2])
    method_name = "سيرياتيل" if context.user_data['c_meth'] == 'Syriatel' else "MTN"
    
    keyboard = [
        [InlineKeyboardButton("✅ تأكيد", callback_data='c_confirm')],
        [InlineKeyboardButton("❌ إلغاء", callback_data='back_to_menu')]
    ]
    await update.message.reply_text(
        f"📋 **تأكيد الشحن:**\n📦 {amount_syp}ل.س = {points}ن\n🏦 {method_name}\n📱 `{phone}`\n🔢 `{trans_id}`\n\n⚠️ تأكد من البيانات",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
    )
    return C_CONFIRM

async def charge_step_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    pkg = context.user_data['c_pkg'].split('_')
    amount_syp, points = int(pkg[1]), int(pkg[2])
    method_name = "سيرياتيل" if context.user_data['c_meth'] == 'Syriatel' else "MTN"
    phone = context.user_data['c_phone']
    trans_id = context.user_data['c_trans']
    
    user_db = db.get_user_by_telegram_id(query.from_user.id)
    rid = db.create_charge_request(user_db['id'], amount_syp, points, method_name, phone, trans_id)
    
    admin_kb = [
        [InlineKeyboardButton("✅ قبول", callback_data=f"appc_{rid}")],
        [InlineKeyboardButton("❌ رفض", callback_data=f"rejc_{rid}")]
    ]
    
    await context.bot.send_message(
        ADMIN_ID,
        f"🔔 **شحن جديد #{rid}**\n👤 {query.from_user.first_name} (`{query.from_user.id}`)\n"
        f"📦 {amount_syp}ل.س = {points}ن\n🏦 {method_name}\n📱 `{phone}`\n🔢 `{trans_id}`",
        reply_markup=InlineKeyboardMarkup(admin_kb), parse_mode='Markdown'
    )
    await query.edit_message_text("✅ **تم استلام الطلب!** سيتم إخطارك عند التنفيذ.")
    return ConversationHandler.END

# ========== نظام السحب ==========
async def start_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🇸🇾 سيرياتيل", callback_data='wm_Syriatel'), 
         InlineKeyboardButton("🟡 MTN", callback_data='wm_MTN')],
        [InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')]
    ]
    await query.edit_message_text("🏦 **اختر طريقة الاستلام:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return W_METH

async def withdraw_method_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['w_meth'] = query.data.split('_')[1]
    keyboard = [
        [InlineKeyboardButton(f"{syp} ل.س ({syp*100} نقطة)", callback_data=f"wa_{syp}_{syp*100}")]
        for syp in WITHDRAW_PACKAGES
    ]
    keyboard.append([InlineKeyboardButton("🔙 إلغاء", callback_data='back_to_menu')])
    await query.edit_message_text("💰 **اختر المبلغ:**\n(عمولة 10% تُخصم)", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return W_AMT

async def withdraw_amount_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, amount_syp, points = query.data.split('_')
    amount_syp, points = int(amount_syp), int(points)
    commission = int(amount_syp * 0.10)
    final = amount_syp - commission
    context.user_data.update({'w_amount': amount_syp, 'w_points': points, 'w_final': final})
    
    await query.edit_message_text(
        f"⚠️ **تأكيد السحب:**\n💰 المطلوب: {amount_syp} ل.س\n✂️ العمولة: -{commission} ل.س\n"
        f"✅ **سيصلك: {final} ل.س**\n📊 يُخصم: {points} نقطة\n\n📱 **أرسل رقم الهاتف** للاستلام:",
        parse_mode='Markdown'
    )
    return W_PHONE

async def withdraw_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not phone.isdigit() or len(phone) < 7:
        await update.message.reply_text("❌ رقم غير صالح. أرسل الرقم مرة أخرى:")
        return W_PHONE
    context.user_data['w_phone'] = phone
    
    pkg = context.user_data
    keyboard = [
        [InlineKeyboardButton("✅ تأكيد", callback_data='w_confirm')],
        [InlineKeyboardButton("❌ إلغاء", callback_data='back_to_menu')]
    ]
    await update.message.reply_text(
        f"📋 **تأكيد السحب:**\n💰 الأصلي: {pkg['w_amount']}ل.س | ✂️ العمولة: {int(pkg['w_amount']*0.10)}ل.س\n"
        f"✅ **سيصلك: {pkg['w_final']}ل.س** | 📊 يُخصم: {pkg['w_points']}ن\n📱 `{phone}`\n\n⚠️ تأكد من البيانات",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
    )
    return W_CONFIRM

async def withdraw_step_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    pkg = context.user_data
    phone = pkg['w_phone']
    user_db = db.get_user_by_telegram_id(query.from_user.id)
    
    if user_db['points'] < pkg['w_points']:
        await query.edit_message_text("❌ رصيدك غير كافٍ!")
        return ConversationHandler.END
    
    db.deduct_points(user_db['id'], pkg['w_points'])
    rid = db.create_withdrawal_request(
        user_db['id'], pkg['w_points'], pkg['w_amount'], pkg['w_final'], pkg['w_meth'], phone
    )
    
    admin_kb = [
        [InlineKeyboardButton("✅ قبول", callback_data=f"appw_{rid}")],
        [InlineKeyboardButton("❌ رفض", callback_data=f"rejw_{rid}")]
    ]
    
    await context.bot.send_message(
        ADMIN_ID,
        f"💸 **سحب جديد #{rid}**\n👤 {query.from_user.first_name} (`{query.from_user.id}`)\n"
        f"💰 الأصلي: {pkg['w_amount']}ل.س | ✂️ العمولة: {int(pkg['w_amount']*0.10)}ل.س\n"
        f"✅ **للتحويل: {pkg['w_final']}ل.س** | 📊 يُخصم: {pkg['w_points']}ن\n📱 `{phone}`",
        reply_markup=InlineKeyboardMarkup(admin_kb), parse_mode='Markdown'
    )
    await query.edit_message_text("✅ **تم استلام طلب السحب!** سيتم إخطارك عند التنفيذ.")
    return ConversationHandler.END

# ========== قرارات الأدمن ==========
async def handle_admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    
    try:
        action = data[:4]
        rid = int(data[5:])
        
        if action in ["appc", "rejc"]:
            charge_data = db.get_charge_request_details(rid)
            if not charge_data:
                await query.edit_message_text(f"❌ الطلب #{rid} غير موجود")
                return
            
            player_tid = charge_data.get('telegram_id')
            if not player_tid:
                await query.edit_message_text(f"❌ لا يمكن تحديد اللاعب")
                return
            
            if action == "appc":
                db.update_charge_status(rid, 'approved', query.from_user.id)
                await context.bot.send_message(
                    player_tid,
                    f"🎉 **تم قبول شحنك!**\n\n✅ أُضيف **{charge_data['points']} نقطة**\n"
                    f"💰 القيمة: {charge_data['points'] * POINTS_PER_SYP:,} ل.س\n\n🎮 ابدأ اللعب!"
                )
                await query.edit_message_text(f"✅ **تم قبول الشحن #{rid}**")
            else:
                db.update_charge_status(rid, 'rejected', query.from_user.id)
                await context.bot.send_message(
                    player_tid,
                    "❌ **تم رفض طلب الشحن**\n\n⚠️ يرجى التأكد من:\n• رقم الهاتف\n• رقم العملية\n\nثم أعد المحاولة."
                )
                await query.edit_message_text(f"❌ **تم رفض الشحن #{rid}**")
                
        elif action in ["appw", "rejw"]:
            withdraw_data = db.get_withdraw_details(rid)
            if not withdraw_data:
                await query.edit_message_text(f"❌ الطلب #{rid} غير موجود")
                return
            
            player_tid = withdraw_data.get('telegram_id')
            if not player_tid:
                await query.edit_message_text(f"❌ لا يمكن تحديد اللاعب")
                return
            
            if action == "appw":
                db.update_withdraw_status(rid, 'approved')
                await context.bot.send_message(
                    player_tid,
                    f"💸 **تم قبول سحبك!**\n\n✅ سيتم تحويل **{withdraw_data['final_amount']} ل.س** إلى:\n"
                    f"📱 `{withdraw_data['receiver_phone']}`\n\n⏱️ **سيصلك خلال ساعة**"
                )
                await query.edit_message_text(f"✅ **تم قبول السحب #{rid}**")
            else:
                db.add_points(withdraw_data['user_id'], withdraw_data['amount_points'])
                db.update_withdraw_status(rid, 'rejected')
                await context.bot.send_message(
                    player_tid,
                    "❌ **تم رفض السحب**\n\n⚠️ الرجاء التأكد من:\n• رقم الهاتف\n• صحة البيانات\n\nثم أعد المحاولة."
                )
                await query.edit_message_text(f"❌ **تم رفض السحب #{rid}**")
                
    except Exception as e:
        logger.error(f"Error in admin decision: {e}", exc_info=True)
        await query.edit_message_text(f"❌ خطأ: {str(e)}")

# ========== أوامر المستخدم ==========
async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_data = db.get_user_by_telegram_id(query.from_user.id)
    syp = user_data['points'] * POINTS_PER_SYP
    await query.edit_message_text(
        f"👤 **معلومات حسابك:**\n\n🆔 `{user_data['telegram_id']}`\n"
        f"👤 {user_data.get('first_name', 'لاعب')}\n💰 **{user_data['points']} نقطة**\n💵 **{syp:,} ل.س**",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]),
        parse_mode='Markdown'
    )

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer("✅ تم الإلغاء")
        await show_main_menu_simple(update.callback_query.from_user.id, update.callback_query)
    elif update.message:
        await update.message.reply_text("✅ **تم الإلغاء والعودة للقائمة**")
        await show_main_menu_simple(update.effective_user.id)
    return ConversationHandler.END

async def show_main_menu_simple(user_id, query=None):
    user = db.get_user_by_telegram_id(user_id)
    text = f"🎮 **القائمة**\n👤 {user.get('first_name', 'لاعب')}\n💰 الرصيد: {user['points']} نقطة" if user else "❌ خطأ"
    kb = [
        [InlineKeyboardButton("🎯 لعب", callback_data='choose_level')],
        [InlineKeyboardButton("💳 شحن", callback_data='start_charge'),
         InlineKeyboardButton("💰 سحب", callback_data='start_withdraw')],
        [InlineKeyboardButton("👤 حسابي", callback_data='profile')],
        [InlineKeyboardButton("📞 الدعم", url="https://t.me/AskBelal")]
    ]
    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def main():
    # ✅ إعداد التطبيق مع مهلات شبكة أطول
    application = Application.builder().token(BOT_TOKEN).connect_timeout(60).read_timeout(60).build()

    charge_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_charge, pattern='^start_charge$')],
        states={
            C_PKG: [CallbackQueryHandler(charge_method_menu, pattern='^cp_')],
            C_METH: [CallbackQueryHandler(charge_method_selected, pattern='^cm_')],
            C_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, charge_phone_input)],
            C_TRANS: [MessageHandler(filters.TEXT & ~filters.COMMAND, charge_trans_input)],
            C_CONFIRM: [CallbackQueryHandler(charge_step_final, pattern='^c_confirm$')]
        },
        fallbacks=[CommandHandler('start', start), CallbackQueryHandler(cancel_handler, pattern='^back_to_menu$')]
    )

    withdraw_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_withdraw, pattern='^start_withdraw$')],
        states={
            W_METH: [CallbackQueryHandler(withdraw_method_selected, pattern='^wm_')],
            W_AMT: [CallbackQueryHandler(withdraw_amount_selected, pattern='^wa_')],
            W_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_phone_input)],
            W_CONFIRM: [CallbackQueryHandler(withdraw_step_final, pattern='^w_confirm$')]
        },
        fallbacks=[CommandHandler('start', start), CallbackQueryHandler(cancel_handler, pattern='^back_to_menu$')]
    )

    application.add_handler(charge_h)
    application.add_handler(withdraw_h)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel_handler))
    application.add_handler(CallbackQueryHandler(choose_level, pattern='^choose_level$'))
    application.add_handler(CallbackQueryHandler(handle_admin_decision, pattern='^(appc|rejc|appw|rejw)_'))
    application.add_handler(CallbackQueryHandler(profile_handler, pattern='^profile$'))
    application.add_handler(CallbackQueryHandler(cancel_handler, pattern='^back_to_menu$'))
    
    logger.info("🤖 Bot started successfully")
    print("🤖 بوت سودوكو يعمل بنجاح...")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()

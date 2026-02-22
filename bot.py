import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from database import Database
import os

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# توكن البوت - ضع التوكن الخاص بك هنا
BOT_TOKEN = '8128461147:AAHXGMSn95ubi9ytEtv60j_MuPc78A76H5E'
GAME_URL = 'https://your-app-url.com'  # رابط تطبيق Flask الخاص بك

db = Database()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # إنشاء حساب جديد أو تسجيل دخول
    user_id = db.create_user(
        telegram_id=user.id,
        username=user.username or user.first_name,
        first_name=user.first_name
    )
    
    # الحصول على نقاط المستخدم
    points = db.get_user_points(user_id)
    
    welcome_message = f"""
🎮 مرحباً بك في لعبة السودوكو يا {user.first_name}!

✨ تم إنشاء حسابك بنجاح
💰 رصيدك الحالي: {points} نقطة (هدية ترحيبية)

📌 يمكنك:
• لعب السودوكو وكسب النقاط
• شحن رصيدك عبر مشاهدة الإعلانات
• التنافس مع الآخرين

👇 اختر من القائمة:
    """
    
    keyboard = [
        [InlineKeyboardButton("🎯 العب سودوكو", url=f"{GAME_URL}/play?user={user.id}")],
        [InlineKeyboardButton("💰 نقاطي", callback_data='points')],
        [InlineKeyboardButton("🏆 لوحة الشرف", callback_data='leaderboard')],
        [InlineKeyboardButton("📊 إحصائياتي", callback_data='stats')],
        [InlineKeyboardButton("🎁 شحن نقاط", callback_data='earn_points')],
        [InlineKeyboardButton("❓ تعليمات", callback_data='help')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_message, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)
    
    if not user_data:
        await query.edit_message_text("❌ الرجاء استخدام /start أولاً")
        return
    
    user_id = user_data[0]
    
    if query.data == 'points':
        points = db.get_user_points(user_id)
        await query.edit_message_text(
            f"💰 رصيدك الحالي: {points} نقطة\n"
            "🎁 اربح المزيد من النقاط عبر:\n"
            "• إكمال الألغاز\n"
            "• مشاهدة الإعلانات\n"
            "• الدعوات"
        )
    
    elif query.data == 'leaderboard':
        leaders = db.get_leaderboard()
        leader_text = "🏆 لوحة الشرف:\n\n"
        for i, leader in enumerate(leaders, 1):
            leader_text += f"{i}. {leader[0]} - {leader[1]} نقطة ({leader[2]} لعبة)\n"
        await query.edit_message_text(leader_text)
    
    elif query.data == 'stats':
        stats = f"""
📊 إحصائياتك:
• النقاط: {user_data[5]}
• الألعاب: {user_data[6]}
• الألعاب المكتملة: {user_data[7]}
        """
        await query.edit_message_text(stats)
    
    elif query.data == 'earn_points':
        keyboard = [
            [InlineKeyboardButton("📺 مشاهدة إعلان (+10 نقاط)", callback_data='watch_ad')],
            [InlineKeyboardButton("🔗 رابط دعوة", callback_data='referral')],
            [InlineKeyboardButton("🔙 رجوع", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🎁 اختر طريقة الشحن:",
            reply_markup=reply_markup
        )
    
    elif query.data == 'watch_ad':
        # هنا يمكنك إضافة إعلانات حقيقية
        db.add_points(user_id, 10, "مشاهدة إعلان")
        await query.edit_message_text(
            "✅ تمت إضافة 10 نقاط إلى رصيدك!\n"
            "يمكنك مشاهدة المزيد من الإعلانات كل ساعة."
        )
    
    elif query.data == 'referral':
        # إنشاء رابط دعوة فريد
        referral_link = f"https://t.me/{(await context.bot.get_me()).username}?start={user.id}"
        await query.edit_message_text(
            f"🔗 رابط دعوتك:\n{referral_link}\n\n"
            "🎁 احصل على 20 نقطة لكل صديق يدخل عبر رابطك!"
        )
    
    elif query.data == 'help':
        help_text = """
❓ تعليمات اللعبة:

🎯 كيفية اللعب:
• املأ الشبكة بالأرقام من 1-9
• كل رقم يظهر مرة واحدة في كل صف
• كل رقم يظهر مرة واحدة في كل عمود
• كل رقم يظهر مرة واحدة في كل مربع 3x3

💰 كسب النقاط:
• إكمال لغز سهل: +20 نقطة
• إكمال لغز متوسط: +40 نقطة
• إكمال لغز صعب: +60 نقطة
• مشاهدة إعلان: +10 نقاط
• دعوة صديق: +20 نقطة
        """
        await query.edit_message_text(help_text)
    
    elif query.data == 'back':
        await start(update, context)

async def referral_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # معالجة روابط الدعوة
    if context.args and len(context.args) > 0:
        referrer_id = int(context.args[0])
        new_user = update.effective_user
        
        # إنشاء حساب للمستخدم الجديد
        user_id = db.create_user(
            telegram_id=new_user.id,
            username=new_user.username or new_user.first_name,
            first_name=new_user.first_name
        )
        
        # مكافأة المُحيل
        db.add_points(referrer_id, 20, "مكافأة دعوة")
        
        await update.message.reply_text(
            "🎉 مرحباً بك! تمت إضافة 100 نقطة ترحيبية لحسابك.\n"
            "شكراً لصديقك على الدعوة!"
        )
    else:
        await start(update, context)

def main():
    # إنشاء التطبيق
    application = Application.builder().token(BOT_TOKEN).build()
    
    # إضافة المعالجات
    application.add_handler(CommandHandler("start", referral_handler))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # تشغيل البوت
    print("🤖 البوت يعمل...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
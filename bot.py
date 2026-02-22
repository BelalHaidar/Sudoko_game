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

# التوكن ورابط اللعبة - غير هذه القيم
BOT_TOKEN = '8128461147:AAHXGMSn95ubi9ytEtv60j_MuPc78A76H5E'  # ضع توكن البوت هنا
GAME_URL = 'https://sudoko-game-s4dt.onrender.com'  # رابط لعبتك

db = Database()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الأمر الرئيسي /start - ينشئ حساب جديد أو يسجل دخول"""
    user = update.effective_user
    
    # إنشاء حساب جديد أو تسجيل دخول
    user_id = db.create_user(
        telegram_id=user.id,
        username=user.username or user.first_name,
        first_name=user.first_name
    )
    
    # الحصول على نقاط المستخدم
    points = db.get_user_points(user_id)
    
    # رسالة الترحيب
    welcome_message = f"""
🎮 **مرحباً بك في لعبة السودوكو يا {user.first_name}!**

✨ تم إنشاء حسابك بنجاح
💰 **رصيدك الحالي:** {points} نقطة (هدية ترحيبية)

📌 **ماذا يمكنك أن تفعل؟**
• العب سودوكو واكسب النقاط
• شاهد إعلانات لشحن رصيدك
• ادع أصدقائك واحصل على مكافآت
• تنافس مع الآخرين على لوحة الشرف

👇 اختر من القائمة أدناه:
    """
    
    # إنشاء الأزرار التفاعلية
    keyboard = [
        [InlineKeyboardButton("🎯 ابدأ اللعب", url=f"{GAME_URL}/play?user={user.id}")],
        [
            InlineKeyboardButton("💰 نقاطي", callback_data='points'),
            InlineKeyboardButton("🏆 لوحة الشرف", callback_data='leaderboard')
        ],
        [
            InlineKeyboardButton("📊 إحصائياتي", callback_data='stats'),
            InlineKeyboardButton("🎁 المكافأة اليومية", callback_data='daily')
        ],
        [
            InlineKeyboardButton("🔗 رابط دعوة", callback_data='referral'),
            InlineKeyboardButton("❓ تعليمات", callback_data='help')
        ]
    ]
    
    # إضافة زر لوحة التحكم للمشرفين
    if db.is_admin(user.id):
        keyboard.append([InlineKeyboardButton("🛠️ لوحة تحكم المشرف", callback_data='admin_panel')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')

async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /play - بدء لعبة جديدة"""
    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)
    
    if not user_data:
        await update.message.reply_text("❌ الرجاء استخدام /start أولاً")
        return
    
    # التحقق من وجود نقاط كافية
    if user_data[5] < 100:
        keyboard = [[InlineKeyboardButton("💰 شحن نقاط", url=f"{GAME_URL}/charge_points?user={user.id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "❌ رصيدك غير كافٍ لبدء لعبة جديدة (تحتاج 100 نقطة).\n"
            "يمكنك شحن رصيدك من خلال الرابط أدناه:",
            reply_markup=reply_markup
        )
        return
    
    # اختيار مستوى الصعوبة
    keyboard = [
        [
            InlineKeyboardButton("🥉 سهل", callback_data='difficulty_easy'),
            InlineKeyboardButton("🥈 متوسط", callback_data='difficulty_medium')
        ],
        [
            InlineKeyboardButton("🥇 صعب", callback_data='difficulty_hard'),
            InlineKeyboardButton("👑 خبير", callback_data='difficulty_expert')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎯 **اختر مستوى الصعوبة:**\n\n"
        "🥉 سهل: +125 نقطة\n"
        "🥈 متوسط: +200 نقطة\n"
        "🥇 صعب: +300 نقطة\n"
        "👑 خبير: +500 نقطة",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /profile - عرض الملف الشخصي"""
    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)
    
    if not user_data:
        await update.message.reply_text("❌ الرجاء استخدام /start أولاً")
        return
    
    # حساب نسبة الفوز
    win_rate = 0
    if user_data[6] > 0:
        win_rate = round((user_data[7] / user_data[6]) * 100, 1)
    
    stats = f"""
📊 **ملفك الشخصي**

👤 **الاسم:** {user_data[3] or user_data[2]}
🆔 **المعرف:** {user_data[1]}
💰 **النقاط:** {user_data[5]}
🎮 **الألعاب:** {user_data[6]}
🏆 **الألعاب المكتملة:** {user_data[7]}
📊 **نسبة الفوز:** {win_rate}%
📅 **تاريخ التسجيل:** {user_data[8][:10]}
    """
    
    keyboard = [
        [InlineKeyboardButton("🎯 العب الآن", url=f"{GAME_URL}/play?user={user.id}")],
        [InlineKeyboardButton("📊 سجل المعاملات", callback_data='my_transactions')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(stats, reply_markup=reply_markup, parse_mode='Markdown')

async def points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /points - عرض النقاط"""
    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)
    
    if not user_data:
        await update.message.reply_text("❌ الرجاء استخدام /start أولاً")
        return
    
    points = db.get_user_points(user_data[0])
    
    message = f"""
💰 **رصيد النقاط**

**نقاطك الحالية:** {points} نقطة

**🎁 كيف تربح المزيد؟**
• إكمال لغز سهل: +125 نقطة
• إكمال لغز متوسط: +200 نقطة
• إكمال لغز صعب: +300 نقطة
• إكمال لغز خبير: +500 نقطة
• مشاهدة إعلان: +10 نقاط
• دعوة صديق: +20 نقطة
• المكافأة اليومية: +15 نقطة
    """
    
    keyboard = [
        [InlineKeyboardButton("💰 شحن نقاط", url=f"{GAME_URL}/charge_points?user={user.id}")],
        [InlineKeyboardButton("🎯 العب الآن", url=f"{GAME_URL}/play?user={user.id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /leaderboard - عرض لوحة الشرف"""
    leaders = db.get_leaderboard(10)
    
    if not leaders:
        await update.message.reply_text("🏆 لا يوجد متسابقين بعد. كن أول من يلعب!")
        return
    
    leader_text = "🏆 **لوحة الشرف**\n\n"
    
    for i, leader in enumerate(leaders, 1):
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        medal = medals.get(i, f"{i}.")
        leader_text += f"{medal} **{leader[0]}**\n"
        leader_text += f"   ⭐ {leader[1]} نقطة | 🎮 {leader[2]} لعبة\n"
    
    user = update.effective_user
    keyboard = [[InlineKeyboardButton("🎯 العب الآن", url=f"{GAME_URL}/play?user={user.id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(leader_text, reply_markup=reply_markup, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /help - عرض المساعدة"""
    help_text = """
❓ **كيفية اللعب**

🎯 **قواعد السودوكو:**
• املأ الشبكة بالأرقام من 1-9
• كل رقم يظهر مرة واحدة في كل صف
• كل رقم يظهر مرة واحدة في كل عمود
• كل رقم يظهر مرة واحدة في كل مربع 3×3

💰 **نظام النقاط:**
• بدء لعبة جديدة: -100 نقطة
• إكمال لغز سهل: +125 نقطة
• إكمال لغز متوسط: +200 نقطة
• إكمال لغز صعب: +300 نقطة
• إكمال لغز خبير: +500 نقطة
• مشاهدة إعلان: +10 نقاط
• دعوة صديق: +20 نقطة
• مكافأة يومية: +15 نقطة
• تلميح: -50 نقطة

📋 **قائمة الأوامر:**
/start - بدء استخدام البوت
/play - بدء لعبة جديدة
/profile - عرض الملف الشخصي
/points - عرض النقاط
/leaderboard - لوحة الشرف
/help - هذه المساعدة
/referral - رابط دعوة
/daily - المكافأة اليومية
/charge - شحن النقاط
    """
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /referral - إنشاء رابط دعوة"""
    user = update.effective_user
    
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user.id}"
    
    message = f"""
🔗 **رابط دعوتك الشخصي**

انسخ الرابط وأرسله لأصدقائك:
`{referral_link}`

🎁 **المكافآت:**
• لكل صديق يسجل عبر رابطك: +20 نقطة
• لكل 5 أصدقاء: +100 نقطة إضافية
• لكل 10 أصدقاء: وسام خاص في الملف الشخصي
    """
    
    keyboard = [[InlineKeyboardButton("📤 مشاركة الرابط", switch_inline_query=f"العب معي سودوكو! {referral_link}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /daily - المكافأة اليومية"""
    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)
    
    if not user_data:
        await update.message.reply_text("❌ الرجاء استخدام /start أولاً")
        return
    
    # التحقق من إمكانية الحصول على المكافأة
    if db.can_claim_daily(user_data[0]):
        db.add_points(user_data[0], 15, "مكافأة يومية")
        message = """
🎁 **المكافأة اليومية**

✅ تم إضافة **15 نقطة** إلى رصيدك!
تعال غداً للحصول على مكافأة جديدة.
        """
    else:
        message = """
⏳ **المكافأة اليومية**

لا يمكنك الحصول على المكافأة الآن.
المكافأة متاحة مرة واحدة كل 24 ساعة.
        """
    
    keyboard = [[InlineKeyboardButton("🎯 العب الآن", url=f"{GAME_URL}/play?user={user.id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /charge - شحن النقاط"""
    user = update.effective_user
    
    charge_url = f"{GAME_URL}/charge_points?user={user.id}"
    
    keyboard = [[InlineKeyboardButton("💰 شحن الآن", url=charge_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = """
💰 **شحن النقاط**

اختر طريقة الدفع المناسبة لك:
• 📱 سيرياتيل كاش
• 📲 MTN Cash
• 💳 Sham Cash

**الباقات المتوفرة:**
• 1000 ل.س = 100 نقطة
• 2500 ل.س = 250 نقطة + 25 هدية
• 5000 ل.س = 500 نقطة + 75 هدية
• 10000 ل.س = 1000 نقطة + 200 هدية

⚠️ بعد الدفع، سيتم مراجعة طلبك وإضافة النقاط يدوياً.
    """
    
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

# ==================== أوامر المشرف ====================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لوحة تحكم المشرف - /admin"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    
    if not db.is_admin(user.id):
        await query.edit_message_text("⛔ هذا الأمر مخصص للمشرفين فقط.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 إحصائيات النظام", callback_data='admin_stats')],
        [InlineKeyboardButton("👥 إدارة المستخدمين", callback_data='admin_users')],
        [InlineKeyboardButton("💰 طلبات الشحن", callback_data='admin_charges')],
        [InlineKeyboardButton("📝 سجل المعاملات", callback_data='admin_transactions')],
        [InlineKeyboardButton("🎮 إحصائيات الألعاب", callback_data='admin_games')],
        [InlineKeyboardButton("👑 إدارة المشرفين", callback_data='admin_manage')],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "🛠️ **لوحة تحكم المشرف**\n\nاختر ما تريد:", 
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إحصائيات النظام"""
    query = update.callback_query
    await query.answer()
    
    stats = db.get_system_stats()
    
    message = f"""
📊 **إحصائيات النظام**

👥 **المستخدمين:**
• إجمالي المستخدمين: {stats['total_users']}
• نشط اليوم: {stats['active_today']}

💰 **النقاط:**
• إجمالي النقاط: {stats['total_points']}
• متوسط النقاط: {stats['avg_points']}

🎮 **الألعاب:**
• إجمالي الألعاب: {stats['total_games']}
• الألعاب المكتملة: {stats['completed_games']}

📝 **المعاملات:**
• إجمالي المعاملات: {stats['total_transactions']}
• طلبات شحن معلقة: {stats['pending_charges']}
    """
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data='admin_panel')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة المستخدمين"""
    query = update.callback_query
    await query.answer()
    
    users, total = db.get_all_users(page=1)
    
    message = f"👥 **المستخدمين** (الإجمالي: {total})\n\n"
    
    for user in users[:10]:
        message += f"🆔 {user[1]}\n"
        message += f"👤 {user[3]} (@{user[2]})\n"
        message += f"💰 {user[4]} نقطة | 🎮 {user[5]} لعبة\n"
        message += f"📅 {user[7][:10]}\n"
        message += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    
    keyboard = [
        [InlineKeyboardButton("🔍 بحث عن مستخدم", callback_data='admin_search_user')],
        [InlineKeyboardButton("📄 الصفحة التالية", callback_data='admin_users_page_2')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='admin_panel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_charges(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض طلبات الشحن المعلقة"""
    query = update.callback_query
    await query.answer()
    
    requests = db.get_charge_requests('pending')
    
    if not requests:
        await query.edit_message_text("✅ لا توجد طلبات شحن معلقة حالياً.")
        return
    
    for req in requests[:5]:
        message = f"""
💰 **طلب شحن #{req[0]}**

👤 **المستخدم:** {req[3]} (@{req[2]})
💵 **المبلغ:** {req[4]} ل.س
⭐ **النقاط:** {req[5]}
📱 **طريقة الدفع:** {req[6]}
📞 **الرقم:** {req[7]}
🕐 **التاريخ:** {req[9][:16]}
        """
        
        keyboard = [
            [
                InlineKeyboardButton(f"✅ قبول", callback_data=f'approve_charge_{req[0]}'),
                InlineKeyboardButton(f"❌ رفض", callback_data=f'reject_charge_{req[0]}')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    # حذف الرسالة الأصلية
    await query.message.delete()

async def approve_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الموافقة على طلب شحن"""
    query = update.callback_query
    await query.answer()
    
    request_id = int(query.data.split('_')[2])
    admin = update.effective_user
    
    db.update_charge_status(request_id, 'approved', admin.id)
    
    await query.edit_message_text(f"✅ تمت الموافقة على طلب الشحن #{request_id}")

async def reject_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رفض طلب شحن"""
    query = update.callback_query
    await query.answer()
    
    request_id = int(query.data.split('_')[2])
    admin = update.effective_user
    
    db.update_charge_status(request_id, 'rejected', admin.id)
    
    await query.edit_message_text(f"❌ تم رفض طلب الشحن #{request_id}")

async def admin_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض سجل المعاملات"""
    query = update.callback_query
    await query.answer()
    
    transactions, total = db.get_all_transactions(page=1, per_page=10)
    
    message = f"📝 **آخر المعاملات** (الإجمالي: {total})\n\n"
    
    for trans in transactions:
        emoji = {
            'earn': '➕',
            'spend': '➖',
            'bonus': '🎁',
            'admin_add': '💰',
            'admin_remove': '🔻'
        }.get(trans[5], '🔄')
        
        message += f"{emoji} **{trans[3]}**\n"
        message += f"   المبلغ: {trans[4]} نقطة\n"
        message += f"   النوع: {trans[5]}\n"
        message += f"   {trans[7][:16]}\n"
        message += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data='admin_panel')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def my_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض معاملات المستخدم"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)
    
    if not user_data:
        await query.edit_message_text("❌ الرجاء استخدام /start أولاً")
        return
    
    transactions = db.get_user_transactions(user_data[0], 10)
    
    message = "📊 **آخر معاملاتك**\n\n"
    
    for trans in transactions:
        emoji = '➕' if trans[1] > 0 else '➖'
        message += f"{emoji} {abs(trans[1])} نقطة - {trans[3]}\n"
        message += f"   🕐 {trans[4][:16]}\n"
        message += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data='back_to_main')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأزرار التفاعلية الرئيسي"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)
    
    if not user_data and not query.data.startswith('admin_'):
        await query.edit_message_text("❌ الرجاء استخدام /start أولاً")
        return
    
    user_id = user_data[0] if user_data else None
    
    # معالجة اختيار مستوى الصعوبة
    if query.data.startswith('difficulty_'):
        difficulty = query.data.replace('difficulty_', '')
        play_url = f"{GAME_URL}/play?user={user.id}&difficulty={difficulty}"
        
        keyboard = [[InlineKeyboardButton("🎯 اضغط لبدء اللعبة", url=play_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ تم اختيار المستوى: **{difficulty}**\n\n"
            "اضغط على الزر لبدء اللعبة:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == 'points':
        points = db.get_user_points(user_id)
        await query.edit_message_text(
            f"💰 **نقاطك الحالية:** {points} نقطة",
            parse_mode='Markdown'
        )
    
    elif query.data == 'leaderboard':
        leaders = db.get_leaderboard(5)
        text = "🏆 **أفضل 5 لاعبين:**\n\n"
        for i, leader in enumerate(leaders, 1):
            text += f"{i}. {leader[0]}: {leader[1]} نقطة\n"
        await query.edit_message_text(text, parse_mode='Markdown')
    
    elif query.data == 'stats':
        stats = f"""
📊 **إحصائياتك:**
• النقاط: {user_data[5]}
• الألعاب: {user_data[6]}
• الألعاب المكتملة: {user_data[7]}
        """
        await query.edit_message_text(stats, parse_mode='Markdown')
    
    elif query.data == 'daily':
        if db.can_claim_daily(user_id):
            db.add_points(user_id, 15, "مكافأة يومية")
            await query.edit_message_text("✅ تمت إضافة 15 نقطة مكافأة يومية!")
        else:
            await query.edit_message_text("⏳ يمكنك الحصول على المكافأة مرة كل 24 ساعة.")
    
    elif query.data == 'referral':
        bot_username = (await context.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start={user.id}"
        await query.edit_message_text(
            f"🔗 رابط دعوتك:\n`{referral_link}`",
            parse_mode='Markdown'
        )
    
    elif query.data == 'help':
        await help_command(update, context)
    
    elif query.data == 'my_transactions':
        await my_transactions(update, context)
    
    elif query.data == 'admin_panel':
        await admin_panel(update, context)
    
    elif query.data == 'admin_stats':
        await admin_stats(update, context)
    
    elif query.data == 'admin_users':
        await admin_users(update, context)
    
    elif query.data == 'admin_charges':
        await admin_charges(update, context)
    
    elif query.data == 'admin_transactions':
        await admin_transactions(update, context)
    
    elif query.data.startswith('approve_charge_'):
        await approve_charge(update, context)
    
    elif query.data.startswith('reject_charge_'):
        await reject_charge(update, context)
    
    elif query.data == 'back_to_main':
        # العودة للقائمة الرئيسية
        keyboard = [
            [InlineKeyboardButton("🎯 ابدأ اللعب", url=f"{GAME_URL}/play?user={user.id}")],
            [
                InlineKeyboardButton("💰 نقاطي", callback_data='points'),
                InlineKeyboardButton("🏆 لوحة الشرف", callback_data='leaderboard')
            ],
            [
                InlineKeyboardButton("📊 إحصائياتي", callback_data='stats'),
                InlineKeyboardButton("🎁 المكافأة اليومية", callback_data='daily')
            ],
            [
                InlineKeyboardButton("🔗 رابط دعوة", callback_data='referral'),
                InlineKeyboardButton("❓ تعليمات", callback_data='help')
            ]
        ]
        
        if db.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("🛠️ لوحة تحكم المشرف", callback_data='admin_panel')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🎮 **القائمة الرئيسية**\nاختر ما تريد:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def referral_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج روابط الدعوة"""
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
            "🎉 **مرحباً بك!**\n\n"
            "تمت إضافة 100 نقطة ترحيبية لحسابك.\n"
            "وشكراً لصديقك على الدعوة! استمتع باللعب.",
            parse_mode='Markdown'
        )
    else:
        await start(update, context)

async def set_commands(application):
    """تعيين قائمة الأوامر في البوت"""
    commands = [
        ("start", "بدء استخدام البوت"),
        ("play", "بدء لعبة جديدة"),
        ("profile", "عرض الملف الشخصي"),
        ("points", "عرض نقاطك"),
        ("leaderboard", "عرض لوحة الشرف"),
        ("daily", "المكافأة اليومية"),
        ("referral", "رابط الدعوة"),
        ("charge", "شحن النقاط"),
        ("help", "عرض المساعدة"),
    ]
    
    await application.bot.set_my_commands(commands)

def main():
    """الدالة الرئيسية لتشغيل البوت"""
    # إنشاء التطبيق
    application = Application.builder().token(BOT_TOKEN).build()
    
    # إضافة معالجات الأوامر
    application.add_handler(CommandHandler("start", referral_handler))
    application.add_handler(CommandHandler("play", play))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("points", points))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("referral", referral))
    application.add_handler(CommandHandler("daily", daily))
    application.add_handler(CommandHandler("charge", charge))
    
    # معالج الأزرار
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # تعيين الأوامر عند بدء التشغيل
    application.post_init = set_commands
    
    # تشغيل البوت
    print("🤖 البوت يعمل...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

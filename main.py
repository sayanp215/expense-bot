import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
import calendar

# States for conversation handler
CATEGORY, AMOUNT, DESCRIPTION = range(3)


# Database setup
def init_db():
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    # Create expenses table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT,
            date TEXT NOT NULL
        )
    ''')

    # Create categories table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(user_id, name)
        )
    ''')

    conn.commit()
    conn.close()


# Default categories
DEFAULT_CATEGORIES = [
    '🍔 Food', '🚗 Transport', '🏠 Rent', '⚡ Utilities',
    '🎬 Entertainment', '🛒 Shopping', '💊 Health', '📚 Education', '💰 Other'
]


def add_default_categories(user_id):
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    for category in DEFAULT_CATEGORIES:
        try:
            cursor.execute('INSERT INTO categories (user_id, name) VALUES (?, ?)',
                           (user_id, category))
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    conn.close()


def get_user_categories(user_id):
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM categories WHERE user_id = ?', (user_id,))
    categories = [row[0] for row in cursor.fetchall()]
    conn.close()
    return categories if categories else DEFAULT_CATEGORIES


# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_default_categories(user_id)

    keyboard = [
        [InlineKeyboardButton("➕ Add Expense", callback_data='add_expense')],
        [InlineKeyboardButton("📊 Monthly Report", callback_data='monthly_report')],
        [InlineKeyboardButton("📈 Category Summary", callback_data='category_summary')],
        [InlineKeyboardButton("📅 Custom Date Range", callback_data='date_range')],
        [InlineKeyboardButton("🗑️ Delete Last", callback_data='delete_last')],
        [InlineKeyboardButton("⚙️ Manage Categories", callback_data='manage_categories')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "💰 *Welcome to Expense Tracker Bot!*\n\n"
        "Track your expenses efficiently and get monthly insights.\n"
        "Choose an option below:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("➕ Add Expense", callback_data='add_expense')],
        [InlineKeyboardButton("📊 Monthly Report", callback_data='monthly_report')],
        [InlineKeyboardButton("📈 Category Summary", callback_data='category_summary')],
        [InlineKeyboardButton("📅 Custom Date Range", callback_data='date_range')],
        [InlineKeyboardButton("🗑️ Delete Last", callback_data='delete_last')],
        [InlineKeyboardButton("⚙️ Manage Categories", callback_data='manage_categories')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "💰 *Expense Tracker Menu*\n\nChoose an option:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


# Add expense flow
async def add_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    categories = get_user_categories(user_id)

    # Create keyboard with categories (2 per row)
    keyboard = []
    for i in range(0, len(categories), 2):
        row = [InlineKeyboardButton(categories[i], callback_data=f'cat_{categories[i]}')]
        if i + 1 < len(categories):
            row.append(InlineKeyboardButton(categories[i + 1], callback_data=f'cat_{categories[i + 1]}'))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data='menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "📁 *Select Category:*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

    return CATEGORY


async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category = query.data.replace('cat_', '')
    context.user_data['category'] = category

    await query.edit_message_text(
        f"Category: *{category}*\n\n💵 Enter the amount:",
        parse_mode='Markdown'
    )

    return AMOUNT


async def amount_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        if amount <= 0:
            raise ValueError

        context.user_data['amount'] = amount

        await update.message.reply_text(
            "📝 Enter a description (or send /skip to skip):"
        )

        return DESCRIPTION
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid amount. Please enter a valid number:"
        )
        return AMOUNT


async def description_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    description = update.message.text if update.message.text != '/skip' else 'No description'

    user_id = update.effective_user.id
    category = context.user_data['category']
    amount = context.user_data['amount']
    date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Save to database
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO expenses (user_id, category, amount, description, date)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, category, amount, description, date))
    conn.commit()
    conn.close()

    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"✅ *Expense Added!*\n\n"
        f"Category: {category}\n"
        f"Amount: ₹{amount:.2f}\n"
        f"Description: {description}\n"
        f"Date: {datetime.now().strftime('%d %b %Y, %I:%M %p')}",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

    return ConversationHandler.END


# Monthly report
async def monthly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    current_month = datetime.now().strftime('%Y-%m')

    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    # Get total for current month
    cursor.execute('''
        SELECT SUM(amount) FROM expenses
        WHERE user_id = ? AND date LIKE ?
    ''', (user_id, f'{current_month}%'))

    total = cursor.fetchone()[0] or 0

    # Get expenses by category
    cursor.execute('''
        SELECT category, SUM(amount), COUNT(*)
        FROM expenses
        WHERE user_id = ? AND date LIKE ?
        GROUP BY category
        ORDER BY SUM(amount) DESC
    ''', (user_id, f'{current_month}%'))

    categories_data = cursor.fetchall()
    conn.close()

    if not categories_data:
        message = f"📊 *Monthly Report - {datetime.now().strftime('%B %Y')}*\n\n" \
                  "No expenses recorded this month."
    else:
        message = f"📊 *Monthly Report - {datetime.now().strftime('%B %Y')}*\n\n" \
                  f"💰 Total Spent: *₹{total:.2f}*\n\n" \
                  "*Breakdown by Category:*\n"

        for category, amount, count in categories_data:
            percentage = (amount / total) * 100
            message += f"\n{category}\n"
            message += f"  ₹{amount:.2f} ({count} transactions) - {percentage:.1f}%\n"

    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


# Category summary (all time)
async def category_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT category, SUM(amount), COUNT(*), MIN(date), MAX(date)
        FROM expenses
        WHERE user_id = ?
        GROUP BY category
        ORDER BY SUM(amount) DESC
    ''', (user_id,))

    categories_data = cursor.fetchall()

    cursor.execute('SELECT SUM(amount) FROM expenses WHERE user_id = ?', (user_id,))
    total = cursor.fetchone()[0] or 0

    conn.close()

    if not categories_data:
        message = "📈 *Category Summary (All Time)*\n\nNo expenses recorded yet."
    else:
        message = f"📈 *Category Summary (All Time)*\n\n" \
                  f"💰 Total: *₹{total:.2f}*\n\n"

        for category, amount, count, first_date, last_date in categories_data:
            percentage = (amount / total) * 100
            message += f"*{category}*\n"
            message += f"  ₹{amount:.2f} | {count} transactions | {percentage:.1f}%\n\n"

    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


# Delete last expense
async def delete_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    # Get last expense
    cursor.execute('''
        SELECT id, category, amount, description, date
        FROM expenses
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
    ''', (user_id,))

    last_expense = cursor.fetchone()

    if last_expense:
        cursor.execute('DELETE FROM expenses WHERE id = ?', (last_expense[0],))
        conn.commit()
        message = f"🗑️ *Last expense deleted:*\n\n" \
                  f"Category: {last_expense[1]}\n" \
                  f"Amount: ₹{last_expense[2]:.2f}\n" \
                  f"Description: {last_expense[3]}"
    else:
        message = "No expenses to delete."

    conn.close()

    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


# Cancel conversation
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Operation cancelled. Use /start to begin again."
    )
    return ConversationHandler.END


def main():
    # Initialize database
    init_db()

    # Create application
    TOKEN = '6793523642:AAEX6Kbb_La-OxHJlqMkKx5n54XqVNquiUo'  # Replace with your bot token from @BotFather
    application = Application.builder().token(TOKEN).build()

    # Conversation handler for adding expenses
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_expense_start, pattern='^add_expense$')],
        states={
            CATEGORY: [CallbackQueryHandler(category_selected, pattern='^cat_')],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, amount_entered)],
            DESCRIPTION: [MessageHandler(filters.TEXT, description_entered)]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )

    # Add handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(menu, pattern='^menu$'))
    application.add_handler(CallbackQueryHandler(monthly_report, pattern='^monthly_report$'))
    application.add_handler(CallbackQueryHandler(category_summary, pattern='^category_summary$'))
    application.add_handler(CallbackQueryHandler(delete_last, pattern='^delete_last$'))

    # Start bot
    print("Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

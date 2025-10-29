import sqlite3
import os
from datetime import datetime, timedelta
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
import pandas as pd
from io import BytesIO

# States for conversation handler
CATEGORY, SUBCATEGORY, AMOUNT, DESCRIPTION, ACCOUNT = range(5)
ACCOUNT_SELECT, BALANCE_AMOUNT = range(5, 7)


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
            subcategory TEXT,
            amount REAL NOT NULL,
            description TEXT,
            account TEXT,
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

    # Create account balances table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS account_balances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            account_name TEXT NOT NULL,
            initial_balance REAL NOT NULL DEFAULT 0,
            current_balance REAL NOT NULL DEFAULT 0,
            last_updated TEXT NOT NULL,
            UNIQUE(user_id, account_name)
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


# Get common subcategories for a category
def get_subcategories_for_category(user_id, category):
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT DISTINCT subcategory
        FROM expenses
        WHERE user_id = ? AND category = ? AND subcategory IS NOT NULL
        ORDER BY subcategory
    ''', (user_id, category))

    subcategories = [row[0] for row in cursor.fetchall()]
    conn.close()

    default_subcats = {
        '🍔 Food': ['Breakfast', 'Lunch', 'Dinner', 'Snacks', 'Tea/Coffee'],
        '🍜 Food': ['Breakfast', 'Lunch', 'Dinner', 'Snacks', 'Tea/Coffee'],
        '🚗 Transport': ['Bus', 'Train', 'Auto', 'Taxi', 'Fuel', 'Metro'],
        '🚖 Transport': ['Bus', 'Train', 'Auto', 'Taxi', 'Fuel', 'Metro'],
        '🏠 Rent': ['House Rent', 'Maintenance', 'Deposit'],
        '⚡ Utilities': ['Electricity', 'Water', 'Gas', 'Internet', 'Phone'],
        '🎬 Entertainment': ['Movies', 'Games', 'Concerts', 'Sports'],
        '🛒 Shopping': ['Groceries', 'Clothing', 'Electronics', 'Home Items'],
        '💊 Health': ['Medicine', 'Doctor', 'Tests', 'Gym'],
        '📚 Education': ['Books', 'Courses', 'Tuition', 'Stationery'],
        '📱Mobile Recharge': ['Data Pack', 'Recharge', 'Bill Payment'],
        '🪑 Household': ['Furniture', 'Appliances', 'Repairs', 'Cleaning']
    }

    base_category = category
    if base_category in default_subcats:
        for subcat in default_subcats[base_category]:
            if subcat not in subcategories:
                subcategories.append(subcat)

    return subcategories if subcategories else ['General']


# Get user's payment accounts
def get_user_accounts(user_id):
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT DISTINCT account
        FROM expenses
        WHERE user_id = ? AND account IS NOT NULL
        ORDER BY account
    ''', (user_id,))

    accounts = [row[0] for row in cursor.fetchall()]
    conn.close()

    default_accounts = ['Cash', 'Online', 'Credit Card', 'Debit Card', 'UPI', 'Mobile Wallet']

    for acc in default_accounts:
        if acc not in accounts:
            accounts.append(acc)

    return accounts


# Account balance functions
def get_account_balance(user_id, account_name):
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT initial_balance, current_balance, last_updated
        FROM account_balances
        WHERE user_id = ? AND account_name = ?
    ''', (user_id, account_name))

    result = cursor.fetchone()
    conn.close()

    if result:
        return {
            'initial': result[0],
            'current': result[1],
            'last_updated': result[2]
        }
    return None


def update_account_balance(user_id, account_name, amount, operation='set'):
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute('''
        SELECT current_balance FROM account_balances
        WHERE user_id = ? AND account_name = ?
    ''', (user_id, account_name))

    existing = cursor.fetchone()

    if existing:
        if operation == 'set':
            new_balance = amount
        elif operation == 'add':
            new_balance = existing[0] + amount
        elif operation == 'subtract':
            new_balance = existing[0] - amount
        else:
            new_balance = amount

        cursor.execute('''
            UPDATE account_balances
            SET current_balance = ?, last_updated = ?
            WHERE user_id = ? AND account_name = ?
        ''', (new_balance, current_time, user_id, account_name))
    else:
        cursor.execute('''
            INSERT INTO account_balances (user_id, account_name, initial_balance, current_balance, last_updated)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, account_name, amount, amount, current_time))

    conn.commit()
    conn.close()


def get_all_account_balances(user_id):
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT account_name, initial_balance, current_balance, last_updated
        FROM account_balances
        WHERE user_id = ?
        ORDER BY account_name
    ''', (user_id,))

    balances = cursor.fetchall()
    conn.close()

    return balances


# Get list of months with expenses
def get_available_months(user_id):
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT DISTINCT strftime('%Y-%m', date) as month
        FROM expenses
        WHERE user_id = ?
        ORDER BY month DESC
    ''', (user_id,))

    months = [row[0] for row in cursor.fetchall()]
    conn.close()
    return months


# Generate professional Excel report
async def generate_professional_excel_report(user_id, year_month, context):
    conn = sqlite3.connect('expenses.db')

    query = '''
        SELECT date, category, subcategory, amount, description, account
        FROM expenses
        WHERE user_id = ? AND date LIKE ?
        ORDER BY date DESC
    '''

    df = pd.read_sql_query(query, conn, params=(user_id, f'{year_month}%'))
    conn.close()

    if df.empty:
        return None

    df['date'] = pd.to_datetime(df['date'])
    df['Day'] = df['date'].dt.strftime('%d')
    df['Weekday'] = df['date'].dt.strftime('%A')
    df['Date'] = df['date'].dt.strftime('%d/%m/%Y')
    df['Time'] = df['date'].dt.strftime('%H:%M')

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:

        # 1. OVERVIEW SHEET
        month_name = datetime.strptime(year_month, '%Y-%m').strftime('%B %Y')
        overview_data = {
            'Metric': [
                'Total Expenses',
                'Number of Transactions',
                'Average Transaction',
                'Highest Expense',
                'Lowest Expense',
                'Daily Average',
                'Most Expensive Day',
                'Most Spent Category'
            ],
            'Value': [
                f"₹{df['amount'].sum():.2f}",
                len(df),
                f"₹{df['amount'].mean():.2f}",
                f"₹{df['amount'].max():.2f}",
                f"₹{df['amount'].min():.2f}",
                f"₹{df['amount'].sum() / df['Day'].nunique():.2f}",
                df.groupby('Date')['amount'].sum().idxmax(),
                df.groupby('category')['amount'].sum().idxmax()
            ]
        }
        overview_df = pd.DataFrame(overview_data)
        overview_df.to_excel(writer, sheet_name='📊 Overview', index=False)

        # 2. CATEGORY SUMMARY
        category_summary = df.groupby('category').agg({
            'amount': ['sum', 'count', 'mean', 'max', 'min']
        }).reset_index()
        category_summary.columns = ['Category', 'Total Amount', 'Transactions', 'Avg Amount', 'Max', 'Min']
        category_summary = category_summary.sort_values('Total Amount', ascending=False)
        total_spent = category_summary['Total Amount'].sum()
        category_summary['Percentage'] = (category_summary['Total Amount'] / total_spent * 100).round(2)
        category_summary['Percentage'] = category_summary['Percentage'].astype(str) + '%'
        category_summary['Total Amount'] = '₹' + category_summary['Total Amount'].round(2).astype(str)
        category_summary['Avg Amount'] = '₹' + category_summary['Avg Amount'].round(2).astype(str)
        category_summary['Max'] = '₹' + category_summary['Max'].round(2).astype(str)
        category_summary['Min'] = '₹' + category_summary['Min'].round(2).astype(str)
        category_summary.to_excel(writer, sheet_name='📁 Categories', index=False)

        # 3. DAILY BREAKDOWN
        daily_breakdown = df.groupby(['Date', 'Weekday']).agg({
            'amount': ['sum', 'count']
        }).reset_index()
        daily_breakdown.columns = ['Date', 'Weekday', 'Total Spent', 'Transactions']
        daily_breakdown = daily_breakdown.sort_values('Date', ascending=False)
        daily_breakdown['Total Spent'] = '₹' + daily_breakdown['Total Spent'].round(2).astype(str)
        daily_breakdown.to_excel(writer, sheet_name='📅 Daily', index=False)

        # 4. ACCOUNT-WISE BREAKDOWN
        if df['account'].notna().any():
            account_breakdown = df.groupby('account').agg({
                'amount': ['sum', 'count']
            }).reset_index()
            account_breakdown.columns = ['Account', 'Total Spent', 'Transactions']
            account_breakdown = account_breakdown.sort_values('Total Spent', ascending=False)
            account_total = account_breakdown['Total Spent'].sum()
            account_breakdown['Percentage'] = (account_breakdown['Total Spent'] / account_total * 100).round(2)
            account_breakdown['Total Spent'] = '₹' + account_breakdown['Total Spent'].round(2).astype(str)
            account_breakdown['Percentage'] = account_breakdown['Percentage'].astype(str) + '%'
            account_breakdown.to_excel(writer, sheet_name='💳 Accounts', index=False)

        # 5. SUBCATEGORY BREAKDOWN
        if df['subcategory'].notna().any():
            subcat_df = df[df['subcategory'].notna()].groupby(['category', 'subcategory']).agg({
                'amount': ['sum', 'count']
            }).reset_index()
            subcat_df.columns = ['Category', 'Subcategory', 'Total', 'Count']
            subcat_df = subcat_df.sort_values(['Category', 'Total'], ascending=[True, False])
            subcat_df['Total'] = '₹' + subcat_df['Total'].round(2).astype(str)
            subcat_df.to_excel(writer, sheet_name='📂 Subcategories', index=False)

        # 6. TOP EXPENSES
        top_expenses = df.nlargest(min(20, len(df)), 'amount')[
            ['Date', 'Time', 'category', 'amount', 'description']].copy()
        top_expenses['amount'] = '₹' + top_expenses['amount'].round(2).astype(str)
        top_expenses.to_excel(writer, sheet_name='💰 Top Expenses', index=False)

        # 7. ALL TRANSACTIONS
        detailed_df = df[
            ['Date', 'Time', 'Weekday', 'category', 'subcategory', 'amount', 'description', 'account']].copy()
        detailed_df['amount'] = '₹' + detailed_df['amount'].round(2).astype(str)
        detailed_df.to_excel(writer, sheet_name='📝 All Transactions', index=False)

        # 8. CATEGORY-WISE SHEETS
        for category in df['category'].unique():
            category_df = df[df['category'] == category][
                ['Date', 'Time', 'amount', 'description', 'subcategory', 'account']].copy()
            category_df = category_df.sort_values('Date', ascending=False)
            category_df['amount'] = '₹' + category_df['amount'].round(2).astype(str)
            sheet_name = category[:31].replace('/', '-')
            category_df.to_excel(writer, sheet_name=sheet_name, index=False)

    output.seek(0)
    return output


# Import expenses from Money Manager format
async def handle_excel_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    document = update.message.document

    if not (document.file_name.endswith('.xlsx') or document.file_name.endswith('.xls') or document.file_name.endswith(
            '.csv')):
        await update.message.reply_text(
            "❌ Please upload a valid Excel file (.xlsx, .xls) or CSV file (.csv)"
        )
        return

    await update.message.reply_text("📥 Downloading your file...")

    file = await context.bot.get_file(document.file_id)
    file_path = f"temp_{user_id}_{document.file_name}"
    await file.download_to_drive(file_path)

    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)

        await update.message.reply_text("📊 Processing your expenses...")

        column_mapping = {
            'date': ['Date', 'date', 'DATE', 'day', 'Day', 'Transaction Date'],
            'category': ['Category', 'category', 'CATEGORY', 'type', 'Type'],
            'subcategory': ['Subcategory', 'subcategory', 'Sub Category', 'SubCategory'],
            'amount': ['Amount', 'amount', 'AMOUNT', 'INR', 'price', 'Price', 'cost', 'Cost'],
            'description': ['Note', 'note', 'Description', 'description', 'DESCRIPTION', 'details', 'Details'],
            'account': ['Account', 'account', 'Payment Method', 'Method']
        }

        actual_columns = {}
        for key, possible_names in column_mapping.items():
            for col in df.columns:
                if col in possible_names:
                    actual_columns[key] = col
                    break

        if 'category' not in actual_columns or 'amount' not in actual_columns:
            await update.message.reply_text(
                "❌ File must have at least 'Category' and 'Amount' columns.\n\n"
                "Supported formats:\n"
                "✅ Money Manager exports\n"
                "✅ Generic Excel: Date, Category, Amount, Description"
            )
            os.remove(file_path)
            return

        if 'Income/Expense' in df.columns:
            df = df[df['Income/Expense'] == 'Expense']

        conn = sqlite3.connect('expenses.db')
        cursor = conn.cursor()

        imported_count = 0
        failed_count = 0

        for index, row in df.iterrows():
            try:
                category = str(row[actual_columns['category']]).strip()
                amount = float(row[actual_columns['amount']])

                if amount <= 0:
                    continue

                subcategory = None
                if 'subcategory' in actual_columns:
                    subcat_value = row[actual_columns['subcategory']]
                    if pd.notna(subcat_value) and str(subcat_value).strip():
                        subcategory = str(subcat_value).strip()

                if 'date' in actual_columns:
                    try:
                        date_value = row[actual_columns['date']]
                        if isinstance(date_value, str):
                            expense_date = pd.to_datetime(date_value, format='%d/%m/%Y %H:%M:%S', errors='coerce')
                            if pd.isna(expense_date):
                                expense_date = pd.to_datetime(date_value, errors='coerce')
                        else:
                            expense_date = pd.to_datetime(date_value)

                        if pd.notna(expense_date):
                            expense_date = expense_date.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            expense_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        expense_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                else:
                    expense_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                description = 'Imported from Excel'
                if 'description' in actual_columns:
                    desc_value = row[actual_columns['description']]
                    if pd.notna(desc_value) and str(desc_value).strip():
                        description = str(desc_value).strip()

                account = None
                if 'account' in actual_columns:
                    acc_value = row[actual_columns['account']]
                    if pd.notna(acc_value) and str(acc_value).strip():
                        account = str(acc_value).strip()

                cursor.execute('''
                    INSERT INTO expenses (user_id, category, subcategory, amount, description, account, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, category, subcategory, amount, description, account, expense_date))

                imported_count += 1

            except Exception as e:
                failed_count += 1
                print(f"Error importing row {index}: {e}")

        conn.commit()
        conn.close()

        os.remove(file_path)

        message = f"✅ *Import Successful!*\n\n" \
                  f"📊 Imported: *{imported_count}* expenses\n"

        if failed_count > 0:
            message += f"⚠️ Failed: {failed_count} rows\n"

        conn = sqlite3.connect('expenses.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT category, SUM(amount), COUNT(*)
            FROM expenses
            WHERE user_id = ?
            GROUP BY category
            ORDER BY SUM(amount) DESC
            LIMIT 5
        ''', (user_id,))

        top_categories = cursor.fetchall()
        conn.close()

        if top_categories:
            message += f"\n*Top Categories Imported:*\n"
            for cat, amt, count in top_categories:
                message += f"{cat}: ₹{amt:.2f} ({count} txns)\n"

        message += f"\n💡 Use /start to view reports!"

        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(
            f"❌ Error processing file: {str(e)}\n\n"
            "Supported formats:\n"
            "✅ Money Manager exports (.xls, .xlsx)\n"
            "✅ Generic Excel with Date, Category, Amount columns"
        )
        if os.path.exists(file_path):
            os.remove(file_path)


# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_default_categories(user_id)

    keyboard = [
        [InlineKeyboardButton("➕ Add Expense", callback_data='add_expense')],
        [InlineKeyboardButton("📊 Current Month Report", callback_data='current_month_report')],
        [InlineKeyboardButton("📅 Previous Months", callback_data='previous_months')],
        [InlineKeyboardButton("💳 Manage Account Balances", callback_data='manage_accounts')],
        [InlineKeyboardButton("📥 Import Excel/CSV", callback_data='import_excel')],
        [InlineKeyboardButton("📤 Export Reports", callback_data='export_menu')],
        [InlineKeyboardButton("🗑️ Delete Last", callback_data='delete_last')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "💰 *Welcome to Advanced Expense Tracker!*\n\n"
        "✨ *Features:*\n"
        "📥 Import Money Manager files\n"
        "📊 Professional Excel reports\n"
        "📈 Category & subcategory analysis\n"
        "💳 Account balance tracking\n"
        "📅 Historical tracking\n"
        "🎯 Top expenses tracking\n\n"
        "Choose an option below:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("➕ Add Expense", callback_data='add_expense')],
        [InlineKeyboardButton("📊 Current Month Report", callback_data='current_month_report')],
        [InlineKeyboardButton("📅 Previous Months", callback_data='previous_months')],
        [InlineKeyboardButton("💳 Manage Account Balances", callback_data='manage_accounts')],
        [InlineKeyboardButton("📥 Import Excel/CSV", callback_data='import_excel')],
        [InlineKeyboardButton("📤 Export Reports", callback_data='export_menu')],
        [InlineKeyboardButton("🗑️ Delete Last", callback_data='delete_last')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "💰 *Expense Tracker Menu*\n\nChoose an option:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


# Account balance management
# Improved Account balance management
async def manage_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    balances = get_all_account_balances(user_id)

    if not balances:
        message = "💳 *Account Balance Manager*\n\n" \
                  "No accounts set up yet.\n\n" \
                  "🎯 *How it works:*\n" \
                  "1. Click 'Add New Account' below\n" \
                  "2. Select account type (Cash, Online, UPI, etc.)\n" \
                  "3. Enter your current balance\n" \
                  "4. Expenses will auto-deduct from balance!\n\n" \
                  "Example: Set Cash = ₹5000\n" \
                  "After ₹100 expense → Balance = ₹4900"
    else:
        message = "💳 *Account Balances*\n\n"
        total_balance = 0

        for account, initial, current, updated in balances:
            spent = initial - current
            total_balance += current
            message += f"*{account}*\n"
            message += f"  💰 Current: ₹{current:.2f}\n"
            message += f"  📊 Spent: ₹{spent:.2f}\n"
            message += f"  🏦 Initial: ₹{initial:.2f}\n\n"

        message += f"━━━━━━━━━━━━━━━━━\n"
        message += f"*💵 Total Balance: ₹{total_balance:.2f}*"

    keyboard = [
        [InlineKeyboardButton("➕ Add New Account", callback_data='add_account_balance')],
        [InlineKeyboardButton("✏️ Update Balance", callback_data='update_balance')],
        [InlineKeyboardButton("💰 Add Money", callback_data='add_money')],
        [InlineKeyboardButton("💸 Subtract Money", callback_data='subtract_money')],
        [InlineKeyboardButton("📊 View Details", callback_data='view_account_details')],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data='menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


# NEW: View detailed account breakdown
async def view_account_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    balances = get_all_account_balances(user_id)

    if not balances:
        message = "💳 No accounts found.\n\nAdd an account first!"
    else:
        message = "💳 *Detailed Account Information*\n\n"

        for account, initial, current, updated in balances:
            conn = sqlite3.connect('expenses.db')
            cursor = conn.cursor()

            # Get expenses for this account
            cursor.execute('''
                SELECT COUNT(*), SUM(amount)
                FROM expenses
                WHERE user_id = ? AND account = ?
            ''', (user_id, account))

            txn_count, total_spent = cursor.fetchone()
            total_spent = total_spent if total_spent else 0

            # Get last transaction
            cursor.execute('''
                SELECT date, amount, category
                FROM expenses
                WHERE user_id = ? AND account = ?
                ORDER BY date DESC
                LIMIT 1
            ''', (user_id, account))

            last_txn = cursor.fetchone()
            conn.close()

            spent_calc = initial - current

            message += f"*{account}*\n"
            message += f"━━━━━━━━━━━━━━\n"
            message += f"💰 Current Balance: ₹{current:.2f}\n"
            message += f"🏦 Initial Balance: ₹{initial:.2f}\n"
            message += f"📊 Total Spent: ₹{spent_calc:.2f}\n"
            message += f"🔢 Transactions: {txn_count if txn_count else 0}\n"

            if last_txn:
                last_date = datetime.strptime(last_txn[0], '%Y-%m-%d %H:%M:%S').strftime('%d %b, %I:%M %p')
                message += f"🕒 Last Used: {last_date}\n"
                message += f"   └ ₹{last_txn[1]:.2f} ({last_txn[2]})\n"

            message += f"📅 Updated: {datetime.strptime(updated, '%Y-%m-%d %H:%M:%S').strftime('%d %b %Y')}\n\n"

    keyboard = [
        [InlineKeyboardButton("🔙 Back to Accounts", callback_data='manage_accounts')],
        [InlineKeyboardButton("🏠 Main Menu", callback_data='menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


# Update start_balance_update function to differentiate between add and update
async def start_balance_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    operation = query.data
    context.user_data['balance_operation'] = operation

    user_id = update.effective_user.id
    accounts = get_user_accounts(user_id)

    keyboard = []
    for i in range(0, len(accounts), 2):
        row = [InlineKeyboardButton(accounts[i], callback_data=f'bacc_{accounts[i]}')]
        if i + 1 < len(accounts):
            row.append(InlineKeyboardButton(accounts[i + 1], callback_data=f'bacc_{accounts[i + 1]}'))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='manage_accounts')])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if operation == 'add_account_balance':
        title = "Add New Account"
        subtitle = "Select account type to set initial balance:"
    elif operation == 'update_balance':
        title = "Update Account Balance"
        subtitle = "Select account to update:"
    elif operation == 'add_money':
        title = "Add Money to Account"
        subtitle = "Select account:"
    else:
        title = "Subtract Money from Account"
        subtitle = "Select account:"

    await query.edit_message_text(
        f"💳 *{title}*\n\n{subtitle}",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

    return ACCOUNT_SELECT


async def account_for_balance_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    account = query.data.replace('bacc_', '')
    context.user_data['selected_account'] = account

    user_id = update.effective_user.id
    balance_info = get_account_balance(user_id, account)
    operation = context.user_data['balance_operation']

    if balance_info and operation != 'add_account_balance':
        current = balance_info['current']
        message = f"💳 *{account}*\n\n" \
                  f"Current Balance: ₹{current:.2f}\n\n"
    else:
        message = f"💳 *{account}*\n\n"

    if operation == 'add_account_balance':
        message += "Enter the balance amount:"
    elif operation == 'add_money':
        message += "Enter amount to add:"
    else:
        message += "Enter amount to subtract:"

    await query.edit_message_text(message, parse_mode='Markdown')

    return BALANCE_AMOUNT


async def balance_amount_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        if amount <= 0:
            raise ValueError

        user_id = update.effective_user.id
        account = context.user_data['selected_account']
        operation = context.user_data['balance_operation']

        if operation == 'add_account_balance':
            update_account_balance(user_id, account, amount, 'set')
            message = f"✅ *Balance Set Successfully!*\n\n" \
                      f"Account: {account}\n" \
                      f"Balance: ₹{amount:.2f}"
        elif operation == 'add_money':
            update_account_balance(user_id, account, amount, 'add')
            new_balance = get_account_balance(user_id, account)['current']
            message = f"✅ *Money Added!*\n\n" \
                      f"Account: {account}\n" \
                      f"Added: ₹{amount:.2f}\n" \
                      f"New Balance: ₹{new_balance:.2f}"
        else:
            update_account_balance(user_id, account, amount, 'subtract')
            new_balance = get_account_balance(user_id, account)['current']
            message = f"✅ *Money Deducted!*\n\n" \
                      f"Account: {account}\n" \
                      f"Deducted: ₹{amount:.2f}\n" \
                      f"New Balance: ₹{new_balance:.2f}"

        keyboard = [
            [InlineKeyboardButton("💳 Manage Accounts", callback_data='manage_accounts')],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data='menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text(
            "❌ Invalid amount. Please enter a valid number:"
        )
        return BALANCE_AMOUNT


# Show previous months
async def show_previous_months(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    months = get_available_months(user_id)

    if not months:
        await query.edit_message_text(
            "📅 No expenses found.\n\nStart by adding expenses or importing an Excel file!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='menu')]])
        )
        return

    keyboard = []
    for month in months:
        month_name = datetime.strptime(month, '%Y-%m').strftime('%B %Y')
        keyboard.append([InlineKeyboardButton(f"📊 {month_name}", callback_data=f'view_month_{month}')])

    keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data='menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "📅 *Select a month to view:*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def view_month_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    month = query.data.replace('view_month_', '')

    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT SUM(amount) FROM expenses
        WHERE user_id = ? AND date LIKE ?
    ''', (user_id, f'{month}%'))

    total = cursor.fetchone()[0] or 0

    cursor.execute('''
        SELECT category, SUM(amount), COUNT(*)
        FROM expenses
        WHERE user_id = ? AND date LIKE ?
        GROUP BY category
        ORDER BY SUM(amount) DESC
    ''', (user_id, f'{month}%'))

    categories_data = cursor.fetchall()

    cursor.execute('''
        SELECT COUNT(DISTINCT DATE(date))
        FROM expenses
        WHERE user_id = ? AND date LIKE ?
    ''', (user_id, f'{month}%'))

    days_count = cursor.fetchone()[0] or 1
    conn.close()

    month_name = datetime.strptime(month, '%Y-%m').strftime('%B %Y')

    if not categories_data:
        message = f"📊 *Report - {month_name}*\n\nNo expenses recorded."
    else:
        daily_avg = total / days_count
        message = f"📊 *Report - {month_name}*\n\n" \
                  f"💰 Total Spent: *₹{total:.2f}*\n" \
                  f"📅 Daily Average: *₹{daily_avg:.2f}*\n" \
                  f"🔢 Transactions: {sum(count for _, _, count in categories_data)}\n\n" \
                  "*Breakdown by Category:*\n"

        for category, amount, count in categories_data:
            percentage = (amount / total) * 100
            message += f"\n{category}\n"
            message += f"  ₹{amount:.2f} ({count} txns) - {percentage:.1f}%\n"

    keyboard = [
        [InlineKeyboardButton("📥 Export Detailed Excel Report", callback_data=f'export_excel_{month}')],
        [InlineKeyboardButton("🔙 Back to Months", callback_data='previous_months')],
        [InlineKeyboardButton("🏠 Main Menu", callback_data='menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def export_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    months = get_available_months(user_id)

    if not months:
        await query.edit_message_text(
            "📤 No data available to export.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='menu')]])
        )
        return

    keyboard = []
    for month in months[:6]:
        month_name = datetime.strptime(month, '%Y-%m').strftime('%B %Y')
        keyboard.append([
            InlineKeyboardButton(f"📊 {month_name}", callback_data=f'export_excel_{month}')
        ])

    keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data='menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "📤 *Export Professional Reports*\n\nSelect month:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def export_excel_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("📊 Generating professional report...")

    user_id = update.effective_user.id
    month = query.data.replace('export_excel_', '')
    month_name = datetime.strptime(month, '%Y-%m').strftime('%B_%Y')

    excel_file = await generate_professional_excel_report(user_id, month, context)

    if excel_file is None:
        await query.edit_message_text(
            "❌ No data found for this month.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='export_menu')]])
        )
        return

    await context.bot.send_document(
        chat_id=query.message.chat_id,
        document=excel_file,
        filename=f'Expense_Report_{month_name}.xlsx',
        caption=f"📊 *Professional Expense Report - {month_name.replace('_', ' ')}*\n\n"
                f"*Report Contains:*\n"
                f"📈 Overview with key metrics\n"
                f"📁 Category-wise breakdown\n"
                f"📅 Daily spending analysis\n"
                f"💳 Account-wise summary\n"
                f"📂 Subcategory details\n"
                f"💰 Top 20 expenses\n"
                f"📝 All transactions\n"
                f"📊 Individual category sheets\n\n"
                f"Perfect for budget analysis & financial planning!",
        parse_mode='Markdown'
    )

    await query.edit_message_text(
        "✅ Professional Excel report sent!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='export_menu')]])
    )


async def current_month_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    current_month = datetime.now().strftime('%Y-%m')

    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT SUM(amount) FROM expenses
        WHERE user_id = ? AND date LIKE ?
    ''', (user_id, f'{current_month}%'))

    total = cursor.fetchone()[0] or 0

    cursor.execute('''
        SELECT category, SUM(amount), COUNT(*)
        FROM expenses
        WHERE user_id = ? AND date LIKE ?
        GROUP BY category
        ORDER BY SUM(amount) DESC
    ''', (user_id, f'{current_month}%'))

    categories_data = cursor.fetchall()

    cursor.execute('''
        SELECT COUNT(DISTINCT DATE(date))
        FROM expenses
        WHERE user_id = ? AND date LIKE ?
    ''', (user_id, f'{current_month}%'))

    days_count = cursor.fetchone()[0] or 1
    conn.close()

    if not categories_data:
        message = f"📊 *Current Month - {datetime.now().strftime('%B %Y')}*\n\n" \
                  "No expenses recorded this month."
    else:
        daily_avg = total / days_count
        message = f"📊 *Current Month - {datetime.now().strftime('%B %Y')}*\n\n" \
                  f"💰 Total Spent: *₹{total:.2f}*\n" \
                  f"📅 Daily Average: *₹{daily_avg:.2f}*\n" \
                  f"🔢 Transactions: {sum(count for _, _, count in categories_data)}\n\n" \
                  "*Breakdown by Category:*\n"

        for category, amount, count in categories_data:
            percentage = (amount / total) * 100
            message += f"\n{category}\n"
            message += f"  ₹{amount:.2f} ({count} txns) - {percentage:.1f}%\n"

    keyboard = [
        [InlineKeyboardButton("📥 Export Excel Report", callback_data=f'export_excel_{current_month}')],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data='menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def import_excel_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    message = "📥 *Import Your Expenses*\n\n" \
              "*Supported Formats:*\n" \
              "✅ Money Manager exports (.xls, .xlsx)\n" \
              "✅ Generic Excel/CSV files\n\n" \
              "*Required Columns:*\n" \
              "• Category\n" \
              "• Amount\n\n" \
              "*Optional Columns:*\n" \
              "• Date\n" \
              "• Subcategory\n" \
              "• Description/Note\n" \
              "• Account\n\n" \
              "Just upload your file and I'll handle the rest!"

    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')


# Add expense flow
async def add_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    categories = get_user_categories(user_id)

    keyboard = []
    for i in range(0, len(categories), 2):
        row = [InlineKeyboardButton(categories[i], callback_data=f'cat_{categories[i]}')]
        if i + 1 < len(categories):
            row.append(InlineKeyboardButton(categories[i + 1], callback_data=f'cat_{categories[i + 1]}'))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "📁 *Step 1/5: Select Category*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

    return CATEGORY


async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category = query.data.replace('cat_', '')
    context.user_data['category'] = category

    user_id = update.effective_user.id
    subcategories = get_subcategories_for_category(user_id, category)

    keyboard = []
    for i in range(0, len(subcategories), 2):
        row = [InlineKeyboardButton(subcategories[i], callback_data=f'subcat_{subcategories[i]}')]
        if i + 1 < len(subcategories):
            row.append(InlineKeyboardButton(subcategories[i + 1], callback_data=f'subcat_{subcategories[i + 1]}'))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("⏭️ Skip Subcategory", callback_data='subcat_skip')])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='add_expense')])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"Category: *{category}*\n\n"
        f"📂 *Step 2/5: Select Subcategory*\n"
        f"(or skip if not needed)",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

    return SUBCATEGORY


async def subcategory_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    subcategory = query.data.replace('subcat_', '')

    if subcategory == 'skip':
        context.user_data['subcategory'] = None
        subcategory_text = "None"
    else:
        context.user_data['subcategory'] = subcategory
        subcategory_text = subcategory

    category = context.user_data['category']

    await query.edit_message_text(
        f"Category: *{category}*\n"
        f"Subcategory: *{subcategory_text}*\n\n"
        f"💵 *Step 3/5: Enter the amount*",
        parse_mode='Markdown'
    )

    return AMOUNT


async def amount_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        if amount <= 0:
            raise ValueError

        context.user_data['amount'] = amount

        category = context.user_data['category']
        subcategory = context.user_data.get('subcategory', 'None')
        if subcategory is None:
            subcategory = 'None'

        await update.message.reply_text(
            f"Category: *{category}*\n"
            f"Subcategory: *{subcategory}*\n"
            f"Amount: *₹{amount:.2f}*\n\n"
            f"📝 *Step 4/5: Enter description*\n"
            f"(or send /skip to skip)",
            parse_mode='Markdown'
        )

        return DESCRIPTION
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid amount. Please enter a valid number:"
        )
        return AMOUNT


async def description_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    description = update.message.text if update.message.text != '/skip' else 'No description'
    context.user_data['description'] = description

    user_id = update.effective_user.id
    accounts = get_user_accounts(user_id)

    keyboard = []
    for i in range(0, len(accounts), 2):
        row = [InlineKeyboardButton(accounts[i], callback_data=f'acc_{accounts[i]}')]
        if i + 1 < len(accounts):
            row.append(InlineKeyboardButton(accounts[i + 1], callback_data=f'acc_{accounts[i + 1]}'))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("⏭️ Skip Account", callback_data='acc_skip')])
    reply_markup = InlineKeyboardMarkup(keyboard)

    category = context.user_data['category']
    subcategory = context.user_data.get('subcategory', 'None')
    if subcategory is None:
        subcategory = 'None'
    amount = context.user_data['amount']

    await update.message.reply_text(
        f"Category: *{category}*\n"
        f"Subcategory: *{subcategory}*\n"
        f"Amount: *₹{amount:.2f}*\n"
        f"Description: *{description}*\n\n"
        f"💳 *Step 5/5: Select Payment Account*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

    return ACCOUNT


async def account_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    account = query.data.replace('acc_', '')

    if account == 'skip':
        context.user_data['account'] = None
        account_text = "Not specified"
    else:
        context.user_data['account'] = account
        account_text = account

    user_id = update.effective_user.id
    category = context.user_data['category']
    subcategory = context.user_data.get('subcategory')
    amount = context.user_data['amount']
    description = context.user_data['description']
    account = context.user_data.get('account')
    date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO expenses (user_id, category, subcategory, amount, description, account, date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, category, subcategory, amount, description, account, date))
    conn.commit()
    conn.close()

    # Auto-deduct from account balance if account is tracked
    balance_updated = False
    new_balance = None
    if account:
        balance_info = get_account_balance(user_id, account)
        if balance_info:
            update_account_balance(user_id, account, amount, 'subtract')
            new_balance = get_account_balance(user_id, account)['current']
            balance_updated = True

    keyboard = [
        [InlineKeyboardButton("➕ Add Another", callback_data='add_expense')],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data='menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = f"✅ *Expense Added Successfully!*\n\n" \
              f"📁 Category: {category}\n" \
              f"📂 Subcategory: {subcategory if subcategory else 'None'}\n" \
              f"💵 Amount: ₹{amount:.2f}\n" \
              f"📝 Description: {description}\n" \
              f"💳 Account: {account_text}\n" \
              f"📅 Date: {datetime.now().strftime('%d %b %Y, %I:%M %p')}"

    if balance_updated:
        message += f"\n\n💰 *{account} Balance*\n" \
                   f"Remaining: ₹{new_balance:.2f}"

    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

    return ConversationHandler.END


async def delete_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, category, amount, description, account
        FROM expenses
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
    ''', (user_id,))

    last_expense = cursor.fetchone()

    if last_expense:
        expense_id, category, amount, description, account = last_expense

        # Add money back to account if it was tracked
        if account:
            balance_info = get_account_balance(user_id, account)
            if balance_info:
                update_account_balance(user_id, account, amount, 'add')

        cursor.execute('DELETE FROM expenses WHERE id = ?', (expense_id,))
        conn.commit()

        message = f"🗑️ *Deleted:*\n\n" \
                  f"Category: {category}\n" \
                  f"Amount: ₹{amount:.2f}\n" \
                  f"Description: {description}"

        if account and balance_info:
            new_balance = get_account_balance(user_id, account)['current']
            message += f"\n\n💰 Refunded to {account}\n" \
                       f"New Balance: ₹{new_balance:.2f}"
    else:
        message = "No expenses to delete."

    conn.close()

    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Operation cancelled. Use /start to begin again."
    )
    return ConversationHandler.END


def main():
    init_db()

    TOKEN = os.getenv('BOT_TOKEN', '6793523642:AAEX6Kbb_La-OxHJlqMkKx5n54XqVNquiUo')
    application = Application.builder().token(TOKEN).build()

    # Conversation handler for adding expenses
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_expense_start, pattern='^add_expense$')],
        states={
            CATEGORY: [CallbackQueryHandler(category_selected, pattern='^cat_')],
            SUBCATEGORY: [CallbackQueryHandler(subcategory_selected, pattern='^subcat_')],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, amount_entered)],
            DESCRIPTION: [MessageHandler(filters.TEXT, description_entered)],
            ACCOUNT: [CallbackQueryHandler(account_selected, pattern='^acc_')]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )

    # Conversation handler for account balance management
    balance_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_balance_update, pattern='^add_account_balance$'),
            CallbackQueryHandler(start_balance_update, pattern='^update_balance$'),  # NEW
            CallbackQueryHandler(start_balance_update, pattern='^add_money$'),
            CallbackQueryHandler(start_balance_update, pattern='^subtract_money$')
        ],
        states={
            ACCOUNT_SELECT: [CallbackQueryHandler(account_for_balance_selected, pattern='^bacc_')],
            BALANCE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, balance_amount_entered)]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )

    application.add_handler(CommandHandler('start', start))
    application.add_handler(conv_handler)
    application.add_handler(balance_conv_handler)
    application.add_handler(CallbackQueryHandler(menu, pattern='^menu$'))
    application.add_handler(CallbackQueryHandler(manage_accounts, pattern='^manage_accounts$'))
    application.add_handler(CallbackQueryHandler(view_account_details, pattern='^view_account_details$'))  # NEW
    application.add_handler(CallbackQueryHandler(current_month_report, pattern='^current_month_report$'))
    application.add_handler(CallbackQueryHandler(show_previous_months, pattern='^previous_months$'))
    application.add_handler(CallbackQueryHandler(view_month_report, pattern='^view_month_'))
    application.add_handler(CallbackQueryHandler(export_menu, pattern='^export_menu$'))
    application.add_handler(CallbackQueryHandler(export_excel_report, pattern='^export_excel_'))
    application.add_handler(CallbackQueryHandler(delete_last, pattern='^delete_last$'))
    application.add_handler(CallbackQueryHandler(import_excel_instructions, pattern='^import_excel$'))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_excel_import))

    print("Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == '__main__':
    main()

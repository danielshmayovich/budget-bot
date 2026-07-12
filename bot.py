import os
import re
import asyncio
import logging
import shutil
from datetime import time as dtime, datetime
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from dotenv import load_dotenv
import excel_handler

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
logging.info("ALL ENV KEYS: %s", sorted(os.environ.keys()))
logging.info("TOKEN found: %s", bool(TOKEN))
PAGE_SIZE = 8
CHAT_ID_FILE = os.path.join(os.path.dirname(__file__), "chat_id.txt")
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

PAY_LABELS = {"cash": "💵 מזומן", "credit": "💳 אשראי"}


def save_chat_id(chat_id: int):
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))


def load_chat_id():
    if os.path.exists(CHAT_ID_FILE):
        with open(CHAT_ID_FILE) as f:
            return int(f.read().strip())
    return None


def fmt(n):
    return f"{n:,.0f}"


def format_status(expenses, income, month_name):
    total_income   = sum(c["actual"] for c in income)
    total_expenses = sum(c["actual"] for c in expenses)
    diff = total_income - total_expenses
    diff_icon = "📈" if diff >= 0 else "📉"
    diff_sign = "+" if diff >= 0 else ""

    lines = [
        f"\U0001f4ca *דוח {month_name}*\n",
        f"💰 הכנסות (בעל + אישה): *{fmt(total_income)} ₪*",
        f"💸 הוצאות: *{fmt(total_expenses)} ₪*",
        f"{diff_icon} הפרש: *{diff_sign}{fmt(diff)} ₪*",
    ]

    if expenses:
        lines.append("")
        lines.append("*הוצאות לפי קטגוריה:*")
        for c in sorted(expenses, key=lambda x: -x["actual"]):
            lines.append(f"  • {c['name']}: {fmt(c['actual'])} ₪")

    return "\n".join(lines)


def format_expense_result(name, amount, result, pay_type=None, month_name=None):
    pay_label = PAY_LABELS.get(pay_type, "") if pay_type else ""
    month_str = f" ({month_name.strip()})" if month_name else ""
    line1 = f"✅ נוספו *{fmt(amount)} ₪* לקטגוריית *{name}*{month_str}"
    if pay_label:
        line1 += f" — {pay_label}"
    lines = [line1, ""]
    if result["budget"] > 0:
        lines.append(f"\U0001f4b0 תקציב: {fmt(result['budget'])} ₪")
        lines.append(f"\U0001f4ca בוצע: {fmt(result['actual'])} ₪")
        if result["remaining"] < 0:
            lines.append(f"⚠️ חריגה של *{fmt(abs(result['remaining']))} ₪* מהתקציב")
        else:
            lines.append(f"\U0001f7e2 נותרו *{fmt(result['remaining'])} ₪*")
    else:
        lines.append(f"\U0001f4ca סה\"כ בקטגוריה: {fmt(result['actual'])} ₪")
    return "\n".join(lines)


def make_pay_keyboard(row, amount):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💳 אשראי", callback_data=f"pay:credit:{row}:{amount}"),
            InlineKeyboardButton("💵 מזומן",  callback_data=f"pay:cash:{row}:{amount}"),
        ],
        [InlineKeyboardButton("❌ ביטול", callback_data="cancel")],
    ])


def make_month_keyboard(pay_type, row, amount):
    current_month = datetime.now().month
    months = excel_handler.MONTH_SHEETS
    rows = []
    row_btns = []
    for num in range(1, 13):
        label = months[num].strip()
        if num == current_month:
            label = f"• {label} •"
        row_btns.append(InlineKeyboardButton(
            label, callback_data=f"month:{num}:{pay_type}:{row}:{amount}"
        ))
        if len(row_btns) == 3:
            rows.append(row_btns)
            row_btns = []
    if row_btns:
        rows.append(row_btns)
    rows.append([InlineKeyboardButton("❌ ביטול", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)


async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    chat_id = load_chat_id()
    if not chat_id:
        return
    try:
        expenses, income, month = excel_handler.get_status()
    except Exception as e:
        logging.error("daily report failed: %s", e)
        return
    if not expenses and not income:
        return
    await context.bot.send_message(
        chat_id=chat_id,
        text=format_status(expenses, income, month),
        parse_mode="Markdown",
    )


def make_cat_keyboard(cats, amount, page=0):
    # Sort: categories with existing expenses first, then alphabetically
    sorted_cats = sorted(cats, key=lambda x: (-x["actual"], x["name"]))
    chunk = sorted_cats[page * PAGE_SIZE: (page + 1) * PAGE_SIZE]

    rows = []
    pair = []
    for c in chunk:
        label = c["name"][:22]
        pair.append(InlineKeyboardButton(label, callback_data=f"cat:{c['row']}:{amount}"))
        if len(pair) == 2:
            rows.append(pair); pair = []
    if pair:
        rows.append(pair)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ הקודם", callback_data=f"page:{page-1}:{amount}"))
    if (page + 1) * PAGE_SIZE < len(sorted_cats):
        nav.append(InlineKeyboardButton("הבא ▶️",   callback_data=f"page:{page+1}:{amount}"))
    if nav:
        rows.append(nav)

    return InlineKeyboardMarkup(rows)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    await update.message.reply_text(
        "שלום! אני בוט ניהול התקציב המשפחתי \U0001f4b0\n\n"
        "פקודות:\n"
        "• /status - דוח מצב חודשי\n"
        "• /dashboard - ויזואליזציה + ניתוח חריגות\n"
        "• /export - הורד קובץ האקסל\n\n"
        "הוספת הוצאה:\n"
        "• שלח `קטגוריה סכום` (לדוגמה: `דלק 150`)\n"
        "• או רק סכום ואני אציג רשימת קטגוריות\n\n"
        "✅ נרשמת לדוח יומי אוטומטי בשעה 08:00"
    )


async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        expenses, income, month = excel_handler.get_status()
    except Exception as e:
        await update.message.reply_text(f"⚠️ שגיאה: {e}")
        return

    active = [c for c in expenses if c["actual"] > 0]
    if not active:
        await update.message.reply_text("אין נתוני הוצאות לחודש הנוכחי")
        return

    active.sort(key=lambda x: -x["actual"])
    total_exp = sum(c["actual"] for c in active)
    total_inc = sum(c["actual"] for c in income)
    diff = total_inc - total_exp
    pct = (total_exp / total_inc * 100) if total_inc > 0 else 0
    diff_icon = "📈" if diff >= 0 else "📉"
    diff_sign = "+" if diff >= 0 else ""
    max_val = active[0]["actual"] if active else 1
    BAR_W = 9

    lines = [
        f"📊 *דוח {month}*\n",
        f"💰 הכנסות:  *{fmt(total_inc)} ₪*",
        f"💸 הוצאות:  *{fmt(total_exp)} ₪*  ({pct:.0f}%)",
        f"{diff_icon} נותר:     *{diff_sign}{fmt(diff)} ₪*",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]

    RLM = "‏"  # Right-to-Left Mark — forces RTL paragraph direction

    overruns = []
    for c in active[:15]:
        actual  = c["actual"]
        budget  = c.get("budget", 0)
        filled  = max(1, int((actual / max_val) * BAR_W))
        bar     = "█" * filled + "░" * (BAR_W - filled)
        name    = c["name"]

        if budget > 0 and actual > budget:
            overrun = actual - budget
            overruns.append((name, overrun, budget))
            icon = "🔴"
        elif budget > 0:
            icon = "🟢"
        else:
            icon = "▪️"

        # Hebrew name on its own RTL line
        lines.append(f"{RLM}{icon} *{name}*")
        # Numbers-only line — pure LTR, no Hebrew
        lines.append(f"   {bar} {fmt(actual)} ₪")
        # Overrun on separate RTL line
        if budget > 0 and actual > budget:
            lines.append(f"{RLM}   ⚠️ חריגה: +{fmt(actual - budget)} ₪")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    if overruns:
        overruns.sort(key=lambda x: -x[1])
        lines.append("\n⚠️ *חריגות מהתקציב:*")
        for name, over, budget in overruns:
            pct_over = (over / budget * 100)
            lines.append(f"  • {name}: +{fmt(over)} ₪  ({pct_over:.0f}% מעל)")

    top3 = [c["name"] for c in active[:3]]
    lines.append(f"\n🎯 *לאן לשים דגש:* {', '.join(top3)}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Accept an Excel file sent to the bot and save it as the budget file."""
    saved_id = load_chat_id()
    if saved_id and update.effective_chat.id != saved_id:
        return  # ignore unknown senders

    doc = update.message.document if update.message else None
    if not doc or not doc.file_name.endswith(".xlsx"):
        await update.message.reply_text("📎 שלח קובץ Excel (.xlsx) כקובץ מצורף")
        return

    excel_path = os.getenv("EXCEL_PATH", "")
    if not excel_path:
        await update.message.reply_text("⚠️ EXCEL_PATH לא מוגדר")
        return

    try:
        tg_file = await context.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(excel_path)
        excel_handler._cat_cache.clear()
        size_kb = doc.file_size / 1024
        await update.message.reply_text(
            f"✅ קובץ האקסל עודכן בהצלחה ({size_kb:.0f} KB)\n"
            f"השתמש ב-/status לבדוק שהנתונים נכונים"
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ שגיאה בהעלאת הקובץ: {e}")


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    excel_path = os.getenv("EXCEL_PATH", "")
    if not excel_path or not os.path.exists(excel_path):
        await update.message.reply_text("⚠️ קובץ האקסל לא נמצא")
        return
    await update.message.reply_document(
        document=open(excel_path, "rb"),
        filename="תקציב_משפחתי_2026.xlsx",
        caption="📊 קובץ תקציב משפחתי עדכני",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        expenses, income, month = excel_handler.get_status()
    except Exception as e:
        await update.message.reply_text(f"⚠️ שגיאה בקריאת הנתונים: {e}")
        return
    if not expenses and not income:
        await update.message.reply_text("לא נמצאו נתונים לחודש הנוכחי")
        return
    await update.message.reply_text(format_status(expenses, income, month), parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    numbers = re.findall(r"\d+(?:\.\d+)?", text)

    if not numbers:
        await cmd_status(update, context)
        return

    amount = float(numbers[0])
    cat_query = re.sub(r"\d+(?:\.\d+)?", "", text)
    cat_query = re.sub(r"\b(שקל|שקלים|ש\"ח|שח|₪|על|ב|ל)\b", "", cat_query).strip()

    try:
        cats = excel_handler.get_categories()
    except Exception as e:
        await update.message.reply_text(f"⚠️ שגיאה בקריאת קטגוריות: {e}")
        return

    if cat_query:
        # Try full query first, then word-by-word
        matches = excel_handler.find_categories_multi(cat_query, cats)
        if not matches:
            for word in cat_query.split():
                if len(word) > 1:
                    word_matches = excel_handler.find_categories_multi(word, cats)
                    for item in word_matches:
                        if item not in matches:
                            matches.append(item)
            matches.sort(key=lambda x: -x[0])
            matches = matches[:5]

        if len(matches) == 1:
            # Single match — go straight to payment keyboard
            _, cat = matches[0]
            context.user_data["pending_name"] = cat["name"]
            kb = make_pay_keyboard(cat["row"], amount)
            await update.message.reply_text(
                f"*{cat['name']}* — *{fmt(amount)} ₪*\nבחר סוג תשלום:",
                reply_markup=kb, parse_mode="Markdown"
            )
            return
        elif len(matches) > 1:
            # Multiple matches — let user pick
            btns = [
                [InlineKeyboardButton(cat["name"][:30], callback_data=f"cat:{cat['row']}:{amount}")]
                for _, cat in matches
            ]
            btns.append([InlineKeyboardButton("📋 כל הקטגוריות", callback_data=f"page:0:{amount}")])
            await update.message.reply_text(
                f"מצאתי כמה קטגוריות עבור *{fmt(amount)} ₪* — בחר:",
                reply_markup=InlineKeyboardMarkup(btns), parse_mode="Markdown"
            )
            return

    kb = make_cat_keyboard(cats, amount, page=0)
    await update.message.reply_text(
        f"בחר קטגוריה עבור *{fmt(amount)} ₪*:",
        reply_markup=kb, parse_mode="Markdown"
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        return  # callback expired (>10 min old)
    data = query.data

    if data == "cancel":
        context.user_data.pop("pending_name", None)
        await query.edit_message_text("❌ בוטל")
        return

    if data.startswith("cat:"):
        # cat:row:amount → show pay type keyboard
        parts  = data.split(":")
        row    = int(parts[1])
        amount = float(parts[2])
        try:
            cats = excel_handler.get_categories()
        except Exception as e:
            await query.edit_message_text(f"⚠️ {e}")
            return
        cat  = next((c for c in cats if c["row"] == row), None)
        name = cat["name"] if cat else f"שורה {row}"
        context.user_data["pending_name"] = name
        kb = make_pay_keyboard(row, amount)
        await query.edit_message_text(
            f"*{name}* — *{fmt(amount)} ₪*\nבחר סוג תשלום:",
            reply_markup=kb, parse_mode="Markdown"
        )

    elif data.startswith("pay:"):
        # pay:type:row:amount → show month keyboard
        parts     = data.split(":")
        pay_type  = parts[1]
        row       = int(parts[2])
        amount    = float(parts[3])
        name      = context.user_data.get("pending_name", f"שורה {row}")
        pay_label = PAY_LABELS.get(pay_type, pay_type)
        kb = make_month_keyboard(pay_type, row, amount)
        await query.edit_message_text(
            f"*{name}* — *{fmt(amount)} ₪* ({pay_label})\nבחר חודש:",
            reply_markup=kb, parse_mode="Markdown"
        )

    elif data.startswith("month:"):
        # month:month_num:pay_type:row:amount → add expense
        parts      = data.split(":")
        month_num  = int(parts[1])
        pay_type   = parts[2]
        row        = int(parts[3])
        amount     = float(parts[4])
        sheet_name = excel_handler.MONTH_SHEETS[month_num]
        name       = context.user_data.pop("pending_name", f"שורה {row}")
        pay_label  = PAY_LABELS.get(pay_type, pay_type)

        # Respond immediately — don't make user wait for Excel write
        await query.edit_message_text(
            f"✅ נוספו *{fmt(amount)} ₪* לקטגוריית *{name}* ({sheet_name.strip()}) — {pay_label}",
            parse_mode="Markdown",
        )

        # Write to Excel in background thread
        chat_id = query.message.chat_id

        async def _save():
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, excel_handler.add_expense, row, amount, sheet_name
                )
            except Exception as exc:
                logging.error("add_expense failed: %s", exc)
                await context.bot.send_message(chat_id=chat_id, text=f"⚠️ שגיאה בשמירה לאקסל: {exc}")

        asyncio.create_task(_save())

    elif data.startswith("page:"):
        parts = data.split(":")
        try:
            cats = excel_handler.get_categories()
        except Exception as e:
            await query.edit_message_text(f"⚠️ {e}")
            return
        kb = make_cat_keyboard(cats, float(parts[2]), page=int(parts[1]))
        await query.edit_message_reply_markup(kb)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error("Exception in handler: %s", context.error, exc_info=context.error)


async def on_startup(app):
    """Sync Desktop→local and warm the category cache before polling starts."""
    desktop = os.getenv("DESKTOP_EXCEL_PATH", "")
    local   = os.getenv("EXCEL_PATH", "")
    if desktop and local and os.path.exists(desktop):
        try:
            shutil.copy2(desktop, local)
            logging.info("סונכרן קובץ Excel מהדסקטופ")
        except Exception as e:
            logging.warning("סנכרון מהדסקטופ נכשל: %s", e)
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, excel_handler.get_categories)
        logging.info("קטגוריות נטענו לזיכרון")
    except Exception as e:
        logging.warning("טעינת קטגוריות נכשלה: %s", e)


def main():
    if not TOKEN:
        raise RuntimeError("חסר TELEGRAM_BOT_TOKEN ב-.env")
    app = Application.builder().token(TOKEN).post_init(on_startup).build()
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
    app.add_handler(CommandHandler("export",    cmd_export))
    app.add_handler(MessageHandler(filters.Document.FileExtension("xlsx"), cmd_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(error_handler)

    if app.job_queue:
        app.job_queue.run_daily(send_daily_report, time=dtime(8, 0, tzinfo=ISRAEL_TZ))
        print("דוח יומי מוגדר לשעה 08:00 שעון ישראל")
    else:
        print("אזהרה: JobQueue לא זמין - התקן apscheduler")

    print("הבוט פועל...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

import sqlite3
import random
import time
import logging
import json
import asyncio
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# Logging setup
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot token and channel settings
TOKEN = "7878405507:AAGXC_46s8S9AeyN_tUtL39PgjrgtGNpccc"
OFFICIAL_CHANNELS = ["@RockPaperTON_chat", "@RockPaper_TON"]
GAME_GROUP_ID = "@RockPaperTON_chat"  # Public group username
ADMINS = [6789474405]  # Admin user ID

# Load opponents from JSON
with open("opponents.json", "r") as f:
    opponents_data = json.load(f)
    opponents = opponents_data["opponents"]

# Game states
(
    WITHDRAW_AMOUNT,
    WITHDRAW_ADDRESS,
    WITHDRAW_CONFIRM,
    CHANNEL_NAME,
    TICKET_REWARD,
    CHANNEL_TYPE,
    BROADCAST_TEXT,
    REMOVE_CHANNEL_NAME,
    EDIT_BALANCE_USER_ID,
    EDIT_BALANCE_AMOUNT,
) = range(10)

# Database connection
conn = None

def init_db():
    global conn
    conn = sqlite3.connect("bot.db", check_same_thread=False)
    c = conn.cursor()
    # Create users table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0.0,
            tickets INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            referrer_id INTEGER,
            referral_link TEXT,
            partner_channels TEXT DEFAULT '',
            total_games INTEGER DEFAULT 0,
            completed_missions TEXT DEFAULT '',
            is_verified INTEGER DEFAULT 0,
            last_daily_bonus REAL DEFAULT 0.0,
            daily_bonus_streak INTEGER DEFAULT 0
        )
    """
    )
    # Create withdrawals table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS withdrawals (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            wallet_address TEXT,
            status TEXT,
            timestamp REAL
        )
    """
    )
    # Create game_history table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS game_history (
            game_id TEXT PRIMARY KEY,
            user_id INTEGER,
            user_choice TEXT,
            opponent_choice TEXT,
            result TEXT,
            timestamp REAL
        )
    """
    )
    # Create partner_channels table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS partner_channels (
            channel_id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_name TEXT,
            ticket_reward INTEGER,
            require_membership INTEGER DEFAULT 0
        )
    """
    )
    # Initialize default partner channels if empty
    c.execute("SELECT COUNT(*) FROM partner_channels")
    if c.fetchone()[0] == 0:
        default_channels = [
            ("@gameechannel", 2, 0),  # No membership check
            ("@join_community", 2, 0),  # No membership check
        ]
        c.executemany(
            "INSERT INTO partner_channels (channel_name, ticket_reward, require_membership) VALUES (?, ?, ?)",
            default_channels
        )
    conn.commit()

# User data management
def get_user(user_id):
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    return user

def update_user(user_id, **kwargs):
    c = conn.cursor()
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [user_id]
    c.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
    conn.commit()

def create_user(user_id, username, referrer_id=None):
    referral_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO users (user_id, username, referral_link, referrer_id, is_verified) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, referral_link, referrer_id, 0),
    )
    conn.commit()

def save_game_result(user_id, user_choice, opponent_choice, result):
    game_id = str(uuid.uuid4())
    c = conn.cursor()
    c.execute(
        "INSERT INTO game_history (game_id, user_id, user_choice, opponent_choice, result, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (game_id, user_id, user_choice, opponent_choice, result, time.time())
    )
    conn.commit()

def get_partner_channels():
    c = conn.cursor()
    c.execute("SELECT channel_name, ticket_reward, require_membership FROM partner_channels")
    return c.fetchall()

def add_partner_channel(channel_name, ticket_reward, require_membership):
    c = conn.cursor()
    c.execute(
        "INSERT INTO partner_channels (channel_name, ticket_reward, require_membership) VALUES (?, ?, ?)",
        (channel_name, ticket_reward, require_membership)
    )
    conn.commit()

def remove_partner_channel(channel_name):
    c = conn.cursor()
    c.execute("DELETE FROM partner_channels WHERE channel_name = ?", (channel_name,))
    affected_rows = c.rowcount
    conn.commit()
    return affected_rows > 0

# Check channel membership
async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, channels):
    for channel in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            is_member = member.status in ["member", "administrator", "creator"]
            logger.info(f"Checking membership for user {user_id} in channel {channel}: {is_member}")
            if not is_member:
                return False
        except Exception as e:
            logger.error(f"Error checking membership for {channel}: {e}")
            return False
    return True

# Main menu
def main_menu():
    return ReplyKeyboardMarkup(
        [
            ["📜 Info", "🎮 Play to Earn"],
            ["💰 Balance", "👥 Referrals"],
            ["🎟 Free Tickets", "📜 Game History"],
        ],
        resize_keyboard=True,
    )

# Admin panel
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("🚫 Access denied! Only for admins. Try /admin or check your ID.")
        return

    keyboard = [
        ["➕ Add Partner Channel", "🗑 Remove Partner Channel"],
        ["📊 View Stats", "📢 Broadcast Message"],
        ["🏠 Main Menu"],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🔐 Admin Panel: Choose an option:", reply_markup=reply_markup)

# Add partner channel
async def add_partner_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("🚫 Access denied! Only for admins.")
        return ConversationHandler.END

    await update.message.reply_text("➕ Enter the partner channel name (e.g., @ChannelName):")
    return CHANNEL_NAME

async def add_partner_channel_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel_name = update.message.text
    if not channel_name.startswith("@"):
        await update.message.reply_text("🚫 Invalid channel name. It must start with @ (e.g., @ChannelName).")
        return CHANNEL_NAME
    context.user_data["new_channel_name"] = channel_name
    await update.message.reply_text("🎟 Enter the ticket reward for this channel (e.g., 2):")
    return TICKET_REWARD

async def add_partner_channel_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ticket_reward = int(update.message.text)
        if ticket_reward <= 0:
            await update.message.reply_text("🚫 Ticket reward must be a positive number.")
            return TICKET_REWARD
        context.user_data["ticket_reward"] = ticket_reward
        keyboard = [
            [InlineKeyboardButton("✅ Membership Check", callback_data="membership")],
            [InlineKeyboardButton("👆 Click Count", callback_data="clickcount")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "📋 Which method do you choose for this channel? Membership check or Click Count?",
            reply_markup=reply_markup
        )
        return CHANNEL_TYPE
    except ValueError:
        await update.message.reply_text("🚫 Invalid number. Please enter a valid ticket reward.")
        return TICKET_REWARD

async def add_partner_channel_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    channel_type = query.data
    channel_name = context.user_data["new_channel_name"]
    ticket_reward = context.user_data["ticket_reward"]
    require_membership = 1 if channel_type == "membership" else 0

    add_partner_channel(channel_name, ticket_reward, require_membership)

    # Notify all users about the new channel
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    success_count = 0
    for user in users:
        user_id = user[0]
        try:
            await context.bot.send_message(
                user_id,
                f"📢 New Partner Channel! Join {channel_name} and earn {ticket_reward} tickets! 🚀"
            )
            success_count += 1
            await asyncio.sleep(0.05)  # Avoid rate limiting
        except Exception as e:
            logger.error(f"Failed to send notification to {user_id}: {e}")

    await query.message.reply_text(
        f"✅ Partner channel {channel_name} added with {ticket_reward} ticket reward! Notified {success_count} users.",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END

# Remove partner channel
async def remove_partner_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("🚫 Access denied! Only for admins.")
        return ConversationHandler.END

    await update.message.reply_text("🗑 Enter the partner channel name to remove (e.g., @ChannelName):")
    return REMOVE_CHANNEL_NAME

async def remove_partner_channel_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel_name = update.message.text
    if not channel_name.startswith("@"):
        await update.message.reply_text("🚫 Invalid channel name. It must start with @ (e.g., @ChannelName).")
        return REMOVE_CHANNEL_NAME

    if remove_partner_channel(channel_name):
        await update.message.reply_text(
            f"✅ {channel_name} partner channel removed!",
            reply_markup=main_menu(),
        )
    else:
        await update.message.reply_text(
            f"⚠️ {channel_name} not found. Please enter a valid name.",
            reply_markup=main_menu(),
        )
    return ConversationHandler.END

# View stats
async def view_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("🚫 Access denied! Only for admins.")
        return

    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT SUM(total_games) FROM users")
    total_games = c.fetchone()[0] or 0
    c.execute("SELECT SUM(amount) FROM withdrawals WHERE status = 'completed'")
    total_withdrawn = c.fetchone()[0] or 0.0
    c.execute("SELECT SUM(tickets) FROM users")
    total_tickets = c.fetchone()[0] or 0

    await update.message.reply_text(
        f"📊 Bot Statistics:\n"
        f"👥 Total Users: {total_users}\n"
        f"🎮 Total Games Played: {total_games}\n"
        f"💸 Total Withdrawn: {total_withdrawn:.2f} $TON\n"
        f"🎟 Total Tickets Distributed: {total_tickets}",
        reply_markup=main_menu(),
    )

# Broadcast message
async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("🚫 Access denied! Only for admins.")
        return ConversationHandler.END

    await update.message.reply_text("📢 Enter the message to broadcast to all users:")
    return BROADCAST_TEXT

async def broadcast_message_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()

    success_count = 0
    for user in users:
        user_id = user[0]
        try:
            await context.bot.send_message(user_id, message)
            success_count += 1
            await asyncio.sleep(0.05)  # Avoid rate limiting
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {e}")

    await update.message.reply_text(
        f"✅ Broadcast sent to {success_count} users!",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Start command received")
    user = update.effective_user
    args = context.args
    referrer_id = int(args[0]) if args and args[0].isdigit() else None

    logger.info(f"Creating user: {user.id}, username: {user.username}, referrer_id: {referrer_id}")
    create_user(user.id, user.username, referrer_id)
    user_data = get_user(user.id)

    keyboard = []
    for channel in OFFICIAL_CHANNELS:
        keyboard.append([InlineKeyboardButton(f"📢 {channel}", url=f"https://t.me/{channel[1:]}")])
    keyboard.append([InlineKeyboardButton("✅ Verify Membership", callback_data="verify_membership")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    logger.info("Sending welcome message")
    await update.message.reply_text(
        f"🎉 Welcome, {user.first_name}! Join Rock-Paper-Scissors and earn $TON! 🚀\n"
        f"First, join our official channels:",
        reply_markup=reply_markup,
    )
    logger.info("Welcome message sent")

# Verify official channels
async def verify_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Verify membership callback received")
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if await check_membership(update, context, user_id, channels=OFFICIAL_CHANNELS):
        user_data = get_user(user_id)
        new_tickets = user_data[3]
        if user_data[12] == 0:  # If first time verifying
            new_tickets += 5
            if user_data[7]:  # referrer_id
                referrer_id = user_data[7]
                referrer = get_user(referrer_id)
                if referrer:
                    referrer_tickets = referrer[3] + 5
                    new_referrals = referrer[6] + 1
                    update_user(referrer_id, tickets=referrer_tickets, referrals=new_referrals)
                    try:
                        await context.bot.send_message(
                            referrer_id,
                            "🎉 New referral joined! +5 tickets added! 🎟",
                        )
                    except Exception as e:
                        logger.error(f"Error notifying referrer {referrer_id}: {e}")

        update_user(user_id, tickets=new_tickets, is_verified=1)
        await query.answer("✅ Channels verified!" + (" +5 tickets added!" if user_data[12] == 0 else ""), show_alert=True)
        user = update.effective_user
        await query.message.reply_text(
            f"🔥 Hello, {user.first_name}! Channels verified!" + (" +5 tickets added." if user_data[12] == 0 else "") + " You're ready to play! Choose an option:",
            reply_markup=main_menu(),
        )
    else:
        await query.answer("⚠️ Please join all channels and try again!", show_alert=True)
        keyboard = []
        for channel in OFFICIAL_CHANNELS:
            keyboard.append([InlineKeyboardButton(f"📢 {channel}", url=f"https://t.me/{channel[1:]}")])
        keyboard.append([InlineKeyboardButton("✅ Verify Membership", callback_data="verify_membership")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_reply_markup(reply_markup=reply_markup)

# Check verification status
async def check_verification(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    user_data = get_user(user_id)
    if user_data[12] == 0 or not await check_membership(update, context, user_id, channels=OFFICIAL_CHANNELS):
        keyboard = []
        for channel in OFFICIAL_CHANNELS:
            keyboard.append([InlineKeyboardButton(f"📢 {channel}", url=f"https://t.me/{channel[1:]}")])
        keyboard.append([InlineKeyboardButton("✅ Verify Membership", callback_data="verify_membership")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚠️ Please join the official channels and verify first!",
            reply_markup=reply_markup,
        )
        return False
    return True

# Info section
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_verification(update, context, user_id):
        return
    await update.message.reply_text(
        "📜 About the Game:\n"
        "Play Rock-Paper-Scissors and earn $TON! 💸\n"
        "🔹 Each win: +0.01 $TON\n"
        "🔹 Tickets needed (referrals: +5, partners: varies, missions: varies)\n"
        "🔹 Minimum withdrawal: 0.35 $TON\n"
        "Explore:\n"
        "- 🎮 Play to Earn: Challenge opponents!\n"
        "- 💰 Balance: Check your funds.\n"
        "- 👥 Referrals: Invite friends!\n"
        "- 🎟 Free Tickets: Earn more tickets.\n"
        "- 📜 Game History: View your past games.",
        reply_markup=main_menu(),
    )

# Play section
async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_verification(update, context, user_id):
        return
    user_data = get_user(user_id)

    if user_data[3] <= 0:  # tickets
        await update.message.reply_text(
            "😕 No tickets left! Invite friends (+5 tickets), join partner channels, or complete missions!\n"
            f"📎 Your referral link: {user_data[8]}",
            reply_markup=ReplyKeyboardMarkup(
                [["👥 Referrals", "🎟 Free Tickets"], ["🏠 Main Menu"]],
                resize_keyboard=True,
            ),
        )
        return

    await update.message.reply_text(
        f"🎮 Play to Earn!\n"
        f"📊 Your Stats:\n"
        f"- 🏆 Wins: {user_data[4]}\n"
        f"- 😔 Losses: {user_data[5]}\n"
        f"- 🎟 Tickets: {user_data[3]}\n"
        f"Ready to challenge an opponent?",
        reply_markup=ReplyKeyboardMarkup(
            [["🚀 Start Game"], ["🏠 Main Menu"]], resize_keyboard=True
        ),
    )

# Start game
async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_verification(update, context, user_id):
        return
    user_data = get_user(user_id)

    if user_data[3] <= 0:
        await update.message.reply_text(
            "😕 No tickets left! Invite friends (+5 tickets), join partner channels, or complete missions!\n"
            f"📎 Your referral link: {user_data[8]}",
            reply_markup=ReplyKeyboardMarkup(
                [["👥 Referrals", "🎟 Free Tickets"], ["🏠 Main Menu"]],
                resize_keyboard=True,
            ),
        )
        return

    motivational_messages = [
        "🔥 Get ready to crush your opponent! 💥",
        "💪 Show them who's the boss! 🏆",
        "🚀 Time to win some $TON! 🌟",
        "🎯 Make your move and win big! ⚡",
    ]
    await update.message.reply_text("🔍 Searching for an opponent... ⏳")
    await asyncio.sleep(random.uniform(3, 5))
    await update.message.reply_text(random.choice(motivational_messages))

    opponent = context.user_data.get("opponent") or random.choice(opponents)
    context.user_data["opponent"] = opponent
    context.user_data["game_start"] = time.time()

    keyboard = [
        [
            InlineKeyboardButton("✊ Rock", callback_data="rock"),
            InlineKeyboardButton("✂️ Scissors", callback_data="scissors"),
            InlineKeyboardButton("📜 Paper", callback_data="paper"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"⚔️ Your opponent: {opponent}! Game on! Choose within 15 seconds! ⏳",
        reply_markup=reply_markup,
    )

# Game logic
async def game_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_choice = query.data
    await query.answer()

    if "game_start" not in context.user_data:
        await query.message.reply_text("⚠️ Game expired! Start a new one.", reply_markup=main_menu())
        return

    opponent = context.user_data.get("opponent", "Unknown")
    choices = ["rock", "scissors", "paper"]
    opponent_choice = random.choice(choices)

    user_data = get_user(user_id)
    wins = user_data[4]
    losses = user_data[5]
    balance = user_data[2]
    tickets = user_data[3]
    total_games = user_data[10]
    username = user_data[1] or "Anonymous"

    if user_choice == opponent_choice:
        result = (
            f"⚔️ It's a tie! You chose: {user_choice.capitalize()} | Opponent: {opponent_choice.capitalize()}!\n"
            f"Choose again! 😎"
        )
        save_game_result(user_id, user_choice, opponent_choice, "Tie")
        keyboard = [
            [
                InlineKeyboardButton("✊ Rock", callback_data="rock"),
                InlineKeyboardButton("✂️ Scissors", callback_data="scissors"),
                InlineKeyboardButton("📜 Paper", callback_data="paper"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        context.user_data["game_start"] = time.time()

        await query.message.reply_text(result, reply_markup=reply_markup)
        return

    update_user(user_id, tickets=tickets - 1)
    total_games += 1
    if (
        (user_choice == "rock" and opponent_choice == "scissors")
        or (user_choice == "scissors" and opponent_choice == "paper")
        or (user_choice == "paper" and opponent_choice == "rock")
    ):
        result = f"🎉 You won! You chose: {user_choice.capitalize()} | Opponent: {opponent_choice.capitalize()}\n💰 +0.01 $TON added!"
        wins += 1
        balance += 0.01
        save_game_result(user_id, user_choice, opponent_choice, "Win")
        try:
            await context.bot.send_message(
                GAME_GROUP_ID,
                f"🏆 {username} just won 0.01 $TON!"
            )
        except Exception as e:
            logger.error(f"Failed to send group message: {e}")
    else:
        result = f"😔 You lost... You chose: {user_choice.capitalize()} | Opponent: {opponent_choice.capitalize()}\nTry again!"
        losses += 1
        save_game_result(user_id, user_choice, opponent_choice, "Loss")

    update_user(user_id, wins=wins, losses=losses, balance=balance, total_games=total_games)
    context.user_data.pop("game_start", None)
    context.user_data.pop("opponent", None)

    await query.message.reply_text(
        result,
        reply_markup=ReplyKeyboardMarkup(
            [["🚀 Play Again"], ["🏠 Main Menu"]], resize_keyboard=True
        ),
    )

# Game timeout (not used but kept for potential future use)
async def game_timeout(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data["user_id"]
    user_data = get_user(user_id)
    total_games = user_data[10] + 1
    choices = ["rock", "scissors", "paper"]
    opponent_choice = random.choice(choices)

    update_user(user_id, losses=user_data[5] + 1, tickets=user_data[3] - 1, total_games=total_games)
    save_game_result(user_id, "None", opponent_choice, "Loss (Timeout)")

    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=f"⏰ You didn’t choose! Your opponent chose {opponent_choice.capitalize()}. You lost! Try again?",
        reply_markup=ReplyKeyboardMarkup(
            [["🚀 Play Again"], ["🏠 Main Menu"]], resize_keyboard=True
        ),
    )

# Game history
async def game_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_verification(update, context, user_id):
        return

    c = conn.cursor()
    c.execute("SELECT game_id, user_choice, opponent_choice, result, timestamp FROM game_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10", (user_id,))
    games = c.fetchall()

    if not games:
        await update.message.reply_text("📜 No game history found.", reply_markup=main_menu())
        return

    history = "📜 Your Game History (Last 10):\n"
    for game in games:
        history += f"Game ID: {game[0][:8]}...\nYou: {game[1].capitalize() if game[1] != 'None' else 'No choice'} | Opponent: {game[2].capitalize()} | Result: {game[3]}\nTime: {time.ctime(game[4])}\n\n"
    await update.message.reply_text(history, reply_markup=main_menu())

# Balance section
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_verification(update, context, user_id):
        return
    user_data = get_user(user_id)

    c = conn.cursor()
    c.execute(
        "SELECT SUM(amount) FROM withdrawals WHERE user_id = ? AND status = ?",
        (user_id, "completed"),
    )
    withdrawn = c.fetchone()[0] or 0.0
    c.execute(
        "SELECT SUM(amount) FROM withdrawals WHERE user_id = ? AND status = ?",
        (user_id, "pending"),
    )
    pending = c.fetchone()[0] or 0.0

    await update.message.reply_text(
        f"💰 Your Balance:\n"
        f"- 💸 Main Balance: {user_data[2]:.2f} $TON\n"
        f"- ✅ Withdrawn: {withdrawn:.2f} $TON\n"
        f"- ⏳ Pending: {pending:.2f} $TON\n"
        f"Withdraw funds:",
        reply_markup=ReplyKeyboardMarkup(
            [["💸 Withdraw"], ["🏠 Main Menu"]], resize_keyboard=True
        ),
    )

# Withdrawal process
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_verification(update, context, user_id):
        return ConversationHandler.END
    user_data = get_user(user_id)

    if user_data[2] < 0.35:
        await update.message.reply_text(
            "⚠️ Minimum withdrawal: 0.35 $TON. Keep playing!",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    await update.message.reply_text("💸 Enter amount (e.g., 0.35):")
    return WITHDRAW_AMOUNT

async def withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    try:
        amount = float(update.message.text)
        if amount > user_data[2]:
            await update.message.reply_text("🚫 Insufficient funds! Enter a smaller amount.")
            return WITHDRAW_AMOUNT
        if amount < 0.35:
            await update.message.reply_text("⚠️ Minimum withdrawal is 0.35 $TON!")
            return WITHDRAW_AMOUNT
        context.user_data["withdraw_amount"] = amount
        await update.message.reply_text("📤 Enter your TON wallet address:")
        return WITHDRAW_ADDRESS
    except ValueError:
        await update.message.reply_text("🚫 Invalid amount! Enter a number (e.g., 0.35).")
        return WITHDRAW_AMOUNT

async def withdraw_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    amount = context.user_data["withdraw_amount"]
    wallet_address = update.message.text

    keyboard = [[InlineKeyboardButton("✅ Confirm", callback_data="confirm_withdraw")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"📤 Withdrawal: {amount:.2f} $TON\nWallet: {wallet_address}\nConfirm:",
        reply_markup=reply_markup,
    )
    context.user_data["wallet_address"] = wallet_address
    return WITHDRAW_CONFIRM

async def confirm_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    amount = context.user_data["withdraw_amount"]
    wallet_address = context.user_data["wallet_address"]
    await query.answer()

    user_data = get_user(user_id)
    new_balance = user_data[2] - amount
    update_user(user_id, balance=new_balance)

    c = conn.cursor()
    c.execute(
        "INSERT INTO withdrawals (user_id, amount, wallet_address, status, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, wallet_address, "pending", time.time()),
    )
    conn.commit()

    await query.message.reply_text(
        f"✅ Request accepted! {amount:.2f} $TON will be sent to {wallet_address} within 24 hours.",
        reply_markup=main_menu(),
    )

    context.job_queue.run_once(
        complete_withdrawal, 24 * 3600, data={"user_id": user_id, "amount": amount, "wallet_address": wallet_address}
    )

    return ConversationHandler.END

async def complete_withdrawal(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data["user_id"]
    amount = context.job.data["amount"]
    wallet_address = context.job.data["wallet_address"]

    c = conn.cursor()
    c.execute(
        "UPDATE withdrawals SET status = ? WHERE user_id = ? AND amount = ? AND wallet_address = ? AND status = ?",
        ("completed", user_id, amount, wallet_address, "pending"),
    )
    conn.commit()

# Referrals section
async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_verification(update, context, user_id):
        return
    user_data = get_user(user_id)

    referral_link = user_data[8]
    share_url = f"tg://msg_url?url={referral_link}&text=Join%20this%20awesome%20Rock-Paper-Scissors%20game%20and%20earn%20%24TON!%20🚀"
    keyboard = [
        [InlineKeyboardButton("📤 Share Link", url=share_url)],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"👥 Referral System:\n"
        f"📊 Your Referrals: {user_data[6]}\n"
        f"🎟 +5 tickets per referral (after they join channels)\n"
        f"📎 Your link: {referral_link}\n"
        f"Invite friends and earn more tickets! 😎",
        reply_markup=reply_markup,
    )

# Free Tickets section
async def free_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_verification(update, context, user_id):
        return
    keyboard = [
        ["🤝 Partners", "📋 Missions"],
        ["🎁 Daily Bonus", "🏠 Main Menu"],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "🎟 Free Tickets:\n"
        "Earn more tickets by completing tasks or claiming your daily bonus!",
        reply_markup=reply_markup,
    )

# Daily Bonus
async def daily_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_verification(update, context, user_id):
        return
    user_data = get_user(user_id)
    current_time = time.time()
    last_bonus_time = user_data[13] or 0
    streak = user_data[14] or 0

    if current_time - last_bonus_time < 24 * 3600:
        next_bonus_time = last_bonus_time + 24 * 3600
        remaining = int(next_bonus_time - current_time)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        await update.message.reply_text(
            f"⏳ You've already claimed today's bonus! Next bonus in {hours}h {minutes}m.",
            reply_markup=main_menu(),
        )
        return

    # Check if streak should reset
    if current_time - last_bonus_time > 48 * 3600:  # Missed a day
        streak = 0
    else:
        streak += 1

    # Calculate bonus
    bonus_tickets = min(max(streak, 1), 5)  # Ensure at least 1 ticket on first day
    new_tickets = user_data[3] + bonus_tickets
    update_user(user_id, tickets=new_tickets, last_daily_bonus=current_time, daily_bonus_streak=streak)

    bonus_explanation = (
        "🎁 Daily Bonus:\n"
        "Claim every day to increase your bonus!\n"
        "- Day 1: +1 ticket\n"
        "- Day 2: +2 tickets\n"
        "- Day 3: +3 tickets\n"
        "- Day 4: +4 tickets\n"
        "- Day 5+: +5 tickets\n"
        "Miss a day, and it resets to +1 ticket!\n"
        f"✅ You claimed +{bonus_tickets} ticket(s)! Current streak: {streak} day(s)."
    )
    await update.message.reply_text(bonus_explanation, reply_markup=main_menu())

# Partners section
async def partners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_verification(update, context, user_id):
        return
    keyboard = []
    partner_channels = get_partner_channels()
    for idx, (channel, ticket_reward, _) in enumerate(partner_channels):
        keyboard.append([
            InlineKeyboardButton(f"📢 {channel}", url=f"https://t.me/{channel[1:]}"),
            InlineKeyboardButton(f"✅ Confirm (+{ticket_reward})", callback_data=f"confirm_partner_{idx}")
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"🤝 Partner Channels:\n"
        f"Join and earn extra tickets!\n"
        f"Join the channels below and confirm:",
        reply_markup=reply_markup,
    )

async def confirm_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    channel_idx = int(query.data.split("_")[-1])
    await query.answer()

    logger.info(f"Confirm partner clicked: user_id={user_id}, channel_idx={channel_idx}")

    user_data = get_user(user_id)
    partner_channels = user_data[9].split(",") if user_data[9] else []
    logger.info(f"User {user_id} partner channels: {partner_channels}")

    if str(channel_idx) in partner_channels:
        await query.answer("⚠️ You’ve already claimed tickets for this channel!", show_alert=True)
        await query.message.reply_text(
            "⚠️ You’ve already claimed tickets for this channel!",
            reply_markup=main_menu(),
        )
        return

    partner_channels_list = get_partner_channels()
    if channel_idx >= len(partner_channels_list):
        await query.answer("⚠️ Invalid channel!", show_alert=True)
        return
    channel, ticket_reward, require_membership = partner_channels_list[channel_idx]

    # Handle channels with membership check
    if require_membership:
        if not await check_membership(update, context, user_id, [channel]):
            await query.answer(f"⚠️ Please join {channel} first!", show_alert=True)
            keyboard = [[InlineKeyboardButton(f"📢 {channel}", url=f"https://t.me/{channel[1:]}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                f"⚠️ Please join {channel} and try again!",
                reply_markup=reply_markup,
            )
            return
    # Handle channels with click count
    else:
        click_count_key = f"click_count_{channel_idx}_{user_id}"
        click_count = context.user_data.get(click_count_key, 0) + 1
        context.user_data[click_count_key] = click_count
        logger.info(f"Click count for user {user_id} on channel {channel_idx}: {click_count}")

        required_clicks = 3 if channel_idx == 0 else 2
        if click_count < required_clicks:
            await query.answer("⚠️ Keep clicking to confirm!", show_alert=True)
            return

    keyboard = []
    for idx, (ch, reward, req_mem) in enumerate(partner_channels_list):
        if idx == channel_idx:
            continue
        if str(idx) in partner_channels:
            continue
        keyboard.append([
            InlineKeyboardButton(f"📢 {ch}", url=f"https://t.me/{ch[1:]}"),
            InlineKeyboardButton(f"✅ Confirm (+{reward})", callback_data=f"confirm_partner_{idx}")
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)

    new_tickets = user_data[3] + ticket_reward
    partner_channels.append(str(channel_idx))
    update_user(user_id, tickets=new_tickets, partner_channels=",".join(partner_channels))
    if not require_membership:
        context.user_data[click_count_key] = 0

    await query.answer(f"✅ Great! You’ve completed the task! +{ticket_reward} tickets added!", show_alert=True)
    if keyboard:
        await query.message.edit_reply_markup(reply_markup=reply_markup)
    else:
        await query.message.reply_text(
            "🔥 Great! All channels completed! Choose an option:",
            reply_markup=main_menu(),
        )

# Missions section
async def missions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_verification(update, context, user_id):
        return
    user_data = get_user(user_id)
    completed_missions = user_data[11].split(",") if user_data[11] else []
    wins = user_data[4]
    referrals = user_data[6]
    total_games = user_data[10]

    logger.info(f"Missions for user {user_id}: completed_missions={completed_missions}, wins={wins}, referrals={referrals}, total_games={total_games}")

    keyboard = []
    mission_list = [
        ("10 Wins", 10, wins, 2, "wins_10"),
        ("5 Referrals", 5, referrals, 2, "referrals_5"),
        ("15 Wins", 15, wins, 3, "wins_15"),
        ("10 Referrals", 10, referrals, 3, "referrals_10"),
        ("100 Games", 100, total_games, 5, "games_100"),
        ("25 Wins", 25, wins, 5, "wins_25"),
        ("20 Referrals", 20, referrals, 5, "referrals_20"),
        ("100 Wins", 100, wins, 10, "wins_100"),
        ("100 Referrals", 100, referrals, 15, "referrals_100"),
    ]

    for mission_name, required, current, reward, mission_id in mission_list:
        progress = min(current, required)
        if mission_id in completed_missions:
            keyboard.append([
                InlineKeyboardButton(
                    f"✅ {mission_name}: {progress}/{required} (+{reward} tickets) - Claimed",
                    callback_data=f"claimed_mission_{mission_id}"
                )
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(
                    f"📋 {mission_name}: {progress}/{required} (+{reward} tickets)",
                    callback_data=f"mission_info_{mission_id}"
                ),
                InlineKeyboardButton(
                    "✅ Claim" if progress >= required else "🔒 Locked",
                    callback_data=f"claim_mission_{mission_id}"
                )
            ])

    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_free_tickets")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if not any(mission_id not in completed_missions for _, _, _, _, mission_id in mission_list):
        await update.message.reply_text(
            "📋 Missions:\n🎉 You've completed all missions! Stay tuned for more challenges!",
            reply_markup=reply_markup,
        )
    else:
        await update.message.reply_text(
            "📋 Missions:\nComplete these tasks to earn free tickets! 🎟️",
            reply_markup=reply_markup,
        )

# Individual mission claim handlers
async def claim_wins_10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    user_data = get_user(user_id)
    if not user_data:
        await query.message.reply_text("⚠️ User data not found.", reply_markup=main_menu())
        return

    completed_missions = user_data[11].split(",") if user_data[11] else []
    if "wins_10" in completed_missions:
        await query.answer("⚠️ You've already claimed this mission!", show_alert=True)
        return

    wins = user_data[4]
    if wins < 10:
        await query.answer("⚠️ Mission not yet completed! Need 10 wins.", show_alert=True)
        return

    new_tickets = user_data[3] + 2
    completed_missions.append("wins_10")
    update_user(user_id, tickets=new_tickets, completed_missions=",".join(completed_missions))

    await query.message.reply_text(
        "Congratulations! You have completed '10 Wins' and earned +2 tickets! 🎉",
        reply_markup=ReplyKeyboardMarkup([["📋 Missions"], ["🏠 Main Menu"]], resize_keyboard=True)
    )
    await update_mission_list(update, context)

async def claim_referrals_5(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    user_data = get_user(user_id)
    if not user_data:
        await query.message.reply_text("⚠️ User data not found.", reply_markup=main_menu())
        return

    completed_missions = user_data[11].split(",") if user_data[11] else []
    if "referrals_5" in completed_missions:
        await query.answer("⚠️ You've already claimed this mission!", show_alert=True)
        return

    referrals = user_data[6]
    if referrals < 5:
        await query.answer("⚠️ Mission not yet completed! Need 5 referrals.", show_alert=True)
        return

    new_tickets = user_data[3] + 2
    completed_missions.append("referrals_5")
    update_user(user_id, tickets=new_tickets, completed_missions=",".join(completed_missions))

    await query.message.reply_text(
        "Congratulations! You have completed '5 Referrals' and earned +2 tickets! 🎉",
        reply_markup=ReplyKeyboardMarkup([["📋 Missions"], ["🏠 Main Menu"]], resize_keyboard=True)
    )
    await update_mission_list(update, context)

async def claim_wins_15(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    user_data = get_user(user_id)
    if not user_data:
        await query.message.reply_text("⚠️ User data not found.", reply_markup=main_menu())
        return

    completed_missions = user_data[11].split(",") if user_data[11] else []
    if "wins_15" in completed_missions:
        await query.answer("⚠️ You've already claimed this mission!", show_alert=True)
        return

    wins = user_data[4]
    if wins < 15:
        await query.answer("⚠️ Mission not yet completed! Need 15 wins.", show_alert=True)
        return

    new_tickets = user_data[3] + 3
    completed_missions.append("wins_15")
    update_user(user_id, tickets=new_tickets, completed_missions=",".join(completed_missions))

    await query.message.reply_text(
        "Congratulations! You have completed '15 Wins' and earned +3 tickets! 🎉",
        reply_markup=ReplyKeyboardMarkup([["📋 Missions"], ["🏠 Main Menu"]], resize_keyboard=True)
    )
    await update_mission_list(update, context)

async def claim_referrals_10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    user_data = get_user(user_id)
    if not user_data:
        await query.message.reply_text("⚠️ User data not found.", reply_markup=main_menu())
        return

    completed_missions = user_data[11].split(",") if user_data[11] else []
    if "referrals_10" in completed_missions:
        await query.answer("⚠️ You've already claimed this mission!", show_alert=True)
        return

    referrals = user_data[6]
    if referrals < 10:
        await query.answer("⚠️ Mission not yet completed! Need 10 referrals.", show_alert=True)
        return

    new_tickets = user_data[3] + 3
    completed_missions.append("referrals_10")
    update_user(user_id, tickets=new_tickets, completed_missions=",".join(completed_missions))

    await query.message.reply_text(
        "Congratulations! You have completed '10 Referrals' and earned +3 tickets! 🎉",
        reply_markup=ReplyKeyboardMarkup([["📋 Missions"], ["🏠 Main Menu"]], resize_keyboard=True)
    )
    await update_mission_list(update, context)

async def claim_games_100(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    user_data = get_user(user_id)
    if not user_data:
        await query.message.reply_text("⚠️ User data not found.", reply_markup=main_menu())
        return

    completed_missions = user_data[11].split(",") if user_data[11] else []
    if "games_100" in completed_missions:
        await query.answer("⚠️ You've already claimed this mission!", show_alert=True)
        return

    total_games = user_data[10]
    if total_games < 100:
        await query.answer("⚠️ Mission not yet completed! Need 100 games.", show_alert=True)
        return

    new_tickets = user_data[3] + 5
    completed_missions.append("games_100")
    update_user(user_id, tickets=new_tickets, completed_missions=",".join(completed_missions))

    await query.message.reply_text(
        "Congratulations! You have completed '100 Games' and earned +5 tickets! 🎉",
        reply_markup=ReplyKeyboardMarkup([["📋 Missions"], ["🏠 Main Menu"]], resize_keyboard=True)
    )
    await update_mission_list(update, context)

async def claim_wins_25(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    user_data = get_user(user_id)
    if not user_data:
        await query.message.reply_text("⚠️ User data not found.", reply_markup=main_menu())
        return

    completed_missions = user_data[11].split(",") if user_data[11] else []
    if "wins_25" in completed_missions:
        await query.answer("⚠️ You've already claimed this mission!", show_alert=True)
        return

    wins = user_data[4]
    if wins < 25:
        await query.answer("⚠️ Mission not yet completed! Need 25 wins.", show_alert=True)
        return

    new_tickets = user_data[3] + 5
    completed_missions.append("wins_25")
    update_user(user_id, tickets=new_tickets, completed_missions=",".join(completed_missions))

    await query.message.reply_text(
        "Congratulations! You have completed '25 Wins' and earned +5 tickets! 🎉",
        reply_markup=ReplyKeyboardMarkup([["📋 Missions"], ["🏠 Main Menu"]], resize_keyboard=True)
    )
    await update_mission_list(update, context)

async def claim_referrals_20(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    user_data = get_user(user_id)
    if not user_data:
        await query.message.reply_text("⚠️ User data not found.", reply_markup=main_menu())
        return

    completed_missions = user_data[11].split(",") if user_data[11] else []
    if "referrals_20" in completed_missions:
        await query.answer("⚠️ You've already claimed this mission!", show_alert=True)
        return

    referrals = user_data[6]
    if referrals < 20:
        await query.answer("⚠️ Mission not yet completed! Need 20 referrals.", show_alert=True)
        return

    new_tickets = user_data[3] + 5
    completed_missions.append("referrals_20")
    update_user(user_id, tickets=new_tickets, completed_missions=",".join(completed_missions))

    await query.message.reply_text(
        "Congratulations! You have completed '20 Referrals' and earned +5 tickets! 🎉",
        reply_markup=ReplyKeyboardMarkup([["📋 Missions"], ["🏠 Main Menu"]], resize_keyboard=True)
    )
    await update_mission_list(update, context)

async def claim_wins_100(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    user_data = get_user(user_id)
    if not user_data:
        await query.message.reply_text("⚠️ User data not found.", reply_markup=main_menu())
        return

    completed_missions = user_data[11].split(",") if user_data[11] else []
    if "wins_100" in completed_missions:
        await query.answer("⚠️ You've already claimed this mission!", show_alert=True)
        return

    wins = user_data[4]
    if wins < 100:
        await query.answer("⚠️ Mission not yet completed! Need 100 wins.", show_alert=True)
        return

    new_tickets = user_data[3] + 10
    completed_missions.append("wins_100")
    update_user(user_id, tickets=new_tickets, completed_missions=",".join(completed_missions))

    await query.message.reply_text(
        "Congratulations! You have completed '100 Wins' and earned +10 tickets! 🎉",
        reply_markup=ReplyKeyboardMarkup([["📋 Missions"], ["🏠 Main Menu"]], resize_keyboard=True)
    )
    await update_mission_list(update, context)

async def claim_referrals_100(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    user_data = get_user(user_id)
    if not user_data:
        await query.message.reply_text("⚠️ User data not found.", reply_markup=main_menu())
        return

    completed_missions = user_data[11].split(",") if user_data[11] else []
    if "referrals_100" in completed_missions:
        await query.answer("⚠️ You've already claimed this mission!", show_alert=True)
        return

    referrals = user_data[6]
    if referrals < 100:
        await query.answer("⚠️ Mission not yet completed! Need 100 referrals.", show_alert=True)
        return

    new_tickets = user_data[3] + 15
    completed_missions.append("referrals_100")
    update_user(user_id, tickets=new_tickets, completed_missions=",".join(completed_missions))

    await query.message.reply_text(
        "Congratulations! You have completed '100 Referrals' and earned +15 tickets! 🎉",
        reply_markup=ReplyKeyboardMarkup([["📋 Missions"], ["🏠 Main Menu"]], resize_keyboard=True)
    )
    await update_mission_list(update, context)

# Update mission list after claiming
async def update_mission_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_data = get_user(user_id)
    completed_missions = user_data[11].split(",") if user_data[11] else []
    wins = user_data[4]
    referrals = user_data[6]
    total_games = user_data[10]

    keyboard = []
    mission_list = [
        ("10 Wins", 10, wins, 2, "wins_10"),
        ("5 Referrals", 5, referrals, 2, "referrals_5"),
        ("15 Wins", 15, wins, 3, "wins_15"),
        ("10 Referrals", 10, referrals, 3, "referrals_10"),
        ("100 Games", 100, total_games, 5, "games_100"),
        ("25 Wins", 25, wins, 5, "wins_25"),
        ("20 Referrals", 20, referrals, 5, "referrals_20"),
        ("100 Wins", 100, wins, 10, "wins_100"),
        ("100 Referrals", 100, referrals, 15, "referrals_100"),
    ]

    for mission_name, required, current, reward, mission_id in mission_list:
        progress = min(current, required)
        if mission_id in completed_missions:
            keyboard.append([
                InlineKeyboardButton(
                    f"✅ {mission_name}: {progress}/{required} (+{reward} tickets) - Claimed",
                    callback_data=f"claimed_mission_{mission_id}"
                )
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(
                    f"📋 {mission_name}: {progress}/{required} (+{reward} tickets)",
                    callback_data=f"mission_info_{mission_id}"
                ),
                InlineKeyboardButton(
                    "✅ Claim" if progress >= required else "🔒 Locked",
                    callback_data=f"claim_mission_{mission_id}"
                )
            ])

    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_free_tickets")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.message.edit_reply_markup(reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Failed to update mission list for user {user_id}: {e}")

async def mission_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("📋 This is a mission info button.", show_alert=True)

async def claimed_mission_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ This mission is already claimed!", show_alert=True)

async def back_to_free_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        ["🤝 Partners", "📋 Missions"],
        ["🎁 Daily Bonus", "🏠 Main Menu"],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await query.message.reply_text(
        "🎟 Free Tickets:\n"
        "Earn more tickets by completing tasks or claiming your daily bonus!",
        reply_markup=reply_markup,
    )

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Choose an option:", reply_markup=main_menu())

# Periodic activity notifications
async def send_activity_notification(context: ContextTypes.DEFAULT_TYPE):
    actions = [
        f"{random.choice(opponents)} just won 0.01 $TON! 🏆",
        f"{random.choice(opponents)} just won 0.01 $TON! 🏆",
        f"{random.choice(opponents)} just won 0.01 $TON! 🏆",
        f"{random.choice(opponents)} invited a friend and earned 5 tickets! 🎟",
        f"{random.choice(opponents)} completed a mission and got 3 tickets! 🚀",
        f"{random.choice(opponents)} joined a partner channel for 2 tickets! 📢",
        f"{random.choice(opponents)} claimed their daily bonus! 🎁",
    ]
    # Add withdrawal message with 5% probability (approx. every 20-30 messages)
    if random.random() < 0.05:
        amount = round(random.uniform(0.35, 1.0), 2)
        action = f"{random.choice(opponents)} just withdrew {amount} $TON! 💸"
    else:
        action = random.choice(actions)

    try:
        await context.bot.send_message(GAME_GROUP_ID, action)
    except Exception as e:
        logger.error(f"Failed to send activity notification: {e}")

# Handle text commands
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📜 Info":
        await info(update, context)
    elif text == "🎮 Play to Earn":
        await play(update, context)
    elif text == "💰 Balance":
        await balance(update, context)
    elif text == "👥 Referrals":
        await referrals(update, context)
    elif text == "🎟 Free Tickets":
        await free_tickets(update, context)
    elif text == "🤝 Partners":
        await partners(update, context)
    elif text == "📋 Missions":
        await missions(update, context)
    elif text == "🎁 Daily Bonus":
        await daily_bonus(update, context)
    elif text == "🚀 Start Game" or text == "🚀 Play Again":
        await start_game(update, context)
    elif text == "🏠 Main Menu":
        await update.message.reply_text("Choose an option:", reply_markup=main_menu())
    elif text == "💸 Withdraw":
        return await withdraw(update, context)
    elif text == "📜 Game History":
        await game_history(update, context)
    elif text == "🔐 Admin Panel":
        await admin_panel(update, context)
    elif text == "➕ Add Partner Channel":
        return await add_partner_channel_handler(update, context)
    elif text == "🗑 Remove Partner Channel":
        return await remove_partner_channel_handler(update, context)
    elif text == "📊 View Stats":
        await view_stats(update, context)
    elif text == "📢 Broadcast Message":
        return await broadcast_message(update, context)

# Main function
def main():
    global BOT_USERNAME
    BOT_USERNAME = "RockPaperTON_Bot"
    logger.info("Starting bot...")
    application = Application.builder().token(TOKEN).connect_timeout(20).read_timeout(20).build()

    init_db()

    # Conversation handlers
    withdraw_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💸 Withdraw$"), withdraw)],
        states={
            WITHDRAW_AMOUNT: [MessageHandler(filters.Text() & ~filters.Command(), withdraw_amount)],
            WITHDRAW_ADDRESS: [MessageHandler(filters.Text() & ~filters.Command(), withdraw_address)],
            WITHDRAW_CONFIRM: [CallbackQueryHandler(confirm_withdraw, pattern="^confirm_withdraw$")],
        },
        fallbacks=[],
        per_message=False,
    )

    add_partner_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Add Partner Channel$"), add_partner_channel_handler)],
        states={
            CHANNEL_NAME: [MessageHandler(filters.Text() & ~filters.Command(), add_partner_channel_name)],
            TICKET_REWARD: [MessageHandler(filters.Text() & ~filters.Command(), add_partner_channel_type)],
            CHANNEL_TYPE: [CallbackQueryHandler(add_partner_channel_reward, pattern="^(membership|clickcount)$")],
        },
        fallbacks=[],
        per_message=False,
    )

    remove_partner_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🗑 Remove Partner Channel$"), remove_partner_channel_handler)],
        states={
            REMOVE_CHANNEL_NAME: [MessageHandler(filters.Text() & ~filters.Command(), remove_partner_channel_name)],
        },
        fallbacks=[],
        per_message=False,
    )

    broadcast_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 Broadcast Message$"), broadcast_message)],
        states={
            BROADCAST_TEXT: [MessageHandler(filters.Text() & ~filters.Command(), broadcast_message_text)],
        },
        fallbacks=[],
        per_message=False,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("game_history", game_history))
    application.add_handler(CallbackQueryHandler(verify_membership, pattern="^verify_membership$"))
    application.add_handler(CallbackQueryHandler(game_choice, pattern="^(rock|scissors|paper)$"))
    application.add_handler(CallbackQueryHandler(confirm_partner, pattern="^confirm_partner_"))
    application.add_handler(CallbackQueryHandler(claim_wins_10, pattern="^claim_mission_wins_10$"))
    application.add_handler(CallbackQueryHandler(claim_referrals_5, pattern="^claim_mission_referrals_5$"))
    application.add_handler(CallbackQueryHandler(claim_wins_15, pattern="^claim_mission_wins_15$"))
    application.add_handler(CallbackQueryHandler(claim_referrals_10, pattern="^claim_mission_referrals_10$"))
    application.add_handler(CallbackQueryHandler(claim_games_100, pattern="^claim_mission_games_100$"))
    application.add_handler(CallbackQueryHandler(claim_wins_25, pattern="^claim_mission_wins_25$"))
    application.add_handler(CallbackQueryHandler(claim_referrals_20, pattern="^claim_mission_referrals_20$"))
    application.add_handler(CallbackQueryHandler(claim_wins_100, pattern="^claim_mission_wins_100$"))
    application.add_handler(CallbackQueryHandler(claim_referrals_100, pattern="^claim_mission_referrals_100$"))
    application.add_handler(CallbackQueryHandler(mission_info_handler, pattern="^mission_info_"))
    application.add_handler(CallbackQueryHandler(claimed_mission_handler, pattern="^claimed_mission_"))
    application.add_handler(CallbackQueryHandler(back_to_free_tickets, pattern="^back_to_free_tickets$"))
    application.add_handler(CallbackQueryHandler(back_to_main_menu, pattern="^back_to_main_menu$"))
    application.add_handler(withdraw_handler)
    application.add_handler(add_partner_handler)
    application.add_handler(remove_partner_handler)
    application.add_handler(broadcast_handler)
    application.add_handler(MessageHandler(filters.Text() & ~filters.Command(), handle_text))

    # Schedule periodic activity notifications
    application.job_queue.run_repeating(send_activity_notification, interval=random.randint(3, 7), first=3)

    logger.info("Bot polling started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Bot polling stopped")

if __name__ == "__main__":
    main()
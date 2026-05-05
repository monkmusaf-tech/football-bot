import os
import random
from datetime import datetime, timedelta
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, CallbackContext
import psycopg2
from psycopg2.extras import RealDictCursor
import asyncio

# ------------- PostgreSQL -------------
DATABASE_URL = os.getenv("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL)

# ------------- Fungsi DB -------------
def init_db():
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS clubs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT UNIQUE,
                club_name TEXT,
                photo_url TEXT,
                wins INT DEFAULT 0,
                draws INT DEFAULT 0,
                losses INT DEFAULT 0,
                goals_for INT DEFAULT 0,
                goals_against INT DEFAULT 0,
                points INT DEFAULT 0,
                matches_played INT DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS league_status (
                id INT PRIMARY KEY DEFAULT 1,
                current_week INT DEFAULT 1,
                season_start_date TIMESTAMP
            )
        """)
        cur.execute("INSERT INTO league_status (id) VALUES (1) ON CONFLICT DO NOTHING")
        conn.commit()
init_db()

# ------------- Helper -------------
def get_club(user_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM clubs WHERE user_id = %s", (user_id,))
        return cur.fetchone()

def get_all_clubs():
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM clubs ORDER BY points DESC, goals_for - goals_against DESC")
        return cur.fetchall()

def get_league_week():
    with conn.cursor() as cur:
        cur.execute("SELECT current_week, season_start_date FROM league_status WHERE id=1")
        row = cur.fetchone()
        if row[1] is None:
            return row[0], None
        return row[0], row[1]

def set_league_week(week, start_date=None):
    with conn.cursor() as cur:
        if start_date:
            cur.execute("UPDATE league_status SET current_week=%s, season_start_date=%s WHERE id=1", (week, start_date))
        else:
            cur.execute("UPDATE league_status SET current_week=%s WHERE id=1", (week,))
        conn.commit()

# ------------- Bot Commands -------------
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "⚽ *Football Club Manager*\n\n"
        "1. /createclub <nama> - Buat club\n"
        "2. /uploadfoto - Kirim foto untuk logo club\n"
        "3. /myclub - Info clubmu\n"
        "4. /leaderboard - Top 10 club\n"
        "5. /status - Info liga\n"
        "6. /tanding - Lihat jadwal tanding (admin)\n\n"
        "Admin: /startliga - Mulai liga baru", parse_mode="Markdown"
    )

async def createclub(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    club_name = " ".join(context.args)
    if not club_name:
        await update.message.reply_text("Gunakan: /createclub NamaClub")
        return
    if get_club(user_id):
        await update.message.reply_text("Kamu sudah punya club!")
        return
    with conn.cursor() as cur:
        cur.execute("INSERT INTO clubs (user_id, club_name) VALUES (%s, %s)", (user_id, club_name))
        conn.commit()
    await update.message.reply_text(f"✅ Club *{club_name}* berhasil dibuat! Kirim /uploadfoto untuk logo.", parse_mode="Markdown")

async def uploadfoto(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    club = get_club(user_id)
    if not club:
        await update.message.reply_text("Buat club dulu dengan /createclub")
        return
    if not update.message.photo:
        await update.message.reply_text("Kirim foto sebagai logo.")
        return
    photo = update.message.photo[-1]
    file = await photo.get_file()
    file_url = file.file_path
    with conn.cursor() as cur:
        cur.execute("UPDATE clubs SET photo_url = %s WHERE user_id = %s", (file_url, user_id))
        conn.commit()
    await update.message.reply_text("✅ Logo club tersimpan!")

async def myclub(update: Update, context: CallbackContext):
    club = get_club(update.effective_user.id)
    if not club:
        await update.message.reply_text("Kamu belum punya club.")
        return
    text = (f"🏟️ *{club['club_name']}*\n"
            f"📊 {club['wins']}W - {club['draws']}D - {club['losses']}L\n"
            f"⚽ Goals: {club['goals_for']} : {club['goals_against']}\n"
            f"🎯 Poin: {club['points']} ({club['matches_played']} main)")
    if club['photo_url']:
        await update.message.reply_photo(photo=club['photo_url'], caption=text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

async def leaderboard(update: Update, context: CallbackContext):
    clubs = get_all_clubs()
    if not clubs:
        await update.message.reply_text("Belum ada club.")
        return
    msg = "*🏆 TOP 10 CLUB*\n\n"
    for i, c in enumerate(clubs[:10], 1):
        msg += f"{i}. *{c['club_name']}* - {c['points']} poin (GD: {c['goals_for']-c['goals_against']})\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def status(update: Update, context: CallbackContext):
    week, start_date = get_league_week()
    if start_date is None:
        await update.message.reply_text("Liga belum dimulai. Admin ketik /startliga")
        return
    end_date = start_date + timedelta(days=7)
    remaining = (end_date - datetime.now()).days
    await update.message.reply_text(
        f"📅 *Musim ke-{week}*\n"
        f"Sisa waktu: {remaining} hari\n"
        f"Pertandingan setiap jam 12:00 WIB", parse_mode="Markdown"
    )

async def startliga(update: Update, context: CallbackContext):
    if update.effective_user.id != 7621771510:  # Ganti dengan ID admin
        await update.message.reply_text("Hanya admin.")
        return
    set_league_week(1, datetime.now())
    await update.message.reply_text("🏁 Liga baru dimulai! Pertandingan akan berjalan otomatis.")

async def simulate_matches(context: CallbackContext):
    week, start_date = get_league_week()
    if start_date is None:
        return
    # Simulasi tiap hari jam 12 siang
    clubs = get_all_clubs()
    if len(clubs) < 2:
        return
    # Round robin sederhana
    random.shuffle(clubs)
    for i in range(0, len(clubs)-1, 2):
        home = clubs[i]
        away = clubs[i+1]
        home_goals = random.randint(0, 5)
        away_goals = random.randint(0, 5)
        # Update stats
        with conn.cursor() as cur:
            cur.execute("UPDATE clubs SET goals_for = goals_for + %s, goals_against = goals_against + %s, matches_played = matches_played + 1 WHERE id = %s", (home_goals, away_goals, home['id']))
            cur.execute("UPDATE clubs SET goals_for = goals_for + %s, goals_against = goals_against + %s, matches_played = matches_played + 1 WHERE id = %s", (away_goals, home_goals, away['id']))
            if home_goals > away_goals:
                cur.execute("UPDATE clubs SET wins = wins + 1, points = points + 3 WHERE id = %s", (home['id'],))
                cur.execute("UPDATE clubs SET losses = losses + 1 WHERE id = %s", (away['id'],))
            elif home_goals < away_goals:
                cur.execute("UPDATE clubs SET losses = losses + 1 WHERE id = %s", (home['id'],))
                cur.execute("UPDATE clubs SET wins = wins + 1, points = points + 3 WHERE id = %s", (away['id'],))
            else:
                cur.execute("UPDATE clubs SET draws = draws + 1, points = points + 1 WHERE id = %s", (home['id'],))
                cur.execute("UPDATE clubs SET draws = draws + 1, points = points + 1 WHERE id = %s", (away['id'],))
            conn.commit()
        await context.bot.send_message(123456789, f"🏆 {home['club_name']} {home_goals} - {away_goals} {away['club_name']}")
    # Cek akhir musim
    week, start_date = get_league_week()
    if datetime.now() >= start_date + timedelta(days=7):
        set_league_week(week+1, datetime.now())
        await context.bot.send_message(123456789, f"🎉 Musim {week} selesai! Musim {week+1} dimulai.")

def schedule_matches(app):
    # Setiap hari jam 12 siang UTC (sesuaikan)
    app.job_queue.run_daily(simulate_matches, time=datetime.time(hour=12, minute=0))

# ------------- Main -------------
def main():
    TOKEN = os.getenv("BOT_TOKEN")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("createclub", createclub))
    app.add_handler(CommandHandler("uploadfoto", uploadfoto))
    app.add_handler(CommandHandler("myclub", myclub))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("startliga", startliga))
    schedule_matches(app)
    app.run_polling()

if __name__ == "__main__":
    main()

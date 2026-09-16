import telebot
from telebot import types
import sqlite3
import random
import threading
import time
import os
from datetime import datetime, date, timedelta

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

bot = telebot.TeleBot(TOKEN)

DB_PATH = "seal_life.db"

# ==================== ИНИЦИАЛИЗАЦИЯ БД ====================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS players (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        display_name TEXT,
        photo_path TEXT,
        fishnets INTEGER DEFAULT 100
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS seals (
        seal_id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER,
        name TEXT,
        health INTEGER DEFAULT 100,
        max_health INTEGER DEFAULT 100,
        mood INTEGER DEFAULT 80,
        satiety INTEGER DEFAULT 80,
        strength INTEGER DEFAULT 10,
        defense INTEGER DEFAULT 5,
        level INTEGER DEFAULT 1,
        exp INTEGER DEFAULT 0,
        is_baby INTEGER DEFAULT 0,
        born_at TEXT,
        equipped_weapon TEXT,
        equipped_armor TEXT,
        equipped_helmet TEXT,
        equipped_shield TEXT,
        equipped_accessory TEXT,
        work_cooldown TEXT,
        play_cooldown TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS marriages (
        marriage_id INTEGER PRIMARY KEY AUTOINCREMENT,
        seal1_id INTEGER,
        seal2_id INTEGER,
        player1_id INTEGER,
        player2_id INTEGER,
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS inventory (
        inv_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        item_name TEXT,
        item_type TEXT,
        quantity INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS daily_quests (
        quest_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        quest_type TEXT,
        quest_target INTEGER,
        quest_progress INTEGER DEFAULT 0,
        quest_reward INTEGER,
        date TEXT,
        claimed INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS dungeon_runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        seal_id INTEGER,
        current_floor INTEGER DEFAULT 1,
        active INTEGER DEFAULT 0
    )''')

    # Миграция: добавляем новые колонки если их нет
    c.execute("PRAGMA table_info(seals)")
    cols = [row for row in c.fetchall()]
    if "equipped_accessory" not in cols:
        c.execute("ALTER TABLE seals ADD COLUMN equipped_accessory TEXT")
    if "work_cooldown" not in cols:
        c.execute("ALTER TABLE seals ADD COLUMN work_cooldown TEXT")
    if "play_cooldown" not in cols:
        c.execute("ALTER TABLE seals ADD COLUMN play_cooldown TEXT")

    conn.commit()
    conn.close()

init_db()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def get_player(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_seal(seal_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM seals WHERE seal_id = ?", (seal_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_player_seals(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM seals WHERE owner_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def update_seal(seal_id, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    sets = ", ".join([f"{k} = ?" for k in kwargs])
    vals = list(kwargs.values()) + [seal_id]
    c.execute(f"UPDATE seals SET {sets} WHERE seal_id = ?", vals)
    conn.commit()
    conn.close()

def add_fishnets(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE players SET fishnets = fishnets + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def get_fishnets(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT fishnets FROM players WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row if row else 0

def add_to_inventory(user_id, item_name, item_type, qty=1):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, item_name))
    row = c.fetchone()
    if row:
        c.execute("UPDATE inventory SET quantity = quantity + ? WHERE user_id = ? AND item_name = ?", (qty, user_id, item_name))
    else:
        c.execute("INSERT INTO inventory (user_id, item_name, item_type, quantity) VALUES (?, ?, ?, ?)", (user_id, item_name, item_type, qty))
    conn.commit()
    conn.close()

def get_inventory(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM inventory WHERE user_id = ? AND quantity > 0", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def remove_from_inventory(user_id, item_name, qty=1):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, item_name))
    row = c.fetchone()
    if row:
        new_qty = row - qty
        if new_qty <= 0:
            c.execute("DELETE FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, item_name))
        else:
            c.execute("UPDATE inventory SET quantity = ? WHERE user_id = ? AND item_name = ?", (new_qty, user_id, item_name))
        conn.commit()
    conn.close()

def exp_for_level(level):
    return level * 100 + (level - 1) * 50

def check_levelup(seal_id):
    seal = get_seal(seal_id)
    if not seal:
        return False
    level = seal
    exp = seal
    needed = exp_for_level(level)
    if exp >= needed:
        new_level = level + 1
        new_exp = exp - needed
        str_bonus = random.randint(2, 5)
        def_bonus = random.randint(1, 3)
        hp_bonus = random.randint(10, 20)
        update_seal(
            seal_id,
            level=new_level,
            exp=new_exp,
            strength=seal + str_bonus,
            defense=seal + def_bonus,
            max_health=seal + hp_bonus,
            health=seal + hp_bonus
        )
        return new_level
    return False

def get_effective_stats(seal_id):
    seal = get_seal(seal_id)
    if not seal:
        return 0, 0, 0
    base_str = seal
    base_def = seal
    base_hp = seal

    item_bonuses = {
        "Меч ⚔️": {"str": 5},
        "Щит 🛡️": {"def": 5},
        "Шлем 🪖": {"def": 3, "hp": 10},
        "Броня 👕": {"def": 7, "hp": 20},
    }

    str_bonus = 0
    def_bonus = 0
    hp_bonus = 0

    for slot in [seal, seal, seal, seal]:
        if slot and slot in item_bonuses:
            b = item_bonuses[slot]
            str_bonus += b.get("str", 0)
            def_bonus += b.get("def", 0)
            hp_bonus += b.get("hp", 0)

    return base_str + str_bonus, base_def + def_bonus, base_hp + hp_bonus

def get_mood_bonus(seal_id):
    seal = get_seal(seal_id)
    if not seal:
        return 0
    accessory = seal
    accessory_bonuses = {
        "Бантик 🎀": 10,
        "Шарф 🧣": 8,
        "Корона 👑": 20,
        "Очки 🕶️": 7,
        "Цветок 🌸": 5,
    }
    return accessory_bonuses.get(accessory, 0)

def update_quest_progress(user_id, quest_type, amount=1):
    """Обновляет прогресс ежедневного задания"""
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT quest_id FROM daily_quests WHERE user_id = ? AND quest_type = ? AND date = ? AND claimed = 0", (user_id, quest_type, today))
    row = c.fetchone()
    if row:
        quest_id = row
        c.execute("UPDATE daily_quests SET quest_progress = quest_progress + ? WHERE quest_id = ?", (amount, quest_id))
        conn.commit()
    conn.close()

# ==================== ПРЕДМЕТЫ МАГАЗИНА ====================

SHOP_ITEMS = {
    "Апельсин 🍊": {"price": 15, "type": "food", "satiety": 25, "mood": 10},
    "Рыба 🐟": {"price": 10, "type": "food", "satiety": 20, "mood": 5},
    "Кальмар 🦑": {"price": 25, "type": "food", "satiety": 35, "mood": 15},
    "Мороженое 🍦": {"price": 20, "type": "food", "satiety": 15, "mood": 30},
    "Меч ⚔️": {"price": 100, "type": "weapon"},
    "Щит 🛡️": {"price": 100, "type": "shield"},
    "Шлем 🪖": {"price": 60, "type": "helmet"},
    "Броня 👕": {"price": 150, "type": "armor"},
    "Бантик 🎀": {"price": 40, "type": "accessory"},
    "Шарф 🧣": {"price": 35, "type": "accessory"},
    "Корона 👑": {"price": 200, "type": "accessory"},
    "Очки 🕶️": {"price": 50, "type": "accessory"},
    "Цветок 🌸": {"price": 25, "type": "accessory"},
}

# ==================== РАБОТЫ ====================

JOBS = [
    {"name": "Рыболов 🎣", "desc": "Ловить рыбу", "reward_min": 20, "reward_max": 50, "cooldown_min": 30, "mood_cost": 5, "satiety_cost": 10},
    {"name": "Почтальон 📬", "desc": "Разносить почту", "reward_min": 30, "reward_max": 60, "cooldown_min": 45, "mood_cost": 8, "satiety_cost": 15},
    {"name": "Укротитель 🦭", "desc": "Укрощать морских зверей", "reward_min": 50, "reward_max": 100, "cooldown_min": 60, "mood_cost": 12, "satiety_cost": 20},
    {"name": "Водолаз 🤿", "desc": "Исследовать глубины", "reward_min": 40, "reward_max": 80, "cooldown_min": 50, "mood_cost": 10, "satiety_cost": 18},
    {"name": "Актёр 🎭", "desc": "Выступать в шоу", "reward_min": 35, "reward_max": 70, "cooldown_min": 40, "mood_cost": 6, "satiety_cost": 12},
]

PLAY_COOLDOWN_MIN = 15  # кулдаун на игру — 15 минут

# ==================== ОБРАБОТЧИКИ ====================

def show_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🦭 Мой тюлень"), types.KeyboardButton("👤 Профиль"))
    markup.add(types.KeyboardButton("🛒 Магазин"), types.KeyboardButton("⚔️ Бой"))
    markup.add(types.KeyboardButton("🏰 Подземелье"), types.KeyboardButton("💼 Работа"))
    markup.add(types.KeyboardButton("💍 Брак"), types.KeyboardButton("📋 Задания"))
    bot.send_message(user_id, "Выберите действие:", reply_markup=markup)

@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name

    player = get_player(user_id)
    if not player:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO players (user_id, username, display_name, fishnets) VALUES (?, ?, ?, 100)", (user_id, username, username))
        conn.commit()
        conn.close()

        seal_name = random.choice(["Никифор", "Плюха", "Шлёпа", "Бубль", "Тюня", "Фрэнк", "Сэм"])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO seals (owner_id, name, health, max_health, mood, satiety, strength, defense, level, exp) VALUES (?, ?, 100, 100, 80, 80, 10, 5, 1, 0)", (user_id, seal_name))
        conn.commit()
        conn.close()

        bot.send_message(user_id, f"Добро пожаловать в Мир Тюленей! 🦭\n\nВам выдали тюленя по имени {seal_name} и 100 рыбнеток 🐟.\nИспользуйте кнопки меню для игры!")
    else:
        bot.send_message(user_id, "С возвращением! 🦭 Вы уже зарегистрированы.")
    show_main_menu(user_id)

@bot.message_handler(commands=['stats'])
def send_stats(message):
    user_id = message.from_user.id
    
    # Подключаемся к БД
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Считаем общее количество игроков
    c.execute("SELECT COUNT(*) FROM players")
    total_players = c.fetchone()
    
    # Считаем тюленей у этого пользователя
    c.execute("SELECT COUNT(*) FROM seals WHERE owner_id = ?", (user_id,))
    user_seals_count = c.fetchone()
    
    conn.close()
    
    # Формируем ответ
    response = (
        f"📊 Статистика игры:\n\n"
        f"Всего игроков: {total_players}\n"
        f"У тебя тюленей: {user_seals_count}"
    )
    
    bot.reply_to(message, response)

@bot.message_handler(commands=['help'])
def cmd_help(message):
    text = "🦭 **Справка по командам**\n\n"
    text += "**Основные:**\n"
    text += "  /start — главное меню\n"
    text += "  /help — эта справка\n"
    text += "  /profile — ваш профиль\n"
    text += "  /setphoto — установить фото профиля\n"
    text += "  /setname — изменить имя профиля\n\n"
    text += "**Тюлень:**\n"
    text += "  🦭 Мой тюлень — карточка тюленя (кормить, играть, экипировка)\n\n"
    text += "**Заработок:**\n"
    text += "  /shop — магазин (еда, оружие, аксессуары)\n"
    text += "  /work — отправить тюленя на работу\n"
    text += "  /battle — бой с боссом\n"
    text += "  /dungeon — подземелье (5 этажей)\n\n"
    text += "**Другое:**\n"
    text += "  /marry — брак тюленей\n"
    text += "  /quests — ежедневные задания\n\n"
    text += "**Кулдауны:**\n"
    text += "  🎾 Игра — 15 мин\n"
    text += "  💼 Работа — 30–60 мин (зависит от работы)\n\n"
    text += "**Аксессуары (бонус к настроению):**\n"
    text += "  🌸 Цветок (+5) — 🐟25\n"
    text += "  🧣 Шарф (+8) — 🐟35\n"
    text += "  🎀 Бантик (+10) — 🐟40\n"
    text += "  🕶️ Очки (+7) — 🐟50\n"
    text += "  👑 Корона (+20) — 🐟200"
    bot.send_message(message.from_user.id, text, parse_mode='Markdown')

@bot.message_handler(commands=['profile'])
def cmd_profile(message):
    user_id = message.from_user.id
    player = get_player(user_id)
    if not player:
        bot.send_message(user_id, "Вы не зарегистрированы. Напишите /start")
        return

    display_name = player or "Не указано"
    fishnets = player
    seals = get_player_seals(user_id)

    text = f"👤 **Ваш профиль**\n\n"
    text += f"Имя: {display_name}\n"
    text += f"Рыбнетки: 🐟 {fishnets}\n"
    text += f"Тюленей: {len(seals)}\n\n"
    text += "🦭 Ваши тюлени:\n"
    for s in seals:
        baby = " 🍼 (тюленёнок)" if s == 1 else ""
        text += f"  • {s} — ур.{s}{baby}\n"

    if player and os.path.exists(player):
        with open(player, 'rb') as f:
            bot.send_photo(user_id, f, text, parse_mode='Markdown')
    else:
        bot.send_message(user_id, text, parse_mode='Markdown')

@bot.message_handler(commands=['setphoto'])
def cmd_setphoto(message):
    bot.send_message(message.from_user.id, "Отправьте фото для вашего профиля:")
    bot.register_next_step_handler(message, process_photo)

def process_photo(message):
    user_id = message.from_user.id
    if not message.photo:
        bot.send_message(user_id, "Это не фото! Попробуйте ещё раз: /setphoto")
        return

    file_id = message.photo[-1].file_id
    file_info = bot.get_file(file_id)
    downloaded = bot.download_file(file_info.file_path)

    os.makedirs("photos", exist_ok=True)
    path = f"photos/{user_id}.jpg"
    with open(path, 'wb') as f:
        f.write(downloaded)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE players SET photo_path = ? WHERE user_id = ?", (path, user_id))
    conn.commit()
    conn.close()

    bot.send_message(user_id, "✅ Фото профиля обновлено!")

@bot.message_handler(commands=['setname'])
def cmd_setname(message):
    bot.send_message(message.from_user.id, "Введите новое имя для профиля:")
    bot.register_next_step_handler(message, process_setname)

def process_setname(message):
    user_id = message.from_user.id
    new_name = message.text.strip()
    if len(new_name) > 30:
        bot.send_message(user_id, "Имя слишком длинное (макс 30 символов).")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE players SET display_name = ? WHERE user_id = ?", (new_name, user_id))
    conn.commit()
    conn.close()

    bot.send_message(user_id, f"✅ Имя изменено на: {new_name}")

@bot.message_handler(func=lambda message: any(word in message.text.lower() for word in ["похлопай по животику", "шлёпни по пузику", "дай пять животику", "погладь животик", "похлопай по пузику"]))
def belly_slap_text(message):
    phrases = [
        "🦭 Тюлень радостно хлопает себя по животику! Плюх-плюх! 😄",
        "🦭 *шлёп-шлёп* Так приятно! Ещё? 😊",
        "🦭 Хлоп-хлоп! У тюленя отличное настроение! 🎉",
        "🦭 *плюх* Какой мягкий животик! Спасибо! 🤗"
    ]
    response = random.choice(phrases)
    bot.reply_to(message, response)

# ==================== ТЮЛЕНЬ ====================

@bot.message_handler(func=lambda m: m.text == "🦭 Мой тюлень")
def menu_seal(message):
    user_id = message.from_user.id
    seals = get_player_seals(user_id)
    if not seals:
        bot.send_message(user_id, "У вас нет тюленей! Напишите /start")
        return

    markup = types.InlineKeyboardMarkup()
    for s in seals:
        baby = " 🍼" if s == 1 else ""
        markup.add(types.InlineKeyboardButton(f"{s} (ур.{s}){baby}", callback_data=f"sealinfo_{s}"))
    bot.send_message(user_id, "Выберите тюленя:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sealinfo_"))
def seal_selected(call, seal_id=None):
    if seal_id is None:
        seal_id = int(call.data.split("_"))
    seal = get_seal(seal_id)
    if not seal:
        bot.answer_callback_query(call.id, "Тюлень не найден!")
        return

    eff_str, eff_def, eff_hp = get_effective_stats(seal_id)
    mood_bonus = get_mood_bonus(seal_id)

    text = f"🦭 **{seal}**\n\n"
    text += f"Уровень: {seal} (опыт: {seal}/{exp_for_level(seal)})\n"
    text += f"❤️ Здоровье: {seal}/{seal}\n"
    text += f"😊 Настроение: {seal}"
    if mood_bonus > 0:
        text += f" (+{mood_bonus} от аксессуара)"
    text += f"\n"
    text += f"🍖 Сытость: {seal}\n"
    text += f"💪 Сила: {seal} (с экипировкой: {eff_str})\n"
    text += f"🛡️ Защита: {seal} (с экипировкой: {eff_def})\n"

    equipped = []
    if seal: equipped.append(f"⚔️ {seal}")
    if seal: equipped.append(f"🛡️ {seal}")
    if seal: equipped.append(f"🪖 {seal}")
    if seal: equipped.append(f"👕 {seal}")
    if seal: equipped.append(f"🎀 {seal}")
    text += f"\nЭкипировка: {', '.join(equipped) if equipped else 'нет'}\n"

    if seal == 1:
        text += "\n🍼 Это тюленёнок! Он вырастет через несколько дней.\n"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🍖 Покормить", callback_data=f"feed_{seal_id}"))
    markup.add(types.InlineKeyboardButton("🎾 Поиграть", callback_data=f"play_{seal_id}"))
    markup.add(types.InlineKeyboardButton("👕 Экипировка", callback_data=f"equip_{seal_id}"))
    markup.add(types.InlineKeyboardButton("✏️ Переименовать", callback_data=f"rename_{seal_id}"))
    markup.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back_main"))

    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("feed_"))
def seal_feed(call):
    user_id = call.from_user.id
    seal_id = int(call.data.split("_"))
    seal = get_seal(seal_id)
    if not seal:
        return

    inv = get_inventory(user_id)
    food_items = [i for i in inv if i == "food"]

    if not food_items:
        bot.answer_callback_query(call.id, "У вас нет еды! Купите в магазине.")
        return

    markup = types.InlineKeyboardMarkup()
    for item in food_items:
        name = item
        qty = item
        info = SHOP_ITEMS.get(name, {})
        markup.add(types.InlineKeyboardButton(f"{name} (x{qty}) — сытость +{info.get('satiety', 0)}", callback_data=f"do_feed_{seal_id}_{item}"))
    markup.add(types.InlineKeyboardButton("◀️ Назад", callback_data=f"sealinfo_{seal_id}"))

    bot.edit_message_text("Чем покормить?", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("do_feed_"))
def seal_do_feed(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    seal_id = int(parts)
    item_name = "_".join(parts[3:])

    info = SHOP_ITEMS.get(item_name)
    if not info:
        bot.answer_callback_query(call.id, "Предмет не найден!")
        return

    seal = get_seal(seal_id)
    if not seal:
        return

    new_satiety = min(100, seal + info["satiety"])
    new_mood = min(100, seal + info.get("mood", 5))
    update_seal(seal_id, satiety=new_satiety, mood=new_mood)
    remove_from_inventory(user_id, item_name)

    bot.answer_callback_query(call.id, f"{seal} съел {item_name}! Сытость +{info['satiety']}, настроение +{info.get('mood', 5)}")

    update_quest_progress(user_id, "feed", 1)
    seal_selected(call, seal_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("play_"))
def seal_play(call):
    user_id = call.from_user.id
    seal_id = int(call.data.split("_"))
    seal = get_seal(seal_id)
    if not seal:
        return

    if seal < 10:
        bot.answer_callback_query(call.id, "Тюлень слишком голоден для игры!")
        return

    # Проверка кулдауна на игру
    play_cd = seal
    if play_cd:
        try:
            cd_time = datetime.fromisoformat(play_cd)
            elapsed = datetime.now() - cd_time
            remaining = timedelta(minutes=PLAY_COOLDOWN_MIN) - elapsed
            if remaining.total_seconds() > 0:
                mins = int(remaining.total_seconds() // 60)
                secs = int(remaining.total_seconds() % 60)
                bot.answer_callback_query(call.id, f"⏳ Ещё отдыхает! Подождите {mins}м {secs}с")
                return
        except:
            pass

    new_mood = min(100, seal + 25)
    new_satiety = max(0, seal - 5)
    exp_gain = random.randint(5, 15)
    new_exp = seal + exp_gain
    new_play_cd = datetime.now().isoformat()
    update_seal(seal_id, mood=new_mood, satiety=new_satiety, exp=new_exp, play_cooldown=new_play_cd)

    leveled = check_levelup(seal_id)

    update_quest_progress(user_id, "play", 1)

    msg = f"🎾 Вы поиграли с {seal}!\nНастроение +25, сытость -5, опыт +{exp_gain}\n⏳ Следующая игра через {PLAY_COOLDOWN_MIN} мин"
    if leveled:
        msg += f"\n🎉 {seal} достиг уровня {leveled}!"

    bot.answer_callback_query(call.id, msg)
    seal_selected(call, seal_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rename_"))
def seal_rename(call):
    seal_id = int(call.data.split("_"))
    bot.send_message(call.from_user.id, "Введите новое имя для тюленя:")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, lambda m: process_seal_rename(m, seal_id))

def process_seal_rename(message, seal_id):
    new_name = message.text.strip()
    if len(new_name) > 20:
        bot.send_message(message.from_user.id, "Имя слишком длинное (макс 20 символов).")
        return
    update_seal(seal_id, name=new_name)
    bot.send_message(message.from_user.id, f"✅ Тюлень переименован в {new_name}!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("equip_"))
def seal_equip_menu(call):
    user_id = call.from_user.id
    seal_id = int(call.data.split("_"))
    inv = get_inventory(user_id)
    gear_items = [i for i in inv if i in ("weapon", "armor", "helmet", "shield", "accessory")]

    if not gear_items:
        bot.answer_callback_query(call.id, "У вас нет экипировки!")
        return

    markup = types.InlineKeyboardMarkup()
    for item in gear_items:
        markup.add(types.InlineKeyboardButton(f"{item} (x{item})", callback_data=f"do_equip_{seal_id}_{item}"))
    markup.add(types.InlineKeyboardButton("◀️ Назад", callback_data=f"sealinfo_{seal_id}"))

    bot.edit_message_text("Что надеть?", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("do_equip_"))
def seal_do_equip(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    seal_id = int(parts)
    item_name = "_".join(parts[3:])

    info = SHOP_ITEMS.get(item_name)
    if not info:
        bot.answer_callback_query(call.id, "Предмет не найден!")
        return

    seal = get_seal(seal_id)
    if not seal:
        return

    slot_map = {
        "weapon": "equipped_weapon",
        "armor": "equipped_armor",
        "helmet": "equipped_helmet",
        "shield": "equipped_shield",
        "accessory": "equipped_accessory",
    }
    slot = slot_map.get(info["type"])

    if not slot:
        bot.answer_callback_query(call.id, "Неизвестный тип предмета!")
        return

    col_idx = {
        "equipped_weapon": 13,
        "equipped_armor": 14,
        "equipped_helmet": 15,
        "equipped_shield": 16,
        "equipped_accessory": 17,
    }.get(slot)
    current_val = seal[col_idx] if col_idx is not None else None

    if current_val:
        old_type = SHOP_ITEMS.get(current_val, {}).get("type", "armor")
        add_to_inventory(user_id, current_val, old_type, 1)

    update_seal(seal_id, **{slot: item_name})
    remove_from_inventory(user_id, item_name)

    bot.answer_callback_query(call.id, f"Надето: {item_name}")
    seal_selected(call, seal_id)

@bot.callback_query_handler(func=lambda c: c.data == "back_main")
def back_to_main(call):
    show_main_menu(call.from_user.id)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

# ==================== МАГАЗИН ====================

@bot.message_handler(func=lambda m: m.text == "🛒 Магазин" or m.text == "/shop")
def menu_shop(message):
    user_id = message.from_user.id
    fishnets = get_fishnets(user_id)
    text = f"🛒 **Магазин**\nУ вас: 🐟 {fishnets}\n\n"

    markup = types.InlineKeyboardMarkup(row_width=1)
    for name, info in SHOP_ITEMS.items():
        if info["type"] == "food":
            text += f"  {name} — 🐟{info['price']} (сытость +{info['satiety']}, настроение +{info.get('mood', 0)})\n"
        elif info["type"] == "accessory":
            bonus = {"Бантик 🎀": 10, "Шарф 🧣": 8, "Корона 👑": 20, "Очки 🕶️": 7, "Цветок 🌸": 5}.get(name, 0)
            text += f"  {name} — 🐟{info['price']} (аксессуар, настроение +{bonus})\n"
        else:
            text += f"  {name} — 🐟{info['price']}\n"
        markup.add(types.InlineKeyboardButton(f"Купить {name} — 🐟{info['price']}", callback_data=f"buy_{name}"))

    bot.send_message(user_id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_"))
def shop_buy(call):
    user_id = call.from_user.id
    item_name = call.data[4:]
    info = SHOP_ITEMS.get(item_name)
    if not info:
        bot.answer_callback_query(call.id, "Предмет не найден!")
        return

    fishnets = get_fishnets(user_id)
    if fishnets < info["price"]:
        bot.answer_callback_query(call.id, "Недостаточно рыбнеток!")
        return

    add_fishnets(user_id, -info["price"])
    add_to_inventory(user_id, item_name, info["type"])

    # Обновляем прогресс квеста (если функция существует, иначе закомментируйте строку ниже)
    # update_quest_progress(user_id, "shop", 1)

    bot.answer_callback_query(call.id, f"Куплено: {item_name}!")


# ==================== РАБОТА ====================

@bot.message_handler(func=lambda m: m.text == "💼 Работа" or m.text == "/work")
def menu_work(message):
    user_id = message.from_user.id
    seals = get_player_seals(user_id)
    if not seals:
        bot.send_message(user_id, "У вас нет тюленей!")
        return

    markup = types.InlineKeyboardMarkup()
    for s in seals:
        if s == 1:  # Пропускаем малышей
            continue
        markup.add(types.InlineKeyboardButton(f"{s} (ур.{s})", callback_data=f"worksel_{s}"))

    if not markup.keyboard:
        bot.send_message(user_id, "Все ваши тюлени — малыши, они не могут работать!")
        return

    bot.send_message(user_id, "💼 Выберите тюленя для работы:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("worksel_"))
def work_select_job(call):
    seal_id = int(call.data.split("_"))
    seal = get_seal(seal_id)
    if not seal:
        return

    if seal < 20:
        bot.answer_callback_query(call.id, "Тюлень слишком голоден для работы! Сытость < 20.")
        return

    # Проверка кулдауна
    work_cd = seal
    if work_cd:
        try:
            cd_time = datetime.fromisoformat(work_cd)
            elapsed = datetime.now() - cd_time
            min_cd = min(j["cooldown_min"] for j in JOBS)
            remaining = timedelta(minutes=min_cd) - elapsed
            if remaining.total_seconds() > 0:
                mins = int(remaining.total_seconds() // 60)
                secs = int(remaining.total_seconds() % 60)
                bot.answer_callback_query(call.id, f"⏳ Тюлень устал! Подождите {mins}м {secs}с")
                return
        except Exception:
            pass

    markup = types.InlineKeyboardMarkup(row_width=1)
    for job in JOBS:
        markup.add(types.InlineKeyboardButton(f"{job['name']} — {job['reward_min']}-{job['reward_max']} 🐟", callback_data=f"do_work_{seal_id}_{job['name']}"))
    
    bot.edit_message_text(f"💼 Выберите работу для {seal}:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("do_work_"))
def do_work(call):
    parts = call.data.split("_", 3)
    if len(parts) < 4:
        bot.answer_callback_query(call.id, "Ошибка данных.")
        return
    
    seal_id = int(parts)
    job_name = parts
    
    # Находим работу по имени
    job = next((j for j in JOBS if j["name"] == job_name), None)
    if not job:
        bot.answer_callback_query(call.id, "Работа не найдена.")
        return

    seal = get_seal(seal_id)
    if not seal:
        return

    # Расчет награды
    reward = random.randint(job["reward_min"], job["reward_max"])
    
    # Обновление статусов
    new_satiety = max(0, seal - job["satiety_cost"])
    new_mood = max(0, seal - job["mood_cost"])
    
    # Установка кулдауна (берем минимальное время работы для простоты, можно усложнить)
    new_work_cd = (datetime.now() + timedelta(minutes=job["cooldown_min"])).isoformat()
    
    update_seal(seal_id, satiety=new_satiety, mood=new_mood, work_cooldown=new_work_cd)
    add_fishnets(seal, reward) # seal это owner_id

    msg = f"💼 {seal} поработал как {job_name}!\nПолучил: 🐟{reward}\nСытость: -{job['satiety_cost']}, Настроение: -{job['mood_cost']}"
    
    # update_quest_progress(seal, "work", 1) # Раскомментировать при наличии функции
    
    bot.answer_callback_query(call.id, msg)
    seal_selected(call, seal_id)


# ==================== ПОДЗЕМЕЛЬЕ ====================

@bot.message_handler(func=lambda m: m.text == "🏰 Подземелье" or m.text == "/dungeon")
def menu_dungeon(message):
    user_id = message.from_user.id
    seals = get_player_seals(user_id)
    if not seals:
        bot.send_message(user_id, "У вас нет тюленей!")
        return

    # Проверка, есть ли активный забег
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM dungeon_runs WHERE user_id = ? AND active = 1", (user_id,))
    active_run = c.fetchone()
    conn.close()

    if active_run:
        bot.send_message(user_id, f"⚔️ Вы уже в подземелье! Этаж: {active_run}")
        return

    markup = types.InlineKeyboardMarkup()
    for s in seals:
        if s == 1: continue
        markup.add(types.InlineKeyboardButton(f"{s} (ур.{s})", callback_data=f"dung_start_{s}"))
    
    if not markup.keyboard:
        bot.send_message(user_id, "Нет взрослых тюленей для похода в подземелье.")
        return

    bot.send_message(user_id, "🏰 Выберите тюленя для похода в подземелье:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dung_start_"))
def start_dungeon(call):
    seal_id = int(call.data.split("_"))
    user_id = call.from_user.id
    
    # Создаем забег
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO dungeon_runs (user_id, seal_id, current_floor, active) VALUES (?, ?, 1, 1)", (user_id, seal_id))
    conn.commit()
    conn.close()
    
    bot.answer_callback_query(call.id, "🏰 Вы вошли в подземелье! Начинаем с 1 этажа.")
    enter_dungeon_floor(call, seal_id, 1)

def enter_dungeon_floor(call, seal_id, floor):
    # Логика боя на этаже (упрощенная)
    seal = get_seal(seal_id)
    eff_str, eff_def, eff_hp = get_effective_stats(seal_id)
    
    # Случайный враг
    enemy_hp = floor * 50 + random.randint(10, 30)
    enemy_dmg = floor * 5 + random.randint(2, 5)
    
    # Имитация боя
    # В реальном проекте здесь нужна асинхронность или пошаговая механика
    damage_dealt = max(1, eff_str - (enemy_dmg // 2))
    damage_taken = max(1, enemy_dmg - (eff_def // 2))
    
    # Упрощенный расчет: если сила тюленя больше, он побеждает сразу
    if eff_str * 2 > enemy_hp:
        # Победа
        reward = floor * 10 + random.randint(5, 15)
        exp_gain = floor * 5
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Обновляем тюленя
        new_exp = seal + exp_gain
        update_seal(seal_id, exp=new_exp)
        check_levelup(seal_id)
        
        # Обновляем забег
        c.execute("UPDATE dungeon_runs SET current_floor = current_floor + 1 WHERE user_id = ? AND seal_id = ? AND active = 1", (call.from_user.id, seal_id))
        new_floor = floor + 1
        
        conn.commit()
        conn.close()
        
        msg = f"⚔️ Победа на этаже {floor}!\nНанесено урона: {damage_dealt}\nПолучено: 🐟{reward}, Опыт: +{exp_gain}\nСледующий этаж: {new_floor}"
        bot.answer_callback_query(call.id, msg)
        
        # Автоматически переходим на следующий этаж (или кнопка)
        # Для простоты пока просто показываем кнопку
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Вперед на этаж " + str(new_floor), callback_data=f"dung_floor_{seal_id}_{new_floor}"))
        markup.add(types.InlineKeyboardButton("Выйти из подземелья", callback_data=f"dung_exit_{seal_id}"))
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup)
    else:
        # Поражение
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE dungeon_runs SET active = 0 WHERE user_id = ? AND seal_id = ? AND active = 1", (call.from_user.id, seal_id))
        conn.commit()
        conn.close()
        
        bot.answer_callback_query(call.id, f"💀 Тюлень {seal} пал на этаже {floor}... Слишком слабый.")
        show_main_menu(call.from_user.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dung_floor_"))
def next_floor(call):
    parts = call.data.split("_")
    seal_id = int(parts)
    floor = int(parts)
    enter_dungeon_floor(call, seal_id, floor)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dung_exit_"))
def exit_dungeon(call):
    seal_id = int(call.data.split("_"))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE dungeon_runs SET active = 0 WHERE seal_id = ? AND active = 1", (seal_id,))
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, "🚪 Вы вышли из подземелья.")
    show_main_menu(call.from_user.id)


# ==================== БРАК И ДЕТИ ====================

@bot.message_handler(func=lambda m: m.text == "💍 Брак" or m.text == "/marry")
def menu_marry(message):
    bot.send_message(message.from_user.id, "Функция брака находится в разработке! Тюлени пока слишком застенчивы.")

# ==================== КВЕСТЫ ====================

@bot.message_handler(func=lambda m: m.text == "📋 Задания" or m.text == "/quests")
def menu_quests(message):
    user_id = message.from_user.id
    # Заглушка, так как функция update_quest_progress не была определена в исходном коде
    bot.send_message(user_id, "Ежедневные задания: пока не реализованы в этом фрагменте.")


# ==================== ГЛАВНЫЙ ЦИКЛ ====================

if __name__ == "__main__":
    print("Бот запускается...")
    bot.polling(none_stop=True, interval=0)


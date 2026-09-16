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
    cols = [row[1] for row in c.fetchall()]
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
# Индексы таблицы seals:
# 0=seal_id, 1=owner_id, 2=name, 3=health, 4=max_health,
# 5=mood, 6=satiety, 7=strength, 8=defense, 9=level,
# 10=exp, 11=is_baby, 12=born_at,
# 13=equipped_weapon, 14=equipped_armor, 15=equipped_helmet, 16=equipped_shield,
# 17=equipped_accessory, 18=work_cooldown, 19=play_cooldown

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
    return row[0] if row else 0

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
        new_qty = row[0] - qty
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
    level = seal[9]
    exp = seal[10]
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
            strength=seal[7] + str_bonus,
            defense=seal[8] + def_bonus,
            max_health=seal[4] + hp_bonus,
            health=seal[4] + hp_bonus
        )
        return new_level
    return False

def get_effective_stats(seal_id):
    seal = get_seal(seal_id)
    if not seal:
        return 0, 0, 0
    base_str = seal[7]
    base_def = seal[8]
    base_hp = seal[4]

    item_bonuses = {
        "Меч ⚔️": {"str": 5},
        "Щит 🛡️": {"def": 5},
        "Шлем 🪖": {"def": 3, "hp": 10},
        "Броня 👕": {"def": 7, "hp": 20},
    }

    str_bonus = 0
    def_bonus = 0
    hp_bonus = 0

    for slot in [seal[13], seal[14], seal[15], seal[16]]:
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
    accessory = seal[17]
    accessory_bonuses = {
        "Бантик 🎀": 10,
        "Шарф 🧣": 8,
        "Корона 👑": 20,
        "Очки 🕶️": 7,
        "Цветок 🌸": 5,
    }
    return accessory_bonuses.get(accessory, 0)

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
        @bot.message_handler(commands=['stats'])
       @bot.message_handler(func=lambda message: any(word in message.text.lower() for word in ["похлопай по животику", "шлёпни по пузику", "дай пять животику", "погладь животик", "похлопай по пузику"]))
def belly_slap_text(message):
    phrases = [
        "🦭 Тюлень радостно хлопает себя по животику! Плюх-плюх! 😄",
        "🦭 *шлёп-шлёп* Так приятно! Ещё? 😊",
        "🦭 Хлоп-хлоп! У тюленя отличное настроение! 🎉",
        "🦭 *плюх* Какой мягкий животик! Спасибо! 🤗"
    ]
    
    import random
    response = random.choice(phrases)
    
    bot.reply_to(message, response)

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

    show_main_menu(user_id)

def show_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🦭 Мой тюлень"), types.KeyboardButton("👤 Профиль"))
    markup.add(types.KeyboardButton("🛒 Магазин"), types.KeyboardButton("⚔️ Бой"))
    markup.add(types.KeyboardButton("🏰 Подземелье"), types.KeyboardButton("💼 Работа"))
    markup.add(types.KeyboardButton("💍 Брак"), types.KeyboardButton("📋 Задания"))
    bot.send_message(user_id, "Выберите действие:", reply_markup=markup)

@bot.message_handler(commands=['profile'])
def cmd_profile(message):
    user_id = message.from_user.id
    player = get_player(user_id)
    if not player:
        bot.send_message(user_id, "Вы не зарегистрированы. Напишите /start")
        return

    display_name = player[2] or "Не указано"
    fishnets = player[4]
    seals = get_player_seals(user_id)

    text = f"👤 **Ваш профиль**\n\n"
    text += f"Имя: {display_name}\n"
    text += f"Рыбнетки: 🐟 {fishnets}\n"
    text += f"Тюленей: {len(seals)}\n\n"
    text += "🦭 Ваши тюлени:\n"
    for s in seals:
        baby = " 🍼 (тюленёнок)" if s[11] == 1 else ""
        text += f"  • {s[2]} — ур.{s[9]}{baby}\n"

    if player[3] and os.path.exists(player[3]):
        with open(player[3], 'rb') as f:
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
        baby = " 🍼" if s[11] == 1 else ""
        markup.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]}){baby}", callback_data=f"sealinfo_{s[0]}"))
    bot.send_message(user_id, "Выберите тюленя:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sealinfo_"))
def seal_selected(call, seal_id=None):
    if seal_id is None:
        seal_id = int(call.data.split("_")[1])
    seal = get_seal(seal_id)
    if not seal:
        bot.answer_callback_query(call.id, "Тюлень не найден!")
        return

    eff_str, eff_def, eff_hp = get_effective_stats(seal_id)
    mood_bonus = get_mood_bonus(seal_id)

    text = f"🦭 **{seal[2]}**\n\n"
    text += f"Уровень: {seal[9]} (опыт: {seal[10]}/{exp_for_level(seal[9])})\n"
    text += f"❤️ Здоровье: {seal[3]}/{seal[4]}\n"
    text += f"😊 Настроение: {seal[5]}"
    if mood_bonus > 0:
        text += f" (+{mood_bonus} от аксессуара)"
    text += f"\n"
    text += f"🍖 Сытость: {seal[6]}\n"
    text += f"💪 Сила: {seal[7]} (с экипировкой: {eff_str})\n"
    text += f"🛡️ Защита: {seal[8]} (с экипировкой: {eff_def})\n"

    equipped = []
    if seal[13]: equipped.append(f"⚔️ {seal[13]}")
    if seal[14]: equipped.append(f"🛡️ {seal[14]}")
    if seal[15]: equipped.append(f"🪖 {seal[15]}")
    if seal[16]: equipped.append(f"👕 {seal[16]}")
    if seal[17]: equipped.append(f"🎀 {seal[17]}")
    text += f"\nЭкипировка: {', '.join(equipped) if equipped else 'нет'}\n"

    if seal[11] == 1:
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
    seal_id = int(call.data.split("_")[1])
    seal = get_seal(seal_id)
    if not seal:
        return

    inv = get_inventory(user_id)
    food_items = [i for i in inv if i[3] == "food"]

    if not food_items:
        bot.answer_callback_query(call.id, "У вас нет еды! Купите в магазине.")
        return

    markup = types.InlineKeyboardMarkup()
    for item in food_items:
        name = item[2]
        qty = item[4]
        info = SHOP_ITEMS.get(name, {})
        markup.add(types.InlineKeyboardButton(f"{name} (x{qty}) — сытость +{info.get('satiety', 0)}", callback_data=f"do_feed_{seal_id}_{item[2]}"))
    markup.add(types.InlineKeyboardButton("◀️ Назад", callback_data=f"sealinfo_{seal_id}"))

    bot.edit_message_text("Чем покормить?", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("do_feed_"))
def seal_do_feed(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    seal_id = int(parts[2])
    item_name = "_".join(parts[3:])

    info = SHOP_ITEMS.get(item_name)
    if not info:
        bot.answer_callback_query(call.id, "Предмет не найден!")
        return

    seal = get_seal(seal_id)
    if not seal:
        return

    new_satiety = min(100, seal[6] + info["satiety"])
    new_mood = min(100, seal[5] + info.get("mood", 5))
    update_seal(seal_id, satiety=new_satiety, mood=new_mood)
    remove_from_inventory(user_id, item_name)

    bot.answer_callback_query(call.id, f"{seal[2]} съел {item_name}! Сытость +{info['satiety']}, настроение +{info.get('mood', 5)}")

    update_quest_progress(user_id, "feed", 1)
    seal_selected(call, seal_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("play_"))
def seal_play(call):
    user_id = call.from_user.id
    seal_id = int(call.data.split("_")[1])
    seal = get_seal(seal_id)
    if not seal:
        return

    if seal[6] < 10:
        bot.answer_callback_query(call.id, "Тюлень слишком голоден для игры!")
        return

    # Проверка кулдауна на игру
    play_cd = seal[19]
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

    new_mood = min(100, seal[5] + 25)
    new_satiety = max(0, seal[6] - 5)
    exp_gain = random.randint(5, 15)
    new_exp = seal[10] + exp_gain
    new_play_cd = datetime.now().isoformat()
    update_seal(seal_id, mood=new_mood, satiety=new_satiety, exp=new_exp, play_cooldown=new_play_cd)

    leveled = check_levelup(seal_id)

    update_quest_progress(user_id, "play", 1)

    msg = f"🎾 Вы поиграли с {seal[2]}!\nНастроение +25, сытость -5, опыт +{exp_gain}\n⏳ Следующая игра через {PLAY_COOLDOWN_MIN} мин"
    if leveled:
        msg += f"\n🎉 {seal[2]} достиг уровня {leveled}!"

    bot.answer_callback_query(call.id, msg)
    seal_selected(call, seal_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rename_"))
def seal_rename(call):
    seal_id = int(call.data.split("_")[1])
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
    seal_id = int(call.data.split("_")[1])
    inv = get_inventory(user_id)
    gear_items = [i for i in inv if i[3] in ("weapon", "armor", "helmet", "shield", "accessory")]

    if not gear_items:
        bot.answer_callback_query(call.id, "У вас нет экипировки!")
        return

    markup = types.InlineKeyboardMarkup()
    for item in gear_items:
        markup.add(types.InlineKeyboardButton(f"{item[2]} (x{item[4]})", callback_data=f"do_equip_{seal_id}_{item[2]}"))
    markup.add(types.InlineKeyboardButton("◀️ Назад", callback_data=f"sealinfo_{seal_id}"))

    bot.edit_message_text("Что надеть?", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("do_equip_"))
def seal_do_equip(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    seal_id = int(parts[2])
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

    update_quest_progress(user_id, "shop", 1)

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
        if s[11] == 1:
            continue
        markup.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"worksel_{s[0]}"))

    if not markup.keyboard:
        bot.send_message(user_id, "Все ваши тюлени — малыши, они не могут работать!")
        return

    bot.send_message(user_id, "💼 Выберите тюленя для работы:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("worksel_"))
def work_select_job(call):
    seal_id = int(call.data.split("_")[1])
    seal = get_seal(seal_id)
    if not seal:
        return

    if seal[6] < 20:
        bot.answer_callback_query(call.id, "Тюлень слишком голоден для работы! Сытость < 20.")
        return

    # Проверка кулдауна
    work_cd = seal[18]
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
        except:
            pass

    text = f"💼 Выберите работу для {seal[2]}:\n\n"
    for i, job in enumerate(JOBS):
        text += f"{i+1}. {job['name']} — {job['desc']}\n"
        text += f"   Награда: 🐟{job['reward_min']}-{job['reward_max']}, кулдаун: {job['cooldown_min']} мин\n"
        text += f"   Настроение -{job['mood_cost']}, сытость -{job['satiety_cost']}\n\n"

    markup = types.InlineKeyboardMarkup()
    for i, job in enumerate(JOBS):
        markup.add(types.InlineKeyboardButton(f"{job['name']} — 🐟{job['reward_min']}-{job['reward_max']}", callback_data=f"workdo_{seal_id}_{i}"))
    markup.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back_main"))

    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("workdo_"))
def work_do(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    seal_id = int(parts[1])
    job_idx = int(parts[2])

    if job_idx < 0 or job_idx >= len(JOBS):
        bot.answer_callback_query(call.id, "Работа не найдена!")
        return

    job = JOBS[job_idx]
    seal = get_seal(seal_id)
    if not seal:
        return

    if seal[6] < 20:
        bot.answer_callback_query(call.id, "Тюлень слишком голоден! Покормите его.")
        return

    if seal[5] < 10:
        bot.answer_callback_query(call.id, "Настроение слишком низкое! Поиграйте с тюленем.")
        return

    # Проверка кулдауна
    work_cd = seal[18]
    if work_cd:
        try:
            cd_time = datetime.fromisoformat(work_cd)
            elapsed = datetime.now() - cd_time
            remaining = timedelta(minutes=job["cooldown_min"]) - elapsed
            if remaining.total_seconds() > 0:
                mins = int(remaining.total_seconds() // 60)
                secs = int(remaining.total_seconds() % 60)
                bot.answer_callback_query(call.id, f"⏳ Ещё не отдохнул! Подождите {mins}м {secs}с")
                return
        except:
            pass

    # Выполняем работу
    reward = random.randint(job["reward_min"], job["reward_max"])
    reward += seal[9] * 3  # бонус за уровень
    new_mood = max(0, seal[5] - job["mood_cost"])
    new_satiety = max(0, seal[6] - job["satiety_cost"])
    exp_gain = random.randint(10, 25)
    new_exp = seal[10] + exp_gain
    new_work_cd = datetime.now().isoformat()

    update_seal(seal_id, mood=new_mood, satiety=new_satiety, exp=new_exp, work_cooldown=new_work_cd)
    add_fishnets(user_id, reward)
    leveled = check_levelup(seal_id)

    log = f"💼 {seal[2]} поработал: {job['name']}\n"
    log += f"💰 Заработано: 🐟{reward}\n"
    log += f"📈 Опыт: +{exp_gain}\n"
    log += f"😊 Настроение: -{job['mood_cost']}\n"
    log += f"🍖 Сытость: -{job['satiety_cost']}\n"
    log += f"⏳ Кулдаун: {job['cooldown_min']} мин"
    if leveled:
        log += f"\n🎉 {seal[2]} достиг уровня {leveled}!"

    update_quest_progress(user_id, "work", 1)

    bot.edit_message_text(log, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

# ==================== БОИ ====================

@bot.message_handler(func=lambda m: m.text == "⚔️ Бой" or m.text == "/battle")
def menu_battle(message):
    user_id = message.from_user.id
    seals = get_player_seals(user_id)
    if not seals:
        bot.send_message(user_id, "У вас нет тюленей!")
        return

    markup = types.InlineKeyboardMarkup()
    for s in seals:
        if s[11] == 1:
            continue
        markup.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"battle_{s[0]}"))

    if not markup.keyboard:
        bot.send_message(user_id, "Все ваши тюлени — малыши, они не могут драться!")
        return

    bot.send_message(user_id, "Выберите тюленя для боя:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("battle_"))
def do_battle(call):
    user_id = call.from_user.id
    seal_id = int(call.data.split("_")[1])
    seal = get_seal(seal_id)
    if not seal:
        return

    if seal[3] <= 0:
        bot.answer_callback_query(call.id, "Тюлень слишком ранен!")
        return

    eff_str, eff_def, eff_hp = get_effective_stats(seal_id)

    boss_name = random.choice(["Краб-босс 🦀", "Акула 🦈", "Осьминог 🐙", "Морской ёжик 🦔"])
    boss_hp = random.randint(60, 100) + seal[9] * 10
    boss_str = random.randint(8, 15) + seal[9] * 2
    boss_def = random.randint(3, 8) + seal[9]

    log = [f"⚔️ **Бой: {seal[2]} против {boss_name}**\n"]
    log.append(f"{seal[2]}: ❤️{eff_hp} 💪{eff_str} 🛡️{eff_def}")
    log.append(f"{boss_name}: ❤️{boss_hp} 💪{boss_str} 🛡️{boss_def}\n")

    seal_hp = seal[3]
    round_num = 0

    while seal_hp > 0 and boss_hp > 0:
        round_num += 1
        if round_num > 20:
            log.append("Бой слишком затянулся! Ничья.")
            break

        dmg_to_boss = max(1, eff_str - boss_def + random.randint(-3, 5))
        boss_hp -= dmg_to_boss
        log.append(f"Раунд {round_num}: {seal[2]} наносит {dmg_to_boss} урона! (босс: {max(0, boss_hp)} ❤️)")

        if boss_hp <= 0:
            break

        dmg_to_seal = max(1, boss_str - eff_def + random.randint(-2, 4))
        seal_hp -= dmg_to_seal
        log.append(f"{boss_name} наносит {dmg_to_seal} урона! ({seal[2]}: {max(0, seal_hp)} ❤️)")

    if boss_hp <= 0:
        reward = random.randint(20, 50) + seal[9] * 5
        exp_gain = random.randint(20, 40)
        add_fishnets(user_id, reward)
        new_exp = seal[10] + exp_gain
        update_seal(seal_id, exp=new_exp, mood=min(100, seal[5] + 15))
        leveled = check_levelup(seal_id)

        log.append(f"\n🎉 **Победа!** Награда: 🐟{reward}, опыт +{exp_gain}")
        if leveled:
            log.append(f"📈 {seal[2]} достиг уровня {leveled}!")

        update_quest_progress(user_id, "battle", 1)
    elif seal_hp <= 0:
        update_seal(seal_id, health=max(1, seal[3] // 4), mood=max(0, seal[5] - 20))
        log.append(f"\n💀 **Поражение...** {seal[2]} ранен и расстроен.")
    else:
        log.append("\n🤝 Ничья!")

    bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown')

# ==================== ПОДЗЕМЕЛЬЕ ====================

DUNGEON_MONSTERS = [
    {"name": "Акула 🦈", "hp": 50, "str": 12, "def": 5},
    {"name": "Кракен 🐙", "hp": 80, "str": 18, "def": 8},
    {"name": "Лобстер 🦞", "hp": 40, "str": 10, "def": 10},
    {"name": "Кашалот 🐋", "hp": 120, "str": 20, "def": 12},
    {"name": "Фугу 🐡", "hp": 30, "str": 8, "def": 3},
]

@bot.message_handler(func=lambda m: m.text == "🏰 Подземелье" or m.text == "/dungeon")
def menu_dungeon(message):
    user_id = message.from_user.id
    seals = get_player_seals(user_id)
    if not seals:
        bot.send_message(user_id, "У вас нет тюленей!")
        return

    markup = types.InlineKeyboardMarkup()
    for s in seals:
        if s[11] == 1:
            continue
        markup.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"dngstart_{s[0]}"))

    if not markup.keyboard:
        bot.send_message(user_id, "Все ваши тюлени — малыши!")
        return

    bot.send_message(user_id, "🏰 Выберите тюленя для спуска в подземелье (5 этажей):", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dngstart_"))
def dungeon_start(call):
    user_id = call.from_user.id
    seal_id = int(call.data.split("_")[1])
    seal = get_seal(seal_id)
    if not seal:
        return

    if seal[3] <= 20:
        bot.answer_callback_query(call.id, "Тюлень слишком слаб для подземелья! Здоровье < 20.")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM dungeon_runs WHERE user_id = ?", (user_id,))
    c.execute("INSERT INTO dungeon_runs (user_id, seal_id, current_floor, active) VALUES (?, ?, 1, 1)", (user_id, seal_id))
    conn.commit()
    conn.close()

    dungeon_floor(call, seal_id, 1)

def dungeon_floor(call, seal_id, floor):
    seal = get_seal(seal_id)

    monster = random.choice(DUNGEON_MONSTERS).copy()
    monster["hp"] += floor * 15
    monster["str"] += floor * 3
    monster["def"] += floor * 2

    eff_str, eff_def, eff_hp = get_effective_stats(seal_id)

    text = f"🏰 **Подземелье — Этаж {floor}/5**\n\n"
    text += f"🦭 {seal[2]}: ❤️{seal[3]} 💪{eff_str} 🛡️{eff_def}\n"
    text += f"{monster['name']}: ❤️{monster['hp']} 💪{monster['str']} 🛡️{monster['def']}\n"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⚔️ Атаковать", callback_data=f"dng_atk_{seal_id}_{floor}"))
    markup.add(types.InlineKeyboardButton("🏃 Сбежать", callback_data=f"dng_flee_{seal_id}_{floor}"))

    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dng_atk_"))
def dungeon_attack(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    seal_id = int(parts[2])
    floor = int(parts[3])

    seal = get_seal(seal_id)
    if not seal:
        return

    monster = random.choice(DUNGEON_MONSTERS).copy()
    monster["hp"] += floor * 15
    monster["str"] += floor * 3
    monster["def"] += floor * 2

    eff_str, eff_def, eff_hp = get_effective_stats(seal_id)
    seal_hp = seal[3]

    log = [f"⚔️ Этаж {floor}: {seal[2]} vs {monster['name']}"]

    while seal_hp > 0 and monster["hp"] > 0:
        dmg = max(1, eff_str - monster["def"] + random.randint(-2, 5))
        monster["hp"] -= dmg
        log.append(f"{seal[2]} бьёт на {dmg}! (монстр: {max(0, monster['hp'])} ❤️)")
        if monster["hp"] <= 0:
            break
        dmg_m = max(1, monster["str"] - eff_def + random.randint(-1, 4))
        seal_hp -= dmg_m
        log.append(f"{monster['name']} бьёт на {dmg_m}! ({seal[2]}: {max(0, seal_hp)} ❤️)")

    if monster["hp"] <= 0:
        update_seal(seal_id, health=max(1, seal_hp))
        log.append(f"\n✅ Монстр повержен!")

        if floor >= 5:
            reward = 100 + floor * 30
            exp_gain = 50 + floor * 20
            add_fishnets(user_id, reward)
            s = get_seal(seal_id)
            update_seal(seal_id, exp=s[10] + exp_gain)
            leveled = check_levelup(seal_id)
            log.append(f"🏆 **Подземелье пройдено!** Награда: 🐟{reward}, опыт +{exp_gain}")
            if leveled:
                log.append(f"📈 Уровень {leveled}!")
            update_quest_progress(user_id, "dungeon", 1)

            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE dungeon_runs SET active = 0 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()

            bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        else:
            next_floor = floor + 1
            log.append(f"Открыт этаж {next_floor}!")

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("➡️ Дальше", callback_data=f"dng_next_{seal_id}_{next_floor}"))
            markup.add(types.InlineKeyboardButton("🏃 Выйти", callback_data=f"dng_flee_{seal_id}_{floor}"))

            bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

    elif seal_hp <= 0:
        update_seal(seal_id, health=1, mood=max(0, seal[5] - 30))
        log.append(f"\n💀 {seal[2]} повержен... Вы выброшены из подземелья.")

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE dungeon_runs SET active = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

        bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("dng_next_"))
def dungeon_next(call):
    parts = call.data.split("_")
    seal_id = int(parts[2])
    floor = int(parts[3])
    dungeon_floor(call, seal_id, floor)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dng_flee_"))
def dungeon_flee(call):
    user_id = call.from_user.id

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE dungeon_runs SET active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    bot.edit_message_text("🏃 Вы сбежали из подземелья.", call.message.chat.id, call.message.message_id)

# ==================== БРАКИ ====================

@bot.message_handler(func=lambda m: m.text == "💍 Брак" or m.text == "/marry")
def menu_marry(message):
    user_id = message.from_user.id
    seals = get_player_seals(user_id)
    if not seals:
        bot.send_message(user_id, "У вас нет тюленей!")
        return

    markup = types.InlineKeyboardMarkup()
    for s in seals:
        markup.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"marrysel_{s[0]}"))
    bot.send_message(user_id, "Выберите своего тюленя для брака:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("marrysel_"))
def marry_select(call):
    seal_id = int(call.data.split("_")[1])
    bot.send_message(call.from_user.id, "Введите ID или @username партнёра:")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, lambda m: marry_get_partner(m, seal_id))

def marry_get_partner(message, seal1_id):
    user_id = message.from_user.id
    text = message.text.strip()

    if text.startswith("@"):
        partner_username = text[1:]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id FROM players WHERE username = ?", (partner_username,))
        row = c.fetchone()
        conn.close()
        if not row:
            bot.send_message(user_id, "Игрок не найден!")
            return
        partner_id = row[0]
    else:
        try:
            partner_id = int(text)
        except ValueError:
            bot.send_message(user_id, "Неверный формат! Введите @username или числовой ID.")
            return

    if partner_id == user_id:
        bot.send_message(user_id, "Нельзя заключить брак с самим собой!")
        return

    partner_seals = get_player_seals(partner_id)
    if not partner_seals:
        bot.send_message(user_id, "У этого игрока нет тюленей!")
        return

    markup = types.InlineKeyboardMarkup()
    for s in partner_seals:
        markup.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"marrydo_{seal1_id}_{s[0]}_{partner_id}"))
    bot.send_message(user_id, "Выберите тюленя партнёра:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("marrydo_"))
def marry_do(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    seal1_id = int(parts[1])
    seal2_id = int(parts[2])
    partner_id = int(parts[3])

    seal1 = get_seal(seal1_id)
    seal2 = get_seal(seal2_id)

    if not seal1 or not seal2:
        bot.answer_callback_query(call.id, "Тюлень не найден!")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT * FROM marriages WHERE (seal1_id = ? AND seal2_id = ?) OR (seal1_id = ? AND seal2_id = ?)", (seal1_id, seal2_id, seal2_id, seal1_id))
    if c.fetchone():
        bot.answer_callback_query(call.id, "Эти тюлени уже в браке!")
        conn.close()
        return

    c.execute("INSERT INTO marriages (seal1_id, seal2_id, player1_id, player2_id, created_at) VALUES (?, ?, ?, ?, ?)",
              (seal1_id, seal2_id, user_id, partner_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

    msg = f"💍 Брак заключён! {seal1[2]} ❤️ {seal2[2]}\n"

    if random.random() < 0.5:
        baby_name = random.choice(["Малыш", "Кроха", "Пузырь", "Лапик", "Шлёпик", "Ням"])
        baby_str = (seal1[7] + seal2[7]) // 4 + random.randint(1, 3)
        baby_def = (seal1[8] + seal2[8]) // 4 + random.randint(0, 2)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO seals (owner_id, name, health, max_health, mood, satiety, strength, defense, level, exp, is_baby, born_at) VALUES (?, ?, 60, 60, 70, 70, ?, ?, 1, 0, 1, ?)",
                  (user_id, baby_name, baby_str, baby_def, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        msg += f"🍼 Родился тюленёнок — {baby_name}! Сила: {baby_str}, Защита: {baby_def}"
    else:
        msg += "Тюленёнок не появился... Может быть в следующий раз!"

    bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

# ==================== ЕЖЕДНЕВНЫЕ ЗАДАНИЯ ====================

QUEST_TEMPLATES = [
    {"type": "play", "target": 3, "reward": 30, "desc": "Поиграть с тюленем 3 раза"},
    {"type": "feed", "target": 3, "reward": 30, "desc": "Покормить тюленя 3 раза"},
    {"type": "battle", "target": 1, "reward": 40, "desc": "Победить 1 босса"},
    {"type": "dungeon", "target": 1, "reward": 50, "desc": "Пройти 1 подземелье"},
    {"type": "shop", "target": 1, "reward": 20, "desc": "Купить 1 предмет в магазине"},
    {"type": "work", "target": 1, "reward": 35, "desc": "Отправить тюленя на работу 1 раз"},
]

def generate_daily_quests(user_id):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM daily_quests WHERE user_id = ? AND date = ?", (user_id, today))
    if c.fetchall():
        conn.close()
        return

    c.execute("DELETE FROM daily_quests WHERE user_id = ? AND date != ?", (user_id, today))
    chosen = random.sample(QUEST_TEMPLATES, 3)
    for q in chosen:
        c.execute("INSERT INTO daily_quests (user_id, quest_type, quest_target, quest_progress, quest_reward, date, claimed) VALUES (?, ?, ?, 0, ?, ?, 0)",
                  (user_id, q["type"], q["target"], q["reward"], today))
    conn.commit()
    conn.close()

def update_quest_progress(user_id, quest_type, amount):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT quest_id, quest_progress, quest_target FROM daily_quests WHERE user_id = ? AND quest_type = ? AND date = ? AND claimed = 0",
              (user_id, quest_type, today))
    rows = c.fetchall()
    for row in rows:
        quest_id, progress, target = row
        if progress < target:
            new_progress = min(target, progress + amount)
            c.execute("UPDATE daily_quests SET quest_progress = ? WHERE quest_id = ?", (new_progress, quest_id))
    conn.commit()
    conn.close()

def get_daily_quests(user_id):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM daily_quests WHERE user_id = ? AND date = ?", (user_id, today))
    rows = c.fetchall()
    conn.close()
    return rows

@bot.message_handler(func=lambda m: m.text == "📋 Задания" or m.text == "/quests")
def menu_quests(message):
    user_id = message.from_user.id
    generate_daily_quests(user_id)
    quests = get_daily_quests(user_id)

    if not quests:
        bot.send_message(user_id, "Задания не сгенерированы. Попробуйте позже.")
        return

    text = "📋 **Ежедневные задания**\n\n"
    markup = types.InlineKeyboardMarkup()

    quest_descs = {q["type"]: q["desc"] for q in QUEST_TEMPLATES}

    for q in quests:
        qid, uid, qtype, qtarget, qprogress, qreward, qdate, claimed = q
        desc = quest_descs.get(qtype, qtype)
        status = f"{qprogress}/{qtarget}"
        if claimed:
            text += f"  ✅ {desc} — {status} (награда 🐟{qreward}) — получено\n"
        elif qprogress >= qtarget:
            text += f"  🎁 {desc} — {status} (награда 🐟{qreward}) — готово!\n"
            markup.add(types.InlineKeyboardButton(f"Забрать 🐟{qreward} ({desc})", callback_data=f"qclaim_{qid}"))
        else:
            text += f"  ⬜ {desc} — {status} (награда 🐟{qreward})\n"

    if markup.keyboard:
        bot.send_message(user_id, text, parse_mode='Markdown', reply_markup=markup)
    else:
        bot.send_message(user_id, text, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("qclaim_"))
def quest_claim(call):
    user_id = call.from_user.id
    quest_id = int(call.data.split("_")[1])

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM daily_quests WHERE quest_id = ? AND claimed = 0", (quest_id,))
    row = c.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "Задание уже получено или не найдено!")
        conn.close()
        return

    qtarget = row[3]
    qprogress = row[4]
    qreward = row[5]

    if qprogress < qtarget:
        bot.answer_callback_query(call.id, "Задание ещё не выполнено!")
        conn.close()
        return

    c.execute("UPDATE daily_quests SET claimed = 1 WHERE quest_id = ?", (quest_id,))
    conn.commit()
    conn.close()

    add_fishnets(user_id, qreward)
    bot.answer_callback_query(call.id, f"Получено 🐟{qreward}!")

# ==================== ФОНОВЫЙ ПОТОК: СТАТЫ ====================

def stats_decay():
    while True:
        time.sleep(3600)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT seal_id, health, mood, satiety, max_health FROM seals")
        seals = c.fetchall()
        for s in seals:
            seal_id, hp, mood, satiety, max_hp = s
            new_mood = max(0, mood - random.randint(3, 8))
            new_satiety = max(0, satiety - random.randint(5, 10))
            new_hp = hp
            if new_satiety < 20:
                new_hp = max(1, hp - random.randint(3, 8))
            c.execute("UPDATE seals SET mood = ?, satiety = ?, health = ? WHERE seal_id = ?",
                      (new_mood, new_satiety, new_hp, seal_id))
        conn.commit()
        conn.close()

decay_thread = threading.Thread(target=stats_decay, daemon=True)
decay_thread.start()

# ==================== ОСТАЛЬНЫЕ КОМАНДЫ ====================

@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def btn_profile(message):
    cmd_profile(message)

# ==================== КОМАНДЫ В МЕНЮ (ПОДСКАЗКИ) ====================

bot.set_my_commands([
    types.BotCommand("start", "Регистрация / Главное меню"),
    types.BotCommand("help", "Справка по всем командам"),
    types.BotCommand("profile", "Профиль игрока"),
    types.BotCommand("setphoto", "Установить фото профиля"),
    types.BotCommand("setname", "Изменить имя профиля"),
    types.BotCommand("shop", "Магазин — еда, оружие, аксессуары"),
    types.BotCommand("battle", "Бой с боссом"),
    types.BotCommand("dungeon", "Подземелье (5 этажей)"),
    types.BotCommand("work", "Отправить тюленя на работу"),
    types.BotCommand("marry", "Брак тюленей"),
    types.BotCommand("quests", "Ежедневные задания"),
])

# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    print("Бот запущен! 🦭")
    bot.polling(none_stop=True)

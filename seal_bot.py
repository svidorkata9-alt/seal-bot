import telebot
from telebot import types
import sqlite3, random, threading, time, os, shutil, json, re
from datetime import datetime, date, timedelta

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "PLACEHOLDER_TOKEN")
bot = telebot.TeleBot(TOKEN)
DB_PATH = "seal_life.db"
BACKUP_DIR = "backups"
MAX_SEALS = 5
FISHING_COOLDOWN_MIN = 10
MAX_CLAN_MEMBERS = 20
CLAN_DUNGEON_MIN_LEVEL = 4
CLAN_DUNGEON_FLOORS = 10
PLAY_COOLDOWN_MIN = 15
BABY_GROW_DAYS = 3

# ==================== БЭКАП И МИГРАЦИИ ====================
def backup_db():
    if not os.path.exists(DB_PATH): return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bp = os.path.join(BACKUP_DIR, f"seal_life_{ts}.db")
    shutil.copy2(DB_PATH, bp)
    bks = sorted([os.path.join(BACKUP_DIR,f) for f in os.listdir(BACKUP_DIR) if f.endswith(".db")], key=os.path.getmtime)
    for o in bks[:-10]: os.remove(o)
    return bp

def get_db_version(conn):
    c = conn.cursor()
    try:
        c.execute("SELECT value FROM _meta WHERE key='schema_version'")
        r = c.fetchone()
        return int(r[0]) if r else 0
    except sqlite3.OperationalError: return 0

def set_db_version(conn, v):
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("INSERT OR REPLACE INTO _meta (key,value) VALUES ('schema_version',?)", (str(v),))
    conn.commit()

def migration_1(c):
    c.execute("""CREATE TABLE IF NOT EXISTS players (
        user_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, photo_path TEXT,
        fishnets INTEGER DEFAULT 100, faction TEXT, faction_rep INTEGER DEFAULT 0, fish_cooldown TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS seals (
        seal_id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, name TEXT,
        health INTEGER DEFAULT 100, max_health INTEGER DEFAULT 100, mood INTEGER DEFAULT 80,
        satiety INTEGER DEFAULT 80, strength INTEGER DEFAULT 10, defense INTEGER DEFAULT 5,
        level INTEGER DEFAULT 1, exp INTEGER DEFAULT 0, is_baby INTEGER DEFAULT 0, born_at TEXT,
        equipped_weapon TEXT, equipped_armor TEXT, equipped_helmet TEXT, equipped_shield TEXT,
        equipped_accessory TEXT, work_cooldown TEXT, play_cooldown TEXT, photo_path TEXT,
        work_cooldown_min INTEGER DEFAULT 0
    )""")
    c.execute("CREATE TABLE IF NOT EXISTS marriages (marriage_id INTEGER PRIMARY KEY AUTOINCREMENT, seal1_id INTEGER, seal2_id INTEGER, player1_id INTEGER, player2_id INTEGER, created_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS inventory (inv_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, item_name TEXT, item_type TEXT, quantity INTEGER DEFAULT 1)")
    c.execute("CREATE TABLE IF NOT EXISTS daily_quests (quest_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, quest_type TEXT, quest_target INTEGER, quest_progress INTEGER DEFAULT 0, quest_reward INTEGER, date TEXT, claimed INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS dungeon_runs (run_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, seal_id INTEGER, current_floor INTEGER DEFAULT 1, active INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS trade_offers (offer_id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, item_name TEXT, item_type TEXT, price INTEGER, created_at TEXT, active INTEGER DEFAULT 1)")
    c.execute("CREATE TABLE IF NOT EXISTS votes (vote_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, event_type TEXT, vote TEXT, date TEXT, UNIQUE(user_id, date))")
    c.execute("CREATE TABLE IF NOT EXISTS active_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, effect TEXT, expires_at TEXT, active INTEGER DEFAULT 1)")

def migration_2(c):
    c.execute("CREATE TABLE IF NOT EXISTS seal_skills (skill_id INTEGER PRIMARY KEY AUTOINCREMENT, seal_id INTEGER, skill_name TEXT, skill_effect TEXT, acquired_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS duels (duel_id INTEGER PRIMARY KEY AUTOINCREMENT, challenger_id INTEGER, opponent_id INTEGER, challenger_seal_id INTEGER, opponent_seal_id INTEGER, status TEXT DEFAULT 'pending', winner_id INTEGER, reward INTEGER, created_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS quest_chains (chain_id INTEGER PRIMARY KEY, name TEXT, story TEXT, steps_json TEXT, reward_json TEXT, reward_fishnets INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS player_quest_chains (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chain_id INTEGER, current_step INTEGER DEFAULT 0, step_progress INTEGER DEFAULT 0, completed INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS clans (clan_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, emblem TEXT, leader_id INTEGER, created_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS clan_members (id INTEGER PRIMARY KEY AUTOINCREMENT, clan_id INTEGER, user_id INTEGER, joined_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS clan_dungeons (id INTEGER PRIMARY KEY AUTOINCREMENT, clan_id INTEGER, current_floor INTEGER DEFAULT 1, active INTEGER DEFAULT 0, started_by INTEGER)")
    chains = [
        (1,"Потерянный компас","Старый мудрый тюлень потерял компас во время шторма.",
         json.dumps([{"type":"dungeon_floor","target":3,"desc":"Дойдите до 3-го этажа подземелья"},{"type":"battle_count","target":2,"desc":"Победите 2 боссов"},{"type":"craft_item","target":1,"desc":"Скрафтите 1 предмет"}]),
         json.dumps({"item":"Компас мудреца 🧭","type":"accessory"}),200),
        (2,"Тайна глубин","Древняя табличка говорит о сокровище на дне океана.",
         json.dumps([{"type":"dungeon_complete","target":1,"desc":"Пройдите 1 подземелье полностью"},{"type":"reach_level","target":10,"desc":"Достигните 10 уровня"}]),
         json.dumps({"item":"Амулет глубин 🌊","type":"accessory"}),500),
        (3,"Король арены","Станьте легендой среди тюленей!",
         json.dumps([{"type":"duel_win","target":3,"desc":"Победите 3 игроков в дуэлях"},{"type":"battle_count","target":5,"desc":"Победите 5 боссов"}]),
         json.dumps({"item":"Корона чемпиона 👑","type":"accessory"}),1000),
    ]
    c.executemany("INSERT OR REPLACE INTO quest_chains VALUES (?,?,?,?,?,?)", chains)

def migration_3(c):
    try: c.execute("ALTER TABLE seals ADD COLUMN equipped_artifact TEXT")
    except sqlite3.OperationalError: pass
    try: c.execute("ALTER TABLE dungeon_runs ADD COLUMN current_monster INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass

MIGRATIONS = [migration_1, migration_2, migration_3]

def run_migrations():
    backup_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    v = get_db_version(conn)
    for i in range(v, len(MIGRATIONS)):
        MIGRATIONS[i](c)
    set_db_version(conn, len(MIGRATIONS))
    conn.commit()
    conn.close()

# ==================== МАГАЗИН ====================
SHOP_ITEMS = {
    "Апельсин 🍊": {"price": 15, "type": "food", "satiety": 25, "mood": 10},
    "Рыба 🐟": {"price": 10, "type": "food", "satiety": 20, "mood": 5},
    "Кальмар 🦑": {"price": 25, "type": "food", "satiety": 35, "mood": 15},
    "Мороженое 🍦": {"price": 20, "type": "food", "satiety": 15, "mood": 30},
    "Креветка 🦐": {"price": 18, "type": "food", "satiety": 22, "mood": 8},
    "Устрица 🦪": {"price": 30, "type": "food", "satiety": 40, "mood": 20},
    "Водоросли 🌿": {"price": 8, "type": "food", "satiety": 15, "mood": 3},
    "Аптечка 💊": {"price": 100, "type": "medkit", "heal": 50},
    "Бантик 🎀": {"price": 40, "type": "accessory"},
    "Шарф 🧣": {"price": 35, "type": "accessory"},
    "Корона 👑": {"price": 200, "type": "accessory"},
    "Очки 🕶️": {"price": 50, "type": "accessory"},
    "Цветок 🌸": {"price": 25, "type": "accessory"},
    "Морская звезда ⭐": {"price": 60, "type": "accessory"},
    "Жемчужное ожерелье 🫧": {"price": 120, "type": "accessory"},
    "Перо чайки 🪶": {"price": 30, "type": "accessory"},
    "Радужный пояс 🌈": {"price": 80, "type": "accessory"},
}

# ==================== БОНУСЫ ПРЕДМЕТОВ ====================
ITEM_BONUSES = {
    # Базовое оружие
    "Костяной меч 🗡️": {"str": 5}, "Акулий клык 🦷": {"str": 8}, "Трезубец 🔱": {"str": 12}, "Китовый клинок 🐋": {"str": 15},
    "Ядовитый клинок ☠️": {"str": 10}, "Ядовитый дротик 🎯": {"str": 7},
    # Продвинутое оружие
    "Костяной лук 🏹": {"str": 14}, "Кристальный меч 💎": {"str": 18}, "Ледяной клинок ❄️": {"str": 20},
    "Коралловое копьё 🪸": {"str": 16}, "Светящийся меч ✨": {"str": 22}, "Тёмный клинок 🖤": {"str": 25},
    "Янтарный молот 🟡": {"str": 28}, "Рог нарвала 🦏": {"str": 24}, "Призрачный клинок 👻": {"str": 21},
    "Костяной гарпун 🦴": {"str": 13}, "Глубинный трезубец 🌑": {"str": 30}, "Кристальный лук 💎": {"str": 26},
    "Коралловый меч 🪸": {"str": 19}, "Ядовитый гарпун ☠️": {"str": 17}, "Ледяной лук ❄️": {"str": 23},
    # Базовая броня
    "Чешуйчатая броня 🐟": {"def": 5, "hp": 10}, "Панцирь краба 🦀": {"def": 8, "hp": 15},
    "Плетёная броня 🧵": {"def": 10, "hp": 25}, "Кракеновый панцирь 🐙": {"def": 15, "hp": 40},
    # Продвинутая броня
    "Костяная броня 🦴": {"def": 12, "hp": 30}, "Кристальная броня 💎": {"def": 18, "hp": 50},
    "Ледяная броня ❄️": {"def": 20, "hp": 55}, "Коралловая броня 🪸": {"def": 16, "hp": 45},
    "Светящаяся броня ✨": {"def": 22, "hp": 60}, "Тёмная броня 🖤": {"def": 25, "hp": 70},
    "Янтарная броня 🟡": {"def": 28, "hp": 80}, "Призрачная броня 👻": {"def": 20, "hp": 50},
    "Слизневый панцирь 🐌": {"def": 14, "hp": 35}, "Костяной доспех 🦴": {"def": 15, "hp": 40},
    # Базовые шлемы
    "Шлем из ракушек 🐚": {"def": 3, "hp": 10}, "Костяной шлем 💀": {"def": 5, "hp": 15}, "Корона из зубов 👑": {"def": 8, "hp": 20},
    "Ядовитый шлем ☠️": {"def": 4, "hp": 12},
    # Продвинутые шлемы
    "Кристальный шлем 💎": {"def": 10, "hp": 25}, "Ледяной шлем ❄️": {"def": 12, "hp": 30},
    "Коралловый шлем 🪸": {"def": 9, "hp": 22}, "Светящийся шлем ✨": {"def": 14, "hp": 35},
    "Тёмный шлем 🖤": {"def": 16, "hp": 40}, "Янтарный шлем 🟡": {"def": 18, "hp": 45},
    "Шлем из иголок 🦔": {"def": 8, "hp": 20}, "Призрачный шлем 👻": {"def": 13, "hp": 33},
    "Костяная корона 🦴": {"def": 11, "hp": 28}, "Слизневый шлем 🐌": {"def": 7, "hp": 18},
    # Базовые щиты
    "Щит из чешуи 🐠": {"def": 5}, "Панцирный щит 🛡️": {"def": 8}, "Щит кракена 🦑": {"def": 12}, "Ядовитый щит ☠️": {"def": 7},
    # Продвинутые щиты
    "Кристальный щит 💎": {"def": 15}, "Ледяной щит ❄️": {"def": 18}, "Коралловый щит 🪸": {"def": 14},
    "Светящийся щит ✨": {"def": 20}, "Тёмный щит 🖤": {"def": 22}, "Янтарный щит 🟡": {"def": 25},
    "Песчаный щит ⏳": {"def": 13}, "Призрачный щит 👻": {"def": 17}, "Слизневый щит 🐌": {"def": 11},
    "Костяной щит 🦴": {"def": 10}, "Роговой щит 🦏": {"def": 19},
}

ACCESSORY_BONUSES = {
    "Бантик 🎀": 10, "Шарф 🧣": 8, "Корона 👑": 20, "Очки 🕶️": 7, "Цветок 🌸": 5,
    "Компас мудреца 🧭": 25, "Амулет глубин 🌊": 22, "Корона чемпиона 👑": 30,
    "Морская звезда ⭐": 12, "Жемчужное ожерелье 🫧": 18, "Перо чайки 🪶": 6, "Радужный пояс 🌈": 14,
}

# ==================== РЕЦЕПТЫ КРАФТА ====================
CRAFT_RECIPES = [
    # --- Базовое оружие (Тир 1) ---
    {"name": "Костяной меч 🗡️", "type": "weapon", "resources": {"Акулий зуб 🦈": 3}, "tier": 1, "desc": "Надёжный меч из акульих зубов"},
    {"name": "Акулий клык 🦷", "type": "weapon", "resources": {"Акулий зуб 🦈": 5, "Чешуя 🐟": 2}, "tier": 1, "desc": "Острый клык для режущих ударов"},
    {"name": "Трезубец 🔱", "type": "weapon", "resources": {"Щупальце 🐙": 4, "Акулий зуб 🦈": 3}, "tier": 1, "desc": "Классическое оружие глубин"},
    {"name": "Китовый клинок 🐋", "type": "weapon", "resources": {"Китовый ус 🐋": 3, "Жемчуг 🫧": 1}, "tier": 2, "desc": "Длинный клинок из китового уса"},
    {"name": "Ядовитый клинок ☠️", "type": "weapon", "resources": {"Жало 🐡": 3, "Акулий зуб 🦈": 2}, "tier": 1, "desc": "Отравляет противника"},
    {"name": "Ядовитый дротик 🎯", "type": "weapon", "resources": {"Жало 🐡": 2, "Чешуя 🐟": 3}, "tier": 1, "desc": "Метательный дротик с ядом"},
    # --- Продвинутое оружие (Тир 2) ---
    {"name": "Костяной лук 🏹", "type": "weapon", "resources": {"Кость 🦴": 5, "Чешуя 🐟": 2}, "tier": 2, "desc": "Дальний бой костяным луком"},
    {"name": "Костяной гарпун 🦴", "type": "weapon", "resources": {"Кость 🦴": 4, "Акулий зуб 🦈": 2}, "tier": 2, "desc": "Тяжёлый гарпун для пробивания брони"},
    {"name": "Кристальный меч 💎", "type": "weapon", "resources": {"Кристалл 💎": 3, "Кость 🦴": 2}, "tier": 2, "desc": "Меч из чистого кристалла"},
    {"name": "Ледяной клинок ❄️", "type": "weapon", "resources": {"Лёд 🧊": 4, "Чешуя 🐟": 3}, "tier": 2, "desc": "Замораживает противника"},
    {"name": "Коралловое копьё 🪸", "type": "weapon", "resources": {"Коралл 🪸": 5, "Панцирь 🦀": 2}, "tier": 2, "desc": "Копьё с коралловым наконечником"},
    {"name": "Светящийся меч ✨", "type": "weapon", "resources": {"Светящаяся чешуя ✨": 4, "Кристалл 💎": 2}, "tier": 3, "desc": "Меч, светящийся в темноте"},
    {"name": "Тёмный клинок 🖤", "type": "weapon", "resources": {"Чернила 🖤": 5, "Клык 🦷": 2}, "tier": 3, "desc": "Клинок тьмы"},
    {"name": "Янтарный молот 🟡", "type": "weapon", "resources": {"Янтарь 🟡": 3, "Кость 🦴": 4}, "tier": 3, "desc": "Тяжёлый молот из янтаря"},
    {"name": "Рог нарвала 🦏", "type": "weapon", "resources": {"Рог 🦏": 2, "Жемчуг 🫧": 1}, "tier": 3, "desc": "Острый рог нарвала"},
    {"name": "Призрачный клинок 👻", "type": "weapon", "resources": {"Призрачная чешуя 👻": 4, "Чернила 🖤": 2}, "tier": 3, "desc": "Полупрозрачный клинок"},
    {"name": "Ядовитый гарпун ☠️", "type": "weapon", "resources": {"Жало 🐡": 4, "Кость 🦴": 3, "Слизь 🐌": 2}, "tier": 2, "desc": "Гарпун, пропитанный ядом"},
    {"name": "Коралловый меч 🪸", "type": "weapon", "resources": {"Коралл 🪸": 4, "Акулий зуб 🦈": 2}, "tier": 2, "desc": "Меч с коралловыми шипами"},
    # --- Легендарное оружие (Тир 4) ---
    {"name": "Глубинный трезубец 🌑", "type": "weapon", "resources": {"Клык 🦷": 3, "Янтарь 🟡": 2, "Кристалл 💎": 3}, "tier": 4, "desc": "Легендарный трезубец глубин"},
    {"name": "Кристальный лук 💎", "type": "weapon", "resources": {"Кристалл 💎": 5, "Светящаяся чешуя ✨": 3}, "tier": 4, "desc": "Идеальный лук из кристалла"},
    {"name": "Ледяной лук ❄️", "type": "weapon", "resources": {"Лёд 🧊": 5, "Кристалл 💎": 2}, "tier": 3, "desc": "Лук, замораживающий стрелы"},
    # --- Базовая броня (Тир 1) ---
    {"name": "Чешуйчатая броня 🐟", "type": "armor", "resources": {"Чешуя 🐟": 4}, "tier": 1, "desc": "Лёгкая чешуйчатая броня"},
    {"name": "Панцирь краба 🦀", "type": "armor", "resources": {"Панцирь 🦀": 3}, "tier": 1, "desc": "Прочный панцирь"},
    {"name": "Плетёная броня 🧵", "type": "armor", "resources": {"Щупальце 🐙": 3, "Чешуя 🐟": 2}, "tier": 1, "desc": "Плетёная из щупалец"},
    {"name": "Кракеновый панцирь 🐙", "type": "armor", "resources": {"Щупальце 🐙": 5, "Жемчуг 🫧": 1}, "tier": 2, "desc": "Панцирь из частей кракена"},
    # --- Продвинутая броня (Тир 2-3) ---
    {"name": "Костяная броня 🦴", "type": "armor", "resources": {"Кость 🦴": 5}, "tier": 2, "desc": "Броня из костей"},
    {"name": "Костяной доспех 🦴", "type": "armor", "resources": {"Кость 🦴": 7, "Панцирь 🦀": 2}, "tier": 2, "desc": "Полный доспех из костей"},
    {"name": "Кристальная броня 💎", "type": "armor", "resources": {"Кристалл 💎": 4, "Чешуя 🐟": 2}, "tier": 3, "desc": "Броня из кристаллов"},
    {"name": "Ледяная броня ❄️", "type": "armor", "resources": {"Лёд 🧊": 5}, "tier": 3, "desc": "Броня из вечного льда"},
    {"name": "Коралловая броня 🪸", "type": "armor", "resources": {"Коралл 🪸": 4, "Панцирь 🦀": 2}, "tier": 2, "desc": "Броня с кораллами"},
    {"name": "Светящаяся броня ✨", "type": "armor", "resources": {"Светящаяся чешуя ✨": 4}, "tier": 3, "desc": "Светится в темноте"},
    {"name": "Тёмная броня 🖤", "type": "armor", "resources": {"Чернила 🖤": 4, "Клык 🦷": 2}, "tier": 3, "desc": "Броня тьмы"},
    {"name": "Янтарная броня 🟡", "type": "armor", "resources": {"Янтарь 🟡": 3, "Кость 🦴": 3}, "tier": 4, "desc": "Древняя янтарная броня"},
    {"name": "Призрачная броня 👻", "type": "armor", "resources": {"Призрачная чешуя 👻": 4}, "tier": 3, "desc": "Полупрозрачная броня"},
    {"name": "Слизневый панцирь 🐌", "type": "armor", "resources": {"Слизь 🐌": 4, "Панцирь 🦀": 2}, "tier": 2, "desc": "Скользкий панцирь"},
    # --- Шлемы (Тир 1-4) ---
    {"name": "Шлем из ракушек 🐚", "type": "helmet", "resources": {"Панцирь 🦀": 3, "Чешуя 🐟": 1}, "tier": 1, "desc": "Простой шлем"},
    {"name": "Костяной шлем 💀", "type": "helmet", "resources": {"Акулий зуб 🦈": 3}, "tier": 1, "desc": "Шлем из зубов"},
    {"name": "Корона из зубов 👑", "type": "helmet", "resources": {"Акулий зуб 🦈": 5, "Жемчуг 🫧": 1}, "tier": 2, "desc": "Корона охотника"},
    {"name": "Ядовитый шлем ☠️", "type": "helmet", "resources": {"Жало 🐡": 3, "Чешуя 🐟": 2}, "tier": 1, "desc": "Шлем с ядовитыми шипами"},
    {"name": "Кристальный шлем 💎", "type": "helmet", "resources": {"Кристалл 💎": 3}, "tier": 3, "desc": "Шлем из кристалла"},
    {"name": "Ледяной шлем ❄️", "type": "helmet", "resources": {"Лёд 🧊": 3}, "tier": 3, "desc": "Ледяной шлем"},
    {"name": "Коралловый шлем 🪸", "type": "helmet", "resources": {"Коралл 🪸": 3}, "tier": 2, "desc": "Шлем из кораллов"},
    {"name": "Светящийся шлем ✨", "type": "helmet", "resources": {"Светящаяся чешуя ✨": 3}, "tier": 3, "desc": "Светящийся шлем"},
    {"name": "Тёмный шлем 🖤", "type": "helmet", "resources": {"Чернила 🖤": 3}, "tier": 3, "desc": "Шлем тьмы"},
    {"name": "Янтарный шлем 🟡", "type": "helmet", "resources": {"Янтарь 🟡": 2, "Кость 🦴": 3}, "tier": 4, "desc": "Древний шлем"},
    {"name": "Шлем из иголок 🦔", "type": "helmet", "resources": {"Иголка 🦔": 4, "Панцирь 🦀": 1}, "tier": 2, "desc": "Шлем с иглами"},
    {"name": "Призрачный шлем 👻", "type": "helmet", "resources": {"Призрачная чешуя 👻": 3}, "tier": 3, "desc": "Призрачный шлем"},
    {"name": "Костяная корона 🦴", "type": "helmet", "resources": {"Кость 🦴": 4, "Жемчуг 🫧": 1}, "tier": 2, "desc": "Корона из костей"},
    {"name": "Слизневый шлем 🐌", "type": "helmet", "resources": {"Слизь 🐌": 3, "Панцирь 🦀": 1}, "tier": 2, "desc": "Скользкий шлем"},
    # --- Щиты (Тир 1-4) ---
    {"name": "Щит из чешуи 🐠", "type": "shield", "resources": {"Чешуя 🐟": 4, "Панцирь 🦀": 1}, "tier": 1, "desc": "Щит из чешуи"},
    {"name": "Панцирный щит 🛡️", "type": "shield", "resources": {"Панцирь 🦀": 4}, "tier": 1, "desc": "Прочный щит"},
    {"name": "Щит кракена 🦑", "type": "shield", "resources": {"Щупальце 🐙": 3, "Панцирь 🦀": 2}, "tier": 2, "desc": "Щит из частей кракена"},
    {"name": "Ядовитый щит ☠️", "type": "shield", "resources": {"Жало 🐡": 4, "Панцирь 🦀": 2}, "tier": 2, "desc": "Ядовитый щит"},
    {"name": "Кристальный щит 💎", "type": "shield", "resources": {"Кристалл 💎": 4}, "tier": 3, "desc": "Кристальный щит"},
    {"name": "Ледяной щит ❄️", "type": "shield", "resources": {"Лёд 🧊": 4}, "tier": 3, "desc": "Ледяной щит"},
    {"name": "Коралловый щит 🪸", "type": "shield", "resources": {"Коралл 🪸": 4}, "tier": 2, "desc": "Коралловый щит"},
    {"name": "Светящийся щит ✨", "type": "shield", "resources": {"Светящаяся чешуя ✨": 4}, "tier": 3, "desc": "Светящийся щит"},
    {"name": "Тёмный щит 🖤", "type": "shield", "resources": {"Чернила 🖤": 4}, "tier": 3, "desc": "Щит тьмы"},
    {"name": "Янтарный щит 🟡", "type": "shield", "resources": {"Янтарь 🟡": 3}, "tier": 4, "desc": "Древний щит"},
    {"name": "Песчаный щит ⏳", "type": "shield", "resources": {"Песок ⏳": 5, "Панцирь 🦀": 3}, "tier": 2, "desc": "Песчаный щит"},
    {"name": "Призрачный щит 👻", "type": "shield", "resources": {"Призрачная чешуя 👻": 4}, "tier": 3, "desc": "Призрачный щит"},
    {"name": "Слизневый щит 🐌", "type": "shield", "resources": {"Слизь 🐌": 4, "Панцирь 🦀": 2}, "tier": 2, "desc": "Скользкий щит"},
    {"name": "Костяной щит 🦴", "type": "shield", "resources": {"Кость 🦴": 4}, "tier": 2, "desc": "Щит из костей"},
    {"name": "Роговой щит 🦏", "type": "shield", "resources": {"Рог 🦏": 3, "Панцирь 🦀": 2}, "tier": 3, "desc": "Щит из рога нарвала"},
    # --- Зелья и расходники ---
    {"name": "Зелье силы 💪", "type": "potion", "resources": {"Слизь 🐌": 2, "Жало 🐡": 1}, "tier": 1, "desc": "+10 силы на 1 бой"},
    {"name": "Зелье здоровья 💚", "type": "potion", "resources": {"Иголка 🦔": 3, "Жемчуг 🫧": 1}, "tier": 2, "desc": "Полное лечение"},
    {"name": "Зелье ярости 😤", "type": "potion", "resources": {"Клык 🦷": 2, "Чернила 🖤": 1}, "tier": 3, "desc": "Режим берсерка"},
    {"name": "Ледяное зелье 🧊", "type": "potion", "resources": {"Лёд 🧊": 3}, "tier": 2, "desc": "Замораживает врага"},
    {"name": "Зелье невидимости 👻", "type": "potion", "resources": {"Призрачная чешуя 👻": 2, "Чернила 🖤": 2}, "tier": 3, "desc": "Бонус к уклонению"},
    {"name": "Ядовитое зелье ☠️", "type": "potion", "resources": {"Жало 🐡": 3, "Слизь 🐌": 2}, "tier": 2, "desc": "Отравляет врага"},
    {"name": "Зелье брони 🛡️", "type": "potion", "resources": {"Панцирь 🦀": 3, "Слизь 🐌": 1}, "tier": 2, "desc": "+10 защиты на 1 бой"},
    {"name": "Светящееся зелье ✨", "type": "potion", "resources": {"Светящаяся чешуя ✨": 2, "Кристалл 💎": 1}, "tier": 3, "desc": "Освещает подземелье"},
    {"name": "Янтарный эликсир 🟡", "type": "potion", "resources": {"Янтарь 🟡": 2, "Жемчуг 🫧": 1}, "tier": 4, "desc": "Восстанавливает 100 HP"},
]

POTION_EFFECTS = {
    "Зелье силы 💪": {"stat": "str", "amount": 10, "duration": 1},
    "Зелье здоровья 💚": {"stat": "heal_full", "amount": 0, "duration": 0},
    "Зелье ярости 😤": {"stat": "berserk", "amount": 0, "duration": 1},
    "Ледяное зелье 🧊": {"stat": "freeze", "amount": 0, "duration": 1},
    "Зелье невидимости 👻": {"stat": "dodge", "amount": 30, "duration": 1},
    "Ядовитое зелье ☠️": {"stat": "poison", "amount": 15, "duration": 3},
    "Зелье брони 🛡️": {"stat": "def", "amount": 10, "duration": 1},
    "Светящееся зелье ✨": {"stat": "light", "amount": 0, "duration": 0},
    "Янтарный эликсир 🟡": {"stat": "heal", "amount": 100, "duration": 0},
}

# ==================== ЦЕНЫ ПРОДАЖИ РЕСУРСОВ ====================
RESOURCE_SELL_PRICES = {
    "Чешуя 🐟": 5, "Панцирь 🦀": 7, "Акулий зуб 🦈": 10, "Щупальце 🐙": 12,
    "Жемчуг 🫧": 25, "Китовый ус 🐋": 15, "Жало 🐡": 8,
    "Кость 🦴": 9, "Кристалл 💎": 20, "Лёд 🧊": 14, "Коралл 🪸": 11,
    "Светящаяся чешуя ✨": 22, "Тёмные чернила 🖤": 18, "Янтарь 🟡": 30,
    "Рог 🦏": 28, "Призрачная чешуя 👻": 24, "Слизь 🐌": 6, "Иголка 🦔": 7,
    "Песок ⏳": 4, "Клык 🦷": 16,
}

RARITY_SELL_PRICES = {"F": 15, "E": 35, "D": 75, "C": 150, "B": 350, "A": 700, "S": 1500}

POTION_SELL_PRICES = {
    "Зелье силы 💪": 25, "Зелье здоровья 💚": 50, "Зелье ярости 😤": 70,
    "Ледяное зелье 🧊": 40, "Зелье невидимости 👻": 60, "Ядовитое зелье ☠️": 35,
    "Зелье брони 🛡️": 30, "Светящееся зелье ✨": 55, "Янтарный эликсир 🟡": 120,
}

# ==================== СУНДУКИ И АРТЕФАКТЫ ====================
ARTIFACTS = {
    "F": [{"name":"Ржавый ключ 🗝️","str":2,"def":1,"hp":5},{"name":"Старый компас 🧭","str":1,"def":2,"hp":5},{"name":"Обломок ракушки 🐚","str":2,"def":2,"hp":3}],
    "E": [{"name":"Медный амулет 🟤","str":4,"def":3,"hp":10},{"name":"Рыбацкий талисман 🎣","str":3,"def":4,"hp":12}],
    "D": [{"name":"Серебряный медальон 🥈","str":7,"def":5,"hp":20},{"name":"Коралловый браслет 🪸","str":6,"def":6,"hp":18}],
    "C": [{"name":"Жемчужина силы ⚪","str":12,"def":8,"hp":30},{"name":"Акулий талисман 🦈","str":10,"def":10,"hp":25}],
    "B": [{"name":"Кристалл глубин 💎","str":18,"def":12,"hp":50},{"name":"Раковина Левиафана 🐚","str":15,"def":15,"hp":45}],
    "A": [{"name":"Сердце океана 💙","str":28,"def":18,"hp":80},{"name":"Корона Морского Царя 👑","str":25,"def":20,"hp":75}],
    "S": [{"name":"Слеза Посейдона 💧","str":45,"def":30,"hp":150},{"name":"Трезубец Бездны 🔱","str":50,"def":25,"hp":120}],
}

CHEST_WEAPONS = {
    "F": [{"name":"Ржавый нож 🗡️","str":4},{"name":"Деревянный меч 🪵","str":5}],
    "E": [{"name":"Каменный топор 🪓","str":7},{"name":"Костяной клинок 🦴","str":8}],
    "D": [{"name":"Коралловый меч 🪸","str":11},{"name":"Осколочный клинок 💎","str":12}],
    "C": [{"name":"Ледяной клинок ❄️","str":16},{"name":"Огненный меч 🔥","str":18}],
    "B": [{"name":"Молниевый клинок ⚡","str":22},{"name":"Призрачный меч 👻","str":25}],
    "A": [{"name":"Клинок дракона 🐉","str":32},{"name":"Буревой топор 🌪️","str":35}],
    "S": [{"name":"Меч Богов ⚔️","str":50},{"name":"Клинок Бездны 🌑","str":55}],
}

CHEST_ARMOR = {
    "F": [{"name":"Тряпьё 🧣","def":3,"hp":5},{"name":"Кожаная броня 👕","def":4,"hp":8}],
    "E": [{"name":"Медная броня 🟤","def":6,"hp":15},{"name":"Костяная броня 🦴","def":7,"hp":12}],
    "D": [{"name":"Коралловая броня 🪸","def":10,"hp":25},{"name":"Акулья чешуя 🦈","def":12,"hp":20}],
    "C": [{"name":"Ледяная броня ❄️","def":15,"hp":40},{"name":"Огненная броня 🔥","def":14,"hp":45}],
    "B": [{"name":"Молниевая броня ⚡","def":20,"hp":60},{"name":"Призрачная броня 👻","def":22,"hp":55}],
    "A": [{"name":"Драконья броня 🐉","def":30,"hp":100},{"name":"Буревая броня 🌪️","def":28,"hp":110}],
    "S": [{"name":"Броня Богов 🛡️","def":45,"hp":200},{"name":"Броня Бездны 🌑","def":50,"hp":180}],
}

CHEST_CONTENTS = {
    "F": {"fishnets": (10, 30)}, "E": {"fishnets": (30, 60)}, "D": {"fishnets": (60, 120)},
    "C": {"fishnets": (120, 250)}, "B": {"fishnets": (250, 500)}, "A": {"fishnets": (500, 1000)}, "S": {"fishnets": (1000, 2000)},
}

# ==================== КОНФИГ ПОДЗЕМЕЛЬЯ ====================
DUNGEON_FLOORS_CONFIG = [
    {"monsters": 2, "chest_rarity": "F", "hp_mult": 1.0, "str_mult": 1.0},
    {"monsters": 2, "chest_rarity": "F", "hp_mult": 1.3, "str_mult": 1.2},
    {"monsters": 3, "chest_rarity": "E", "hp_mult": 1.6, "str_mult": 1.4},
    {"monsters": 3, "chest_rarity": "D", "hp_mult": 2.0, "str_mult": 1.6},
    {"monsters": 3, "chest_rarity": "C", "hp_mult": 2.5, "str_mult": 1.8},
    {"monsters": 4, "chest_rarity": "C", "hp_mult": 3.0, "str_mult": 2.0},
    {"monsters": 4, "chest_rarity": "B", "hp_mult": 3.5, "str_mult": 2.2},
    {"monsters": 4, "chest_rarity": "A", "hp_mult": 4.0, "str_mult": 2.5},
    {"monsters": 5, "chest_rarity": "A", "hp_mult": 5.0, "str_mult": 3.0},
    {"monsters": 5, "chest_rarity": "S", "hp_mult": 6.0, "str_mult": 3.5},
]
DUNGEON_TOTAL_FLOORS = 10

# ==================== МОНСТРЫ ПОДЗЕМЕЛЬЯ (расширенные) ====================
DUNGEON_MONSTERS = [
    {"name": "Фугу 🐡", "hp": 30, "str": 8, "def": 3, "drops": {"Жало 🐡": 0.7}},
    {"name": "Креветка-ниндзя 🦐", "hp": 35, "str": 9, "def": 8, "drops": {"Панцирь 🦀": 0.5, "Чешуя 🐟": 0.3}},
    {"name": "Акула 🦈", "hp": 50, "str": 12, "def": 5, "drops": {"Акулий зуб 🦈": 0.7}},
    {"name": "Морской змей 🐍", "hp": 60, "str": 15, "def": 6, "drops": {"Чешуя 🐟": 0.7}},
    {"name": "Кракен 🐙", "hp": 80, "str": 18, "def": 8, "drops": {"Щупальце 🐙": 0.7, "Жемчуг 🫧": 0.1}},
    {"name": "Лобстер 🦞", "hp": 40, "str": 10, "def": 10, "drops": {"Панцирь 🦀": 0.7}},
    {"name": "Кашалот 🐋", "hp": 120, "str": 20, "def": 12, "drops": {"Китовый ус 🐋": 0.6}},
    {"name": "Электрический скат ⚡", "hp": 55, "str": 14, "def": 4, "drops": {"Чешуя 🐟": 0.5, "Жало 🐡": 0.3}},
    {"name": "Гигантская медуза 🪼", "hp": 45, "str": 11, "def": 3, "drops": {"Жало 🐡": 0.6}},
    {"name": "Морской дьявол 😈", "hp": 90, "str": 16, "def": 9, "drops": {"Жемчуг 🫧": 0.3, "Чешуя 🐟": 0.4}},
    # --- НОВЫЕ МОНСТРЫ ---
    {"name": "Морской ёж 🦔", "hp": 35, "str": 7, "def": 12, "drops": {"Иголка 🦔": 0.7, "Жало 🐡": 0.2}},
    {"name": "Нарвал 🦏", "hp": 70, "str": 14, "def": 7, "drops": {"Рог 🦏": 0.5, "Чешуя 🐟": 0.3}},
    {"name": "Гигантская улитка 🐌", "hp": 50, "str": 6, "def": 14, "drops": {"Слизь 🐌": 0.7, "Панцирь 🦀": 0.2}},
    {"name": "Призрачная рыба 👻", "hp": 65, "str": 13, "def": 5, "drops": {"Призрачная чешуя 👻": 0.6}},
    {"name": "Ледяная рыба 🧊", "hp": 75, "str": 15, "def": 8, "drops": {"Лёд 🧊": 0.7, "Чешуя 🐟": 0.2}},
    {"name": "Коралловый страж 🪸", "hp": 85, "str": 12, "def": 14, "drops": {"Коралл 🪸": 0.7, "Панцирь 🦀": 0.2}},
    {"name": "Светящийся угрь ⚡", "hp": 60, "str": 17, "def": 4, "drops": {"Светящаяся чешуя ✨": 0.6, "Чешуя 🐟": 0.2}},
    {"name": "Древний скелет 💀", "hp": 100, "str": 16, "def": 10, "drops": {"Кость 🦴": 0.7, "Жемчуг 🫧": 0.1}},
    {"name": "Тёмный кальмар 🖤", "hp": 90, "str": 18, "def": 6, "drops": {"Тёмные чернила 🖤": 0.7, "Щупальце 🐙": 0.3}},
    {"name": "Песчаный скат ⏳", "hp": 55, "str": 11, "def": 9, "drops": {"Песок ⏳": 0.6, "Чешуя 🐟": 0.2}},
    {"name": "Янтарная рыба 🟡", "hp": 110, "str": 19, "def": 11, "drops": {"Янтарь 🟡": 0.5, "Кость 🦴": 0.2}},
    {"name": "Глубинный хищник 🦷", "hp": 130, "str": 22, "def": 12, "drops": {"Клык 🦷": 0.6, "Чешуя 🐟": 0.2}},
    {"name": "Кристальный голем 💎", "hp": 150, "str": 20, "def": 18, "drops": {"Кристалл 💎": 0.5, "Кость 🦴": 0.2}},
    {"name": "Морская оса 🐝", "hp": 40, "str": 18, "def": 2, "drops": {"Жало 🐡": 0.5, "Иголка 🦔": 0.3}},
    {"name": "Коралловый краб 🪸🦀", "hp": 70, "str": 13, "def": 15, "drops": {"Коралл 🪸": 0.4, "Панцирь 🦀": 0.4}},
    {"name": "Ледяной кракен 🧊🐙", "hp": 140, "str": 24, "def": 10, "drops": {"Лёд 🧊": 0.4, "Щупальце 🐙": 0.4}},
]

BOSSES = [
    {"name": "Краб-босс 🦀", "drops": {"Панцирь 🦀": 0.8}}, {"name": "Акула 🦈", "drops": {"Акулий зуб 🦈": 0.8}},
    {"name": "Осьминог 🐙", "drops": {"Щупальце 🐙": 0.8}}, {"name": "Морской ёжик 🦔", "drops": {"Жало 🐡": 0.8, "Иголка 🦔": 0.5}},
    {"name": "Кашалот 🐋", "drops": {"Китовый ус 🐋": 0.7}}, {"name": "Морской змей 🐍", "drops": {"Чешуя 🐟": 0.8}},
    {"name": "Гигантский краб 🦀", "drops": {"Панцирь 🦀": 0.8, "Жемчуг 🫧": 0.15}},
    {"name": "Электрический скат ⚡", "drops": {"Чешуя 🐟": 0.7, "Жало 🐡": 0.3}},
    {"name": "Глубинный монстр 🌑", "drops": {"Жемчуг 🫧": 0.4, "Щупальце 🐙": 0.5}},
    {"name": "Король креветок 🦐", "drops": {"Панцирь 🦀": 0.7, "Чешуя 🐟": 0.3}},
    {"name": "Кристальный титан 💎", "drops": {"Кристалл 💎": 0.7, "Кость 🦴": 0.3}},
    {"name": "Ледяной левиафан 🧊", "drops": {"Лёд 🧊": 0.7, "Чешуя 🐟": 0.2}},
    {"name": "Тёмный властелин 🖤", "drops": {"Тёмные чернила 🖤": 0.7, "Клык 🦷": 0.3}},
    {"name": "Янтарный дракон 🟡", "drops": {"Янтарь 🟡": 0.6, "Кость 🦴": 0.3}},
    {"name": "Призрачный король 👻", "drops": {"Призрачная чешуя 👻": 0.7, "Жемчуг 🫧": 0.2}},
    {"name": "Нарвал-вождь 🦏", "drops": {"Рог 🦏": 0.7, "Жемчуг 🫧": 0.2}},
]

CLAN_DUNGEON_MONSTERS = [
    {"name": "Страж глубин 🌊", "hp": 200, "str": 25, "def": 15}, {"name": "Древний краб 🦀", "hp": 250, "str": 30, "def": 20},
    {"name": "Призрачная акула 👻", "hp": 300, "str": 35, "def": 18}, {"name": "Ледяной кальмар 🧊", "hp": 350, "str": 40, "def": 25},
    {"name": "Гигантский спрут 🐙", "hp": 400, "str": 45, "def": 22}, {"name": "Морской дракон 🐉", "hp": 500, "str": 55, "def": 30},
    {"name": "Бездонный левиафан 🐋", "hp": 600, "str": 60, "def": 35}, {"name": "Крашеный кракен 🦑", "hp": 700, "str": 70, "def": 40},
    {"name": "Древний бог морей 🔱", "hp": 800, "str": 80, "def": 45}, {"name": "Повелитель бездны 🌑", "hp": 1000, "str": 100, "def": 60},
]

# ==================== ТИРЫ КРАФТА ====================
CRAFT_TIERS = {
    1: {"name": "🔹 Базовый", "color": "🔹"},
    2: {"name": "🔸 Продвинутый", "color": "🔸"},
    3: {"name": "🔴 Элитный", "color": "🔴"},
    4: {"name": "👑 Легендарный", "color": "👑"},
}

# ==================== СЛОВАРЬ ТИПОВ ====================
ITEM_TYPES = {}
for _n, _i in SHOP_ITEMS.items(): ITEM_TYPES[_n] = _i["type"]
for _r in CRAFT_RECIPES: ITEM_TYPES[_r["name"]] = _r["type"]
for _r in "FEDCBAS":
    ITEM_TYPES[f"Сундук [{_r}] 📦"] = "chest"
    for _a in ARTIFACTS.get(_r, []):
        _fn = f"{_a['name']} [{_r}]"
        ITEM_BONUSES[_fn] = {"str": _a.get("str",0), "def": _a.get("def",0), "hp": _a.get("hp",0)}
        ITEM_TYPES[_fn] = "artifact"
    for _w in CHEST_WEAPONS.get(_r, []):
        _fn = f"{_w['name']} [{_r}]"
        ITEM_BONUSES[_fn] = {"str": _w.get("str",0)}
        ITEM_TYPES[_fn] = "weapon"
    for _a in CHEST_ARMOR.get(_r, []):
        _fn = f"{_a['name']} [{_r}]"
        ITEM_BONUSES[_fn] = {"def": _a.get("def",0), "hp": _a.get("hp",0)}
        ITEM_TYPES[_fn] = "armor"
ITEM_TYPES.update({"Компас мудреца 🧭": "accessory", "Амулет глубин 🌊": "accessory", "Корона чемпиона 👑": "accessory"})
SEAL_SKILLS_POOL = [
    {"name": "Критический удар ⚡", "effect": "crit_15", "desc": "15% шанс двойного урона"},
    {"name": "Толстая кожа 🛡️", "effect": "dmg_reduce_10", "desc": "-10% получаемого урона"},
    {"name": "Вампиризм 🩸", "effect": "lifesteal_5", "desc": "Восстанавливает 5% урона"},
    {"name": "Уклонение 💨", "effect": "dodge_10", "desc": "10% шанс увернуться"},
    {"name": "Берсерк 😤", "effect": "berserk", "desc": "+50% урона при HP<30%"},
    {"name": "Регенерация 💚", "effect": "regen", "desc": "+5 HP/час"},
    {"name": "Шипы 🌵", "effect": "thorns", "desc": "Отражает 20% урона"},
    {"name": "Двойной удар ⚔️", "effect": "double_strike", "desc": "10% шанс 2 атаки"},
]

JOBS = [
    {"name": "Рыболов 🎣", "desc": "Ловить рыбу", "reward_min": 20, "reward_max": 50, "cooldown_min": 30, "mood_cost": 5, "satiety_cost": 10},
    {"name": "Почтальон 📬", "desc": "Разносить почту", "reward_min": 30, "reward_max": 60, "cooldown_min": 45, "mood_cost": 8, "satiety_cost": 15},
    {"name": "Укротитель 🦭", "desc": "Укрощать морских зверей", "reward_min": 50, "reward_max": 100, "cooldown_min": 60, "mood_cost": 12, "satiety_cost": 20},
    {"name": "Водолаз 🤿", "desc": "Исследовать глубины", "reward_min": 40, "reward_max": 80, "cooldown_min": 50, "mood_cost": 10, "satiety_cost": 18},
    {"name": "Актёр 🎭", "desc": "Выступать в шоу", "reward_min": 35, "reward_max": 70, "cooldown_min": 40, "mood_cost": 6, "satiety_cost": 12},
]

FISH_TYPES = [
    {"name": "Малёк 🐤", "reward": (3, 8), "correct": "Подсечь!"}, {"name": "Окунь 🐟", "reward": (8, 15), "correct": "Подсечь!"},
    {"name": "Сёмга 🐠", "reward": (15, 25), "correct": "Ждать"}, {"name": "Золотая рыбка ✨", "reward": (30, 50), "correct": "Ждать"},
    {"name": "Краб 🦀", "reward": (10, 20), "correct": "Отпустить"},
]

DAILY_EVENTS = [
    {"event_type": "exp_boost", "effect": "1.5", "desc": "+50% к опыту!"},
    {"event_type": "shop_discount", "effect": "0.2", "desc": "Скидки 20% в магазине!"},
    {"event_type": "fishing_bonus", "effect": "2.0", "desc": "x2 рыбнеток за рыбалку!"},
]

FACTIONS = {
    "hunters": {"name": "Стая охотников 🎯", "desc": "Бонус за бои"},
    "fashion": {"name": "Клуб модников 💅", "desc": "Бонус к настроению"},
    "explorers": {"name": "Гильдия исследователей 🧭", "desc": "Бонус к опыту"},
}

RANDOM_ENCOUNTERS = [
    {"name": "Сундук на берегу! 📦", "type": "item", "chance": 0.12, "items": ["Чешуя 🐟", "Панцирь 🦀", "Акулий зуб 🦈", "Жемчуг 🫧", "Кость 🦴", "Кристалл 💎"]},
    {"name": "Злой краб! 🦀", "type": "battle", "chance": 0.10, "mood_cost": 10, "satiety_cost": 10, "drop": {"Панцирь 🦀": 0.5}},
    {"name": "Дружелюбный дельфин 🐬", "type": "hint", "chance": 0.08, "fishnet_reward": (10, 30)},
    {"name": "Затонувший корабль 🚢", "type": "fishnets", "chance": 0.06, "fishnet_reward": (30, 80)},
    {"name": "Кристальная пещера 💎", "type": "item", "chance": 0.05, "items": ["Кристалл 💎", "Лёд 🧊", "Светящаяся чешуя ✨"]},
    {"name": "Янтарный берег 🟡", "type": "item", "chance": 0.04, "items": ["Янтарь 🟡", "Кость 🦴", "Рог 🦏"]},
]

QUEST_TEMPLATES = [
    {"type": "play", "target": 3, "reward": 30, "desc": "Поиграть 3 раза"}, {"type": "feed", "target": 3, "reward": 30, "desc": "Покормить 3 раза"},
    {"type": "battle", "target": 1, "reward": 40, "desc": "Победить 1 босса"}, {"type": "dungeon", "target": 1, "reward": 50, "desc": "Пройти 1 подземелье"},
    {"type": "shop", "target": 1, "reward": 20, "desc": "Купить 1 предмет"}, {"type": "work", "target": 1, "reward": 35, "desc": "Отправить на работу"},
    {"type": "craft", "target": 1, "reward": 25, "desc": "Скрафтить 1 предмет"}, {"type": "fish", "target": 1, "reward": 25, "desc": "Поймать 1 рыбу"},
]

CLAN_EMOJIS = ["🦭", "🐋", "🦈", "🐙", "🦀", "🦐", "🦑", "🐬", "🐳", "🐢"]

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def _safe_int(value, default=0):
    if value is None: return default
    try: return int(value)
    except (ValueError, TypeError): return default

def get_player(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM players WHERE user_id=?", (uid,)); r = c.fetchone(); conn.close(); return r

def get_seal(sid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM seals WHERE seal_id=?", (sid,)); r = c.fetchone(); conn.close()
    if r: check_baby_growth(sid)
    return r

def get_player_seals(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM seals WHERE owner_id=?", (uid,)); r = c.fetchall(); conn.close(); return r

def get_seal_count(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM seals WHERE owner_id=?", (uid,)); r = c.fetchone(); conn.close()
    return _safe_int(r[0]) if r else 0

def update_seal(sid, **kw):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    s = ", ".join([f"{k}=?" for k in kw]); v = list(kw.values()) + [sid]
    c.execute(f"UPDATE seals SET {s} WHERE seal_id=?", v); conn.commit(); conn.close()

def update_player(uid, **kw):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    s = ", ".join([f"{k}=?" for k in kw]); v = list(kw.values()) + [uid]
    c.execute(f"UPDATE players SET {s} WHERE user_id=?", v); conn.commit(); conn.close()

def add_fishnets(uid, amt):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE players SET fishnets = COALESCE(fishnets, 0) + ? WHERE user_id=?", (amt, uid))
    conn.commit(); conn.close()

def get_fishnets(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT fishnets FROM players WHERE user_id=?", (uid,)); r = c.fetchone(); conn.close()
    return _safe_int(r[0]) if r else 0

def add_to_inv(uid, name, t, q=1):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT inv_id, quantity FROM inventory WHERE user_id=? AND item_name=?", (uid, name)); r = c.fetchone()
    if r: c.execute("UPDATE inventory SET quantity = quantity + ? WHERE inv_id=?", (q, r[0]))
    else: c.execute("INSERT INTO inventory (user_id, item_name, item_type, quantity) VALUES (?, ?, ?, ?)", (uid, name, t, q))
    conn.commit(); conn.close()

def get_inv(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM inventory WHERE user_id=? AND quantity > 0", (uid,)); r = c.fetchall(); conn.close(); return r

def get_item_qty(uid, name):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT quantity FROM inventory WHERE user_id=? AND item_name=?", (uid, name)); r = c.fetchone(); conn.close()
    return _safe_int(r[0]) if r else 0

def remove_from_inv(uid, name, q=1):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT inv_id, quantity FROM inventory WHERE user_id=? AND item_name=?", (uid, name)); r = c.fetchone()
    if r:
        nq = r[1] - q
        if nq <= 0: c.execute("DELETE FROM inventory WHERE inv_id=?", (r[0],))
        else: c.execute("UPDATE inventory SET quantity=? WHERE inv_id=?", (nq, r[0]))
        conn.commit()
    conn.close()

def get_sell_price(item_name):
    if item_name in SHOP_ITEMS: return int(SHOP_ITEMS[item_name]["price"] * 0.5)
    if item_name in RESOURCE_SELL_PRICES: return RESOURCE_SELL_PRICES[item_name]
    if item_name in POTION_SELL_PRICES: return POTION_SELL_PRICES[item_name]
    m = re.search(r'
$$
([A-Z])
$$
', item_name)
    if m and m.group(1) in RARITY_SELL_PRICES: return RARITY_SELL_PRICES[m.group(1)]
    for recipe in CRAFT_RECIPES:
        if recipe["name"] == item_name:
            total = sum(RESOURCE_SELL_PRICES.get(r, 5) * a for r, a in recipe["resources"].items())
            return int(total * 0.6)
    return 5

def exp_for_level(lvl): return lvl * 100 + (lvl - 1) * 50

def get_exp_mult():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT effect FROM active_events WHERE active=1 AND event_type='exp_boost' AND expires_at > ?", (now,)); r = c.fetchone(); conn.close()
    try: return float(r[0]) if r else 1.0
    except: return 1.0

def get_shop_disc():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT effect FROM active_events WHERE active=1 AND event_type='shop_discount' AND expires_at > ?", (now,)); r = c.fetchone(); conn.close()
    try: return float(r[0]) if r else 0.0
    except: return 0.0

def get_fish_bonus():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT effect FROM active_events WHERE active=1 AND event_type='fishing_bonus' AND expires_at > ?", (now,)); r = c.fetchone(); conn.close()
    try: return float(r[0]) if r else 1.0
    except: return 1.0

def get_seal_skills(sid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT skill_name, skill_effect FROM seal_skills WHERE seal_id=?", (sid,)); r = c.fetchall(); conn.close()
    return [{"name": row[0], "effect": row[1]} for row in r]

def uid_owner(sid):
    seal = get_seal(sid); return seal[1] if seal else 0

def check_levelup(sid):
    results = []
    while True:
        seal = get_seal(sid)
        if not seal or len(seal) < 11: break
        lvl = _safe_int(seal[9]); exp = _safe_int(seal[10]); needed = exp_for_level(lvl)
        if exp >= needed:
            nl = lvl + 1; ne = exp - needed
            hp_inc = random.randint(10, 20); new_max_hp = seal[4] + hp_inc
            update_seal(sid, level=nl, exp=ne, strength=seal[7]+random.randint(2,5), defense=seal[8]+random.randint(1,3), max_health=new_max_hp, health=new_max_hp)
            results.append(nl)
            if nl % 5 == 0:
                skill = random.choice(SEAL_SKILLS_POOL)
                conn = sqlite3.connect(DB_PATH); c = conn.cursor()
                c.execute("INSERT INTO seal_skills (seal_id, skill_name, skill_effect, acquired_at) VALUES (?, ?, ?, ?)", (sid, skill["name"], skill["effect"], datetime.now().isoformat()))
                conn.commit(); conn.close()
            uid = uid_owner(sid)
            if uid: update_quest_chain(uid, "reach_level", nl)
        else: break
    return results[-1] if results else False

def get_effective_stats(sid):
    seal = get_seal(sid)
    if not seal: return 0, 0, 0
    base_str = _safe_int(seal[7]); base_def = _safe_int(seal[8]); base_hp = _safe_int(seal[4])
    slots = [seal[13], seal[14], seal[15], seal[16], seal[17]]
    if len(seal) > 22 and seal[22]: slots.append(seal[22])
    bs = bd = bh = 0
    for item_name in slots:
        if not item_name: continue
        if item_name in ITEM_BONUSES:
            b = ITEM_BONUSES[item_name]; bs += _safe_int(b.get("str",0)); bd += _safe_int(b.get("def",0)); bh += _safe_int(b.get("hp",0))
    return base_str + bs, base_def + bd, base_hp + bh

def get_mood_bonus(sid):
    seal = get_seal(sid)
    if not seal or len(seal) < 18: return 0
    acc = seal[17]
    return _safe_int(ACCESSORY_BONUSES.get(acc, 0)) if acc else 0

def can_craft(uid, recipe): return all(get_item_qty(uid, r) >= a for r, a in recipe["resources"].items())

def get_faction_disc(uid):
    p = get_player(uid)
    if not p or len(p) < 7 or not p[5]: return 0.0
    rep = _safe_int(p[6])
    if rep >= 100: return 0.30
    elif rep >= 50: return 0.15
    elif rep >= 20: return 0.05
    return 0.0

def add_faction_rep(uid, amt):
    p = get_player(uid)
    if not p or len(p) < 7: return
    update_player(uid, faction_rep=_safe_int(p[6]) + amt)

def get_floor_monster(fl, mon_idx):
    base_idx = (fl - 1 + mon_idx) % len(DUNGEON_MONSTERS)
    m = DUNGEON_MONSTERS[base_idx].copy()
    config = DUNGEON_FLOORS_CONFIG[min(fl - 1, len(DUNGEON_FLOORS_CONFIG) - 1)]
    m["hp"] = int(m["hp"] * config["hp_mult"])
    m["str"] = int(m["str"] * config["str_mult"])
    m["def"] = int(m["def"] * (1 + (fl - 1) * 0.1))
    return m

def process_drops(uid, drops):
    d = []
    if not drops: return d
    for res, ch in drops.items():
        if random.random() < ch:
            q = random.randint(1, 2); add_to_inv(uid, res, "resource", q); d.append(f"{res} x{q}")
    return d

def check_baby_growth(sid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT is_baby, born_at FROM seals WHERE seal_id=?", (sid,))
    r = c.fetchone()
    if r and r[0] == 1 and r[1]:
        try:
            born = datetime.fromisoformat(r[1])
            if (datetime.now() - born).days >= BABY_GROW_DAYS:
                c.execute("UPDATE seals SET is_baby=0, strength=strength+5, defense=defense+3, max_health=max_health+20, health=max_health+20 WHERE seal_id=?", (sid,))
                conn.commit()
        except: pass
    conn.close()

def get_married_ids():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT seal1_id FROM marriages UNION SELECT seal2_id FROM marriages")
    ids = set(r[0] for r in c.fetchall()); conn.close(); return ids

def get_seal_status(seal, married):
    if not seal: return "❓"
    if _safe_int(seal[11]) == 1: return "🍼"
    if _safe_int(seal[3]) <= 0: return "💀"
    mood = _safe_int(seal[5]); satiety = _safe_int(seal[6])
    if mood < 30 or satiety < 20: return "😴"
    if seal[0] in married: return "❤️"
    wc = seal[18]
    if wc:
        try:
            cm = _safe_int(seal[21]) if len(seal) > 21 else 30
            if datetime.now() - datetime.fromisoformat(wc) < timedelta(minutes=cm): return "💼"
        except: pass
    if mood >= 50 and satiety >= 50: return "🎮"
    return "🦭"

def get_active_event_text():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT event_type FROM active_events WHERE active=1 AND expires_at > ?", (now,)); r = c.fetchone(); conn.close()
    if not r: return None
    for ev in DAILY_EVENTS:
        if ev["event_type"] == r[0]: return ev["desc"]
    return None

def get_todays_event():
    seed = int(date.today().strftime("%Y%m%d"))
    return random.Random(seed).choice(DAILY_EVENTS)

def check_vote_result():
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT vote, COUNT(*) FROM votes WHERE date=? GROUP BY vote", (today,)); rows = c.fetchall(); conn.close()
    y = n = 0
    for v, cnt in rows:
        if v == "yes": y = cnt
        elif v == "no": n = cnt
    return (y + n) >= 3 and y > n

def activate_event(et, eff):
    exp = datetime.now() + timedelta(hours=24)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE active_events SET active=0 WHERE active=1")
    c.execute("INSERT INTO active_events (event_type, effect, expires_at, active) VALUES (?, ?, ?, 1)", (et, eff, exp.isoformat()))
    conn.commit(); conn.close()

def get_quest_chains():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM quest_chains"); r = c.fetchall(); conn.close(); return r

def get_player_chain(uid, chain_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM player_quest_chains WHERE user_id=? AND chain_id=?", (uid, chain_id)); r = c.fetchone(); conn.close(); return r

def update_quest_chain(uid, step_type, amount=1):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT id, chain_id, current_step, step_progress, completed FROM player_quest_chains WHERE user_id=? AND completed=0", (uid,))
    for pc_id, cid, cs, sp, comp in c.fetchall():
        c2 = conn.cursor()
        c2.execute("SELECT steps_json FROM quest_chains WHERE chain_id=?", (cid,)); chain = c2.fetchone()
        if not chain: continue
        try: steps = json.loads(chain[0])
        except json.JSONDecodeError: continue
        if cs < len(steps) and steps[cs]["type"] == step_type:
            ns = sp + 1
            if ns >= steps[cs]["target"]:
                ns = 0; cs2 = cs + 1
                if cs2 >= len(steps): c2.execute("UPDATE player_quest_chains SET completed=1 WHERE id=?", (pc_id,))
                else: c2.execute("UPDATE player_quest_chains SET current_step=?, step_progress=0 WHERE id=?", (cs2, pc_id))
            else: c2.execute("UPDATE player_quest_chains SET step_progress=? WHERE id=?", (ns, pc_id))
    conn.commit(); conn.close()

def get_clan_by_user(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT clans.* FROM clans JOIN clan_members ON clans.clan_id=clan_members.clan_id WHERE clan_members.user_id=?", (uid,)); r = c.fetchone(); conn.close(); return r

def get_clan_members(cid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT user_id FROM clan_members WHERE clan_id=?", (cid,)); r = c.fetchall(); conn.close(); return [row[0] for row in r]

def trigger_encounter(uid):
    enc = random.choice(RANDOM_ENCOUNTERS)
    if random.random() > enc["chance"]: return None
    msg = f"✨ Случайное событие!\n{enc['name']}\n"
    if enc["type"] == "item":
        item = random.choice(enc["items"]); add_to_inv(uid, item, "resource", 1); msg += f"Получен предмет: {item}!"
    elif enc["type"] == "fishnets":
        r = random.randint(*enc["fishnet_reward"]); add_fishnets(uid, r); msg += f"Найдено 🐟{r}!"
    elif enc["type"] == "battle":
        seals = get_player_seals(uid)
        if seals:
            s = seals[0]
            new_mood = max(0, _safe_int(s[5]) - enc.get("mood_cost", 0))
            new_satiety = max(0, _safe_int(s[6]) - enc.get("satiety_cost", 0))
            update_seal(s[0], mood=new_mood, satiety=new_satiety)
            msg += "Тюлень потерял настроение и сытость!"
            if "drop" in enc:
                d = process_drops(uid, enc["drop"])
                if d: msg += f"\nНо добыча: {', '.join(d)}"
    elif enc["type"] == "hint":
        r = random.randint(*enc["fishnet_reward"]); add_fishnets(uid, r); msg += f"Дельфин подсказал секрет! 🐟{r}"
    return msg

def create_duel(cid, oid, csid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO duels (challenger_id, opponent_id, challenger_seal_id, status, created_at) VALUES (?, ?, ?, 'pending', ?)", (cid, oid, csid, datetime.now().isoformat()))
    conn.commit(); did = c.lastrowid; conn.close(); return did

def get_duel(did):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM duels WHERE duel_id=?", (did,)); r = c.fetchone(); conn.close(); return r

def generate_daily_quests(uid):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM daily_quests WHERE user_id=? AND date=?", (uid, today))
    if c.fetchall(): conn.close(); return
    c.execute("DELETE FROM daily_quests WHERE user_id=? AND date!=?", (uid, today))
    for q in random.sample(QUEST_TEMPLATES, 3):
        c.execute("INSERT INTO daily_quests (user_id,quest_type,quest_target,quest_progress,quest_reward,date,claimed) VALUES (?,?,?,?,0,?,0)", (uid, q["type"], q["target"], q["reward"], today))
    conn.commit(); conn.close()

def update_quest_progress(uid, qt, amt=1):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT quest_id,quest_progress,quest_target FROM daily_quests WHERE user_id=? AND quest_type=? AND date=? AND claimed=0", (uid, qt, today))
    for qid, prog, targ in c.fetchall():
        if prog < targ: c.execute("UPDATE daily_quests SET quest_progress=? WHERE quest_id=?", (min(targ, prog + amt), qid))
    conn.commit(); conn.close()

def get_daily_quests(uid):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM daily_quests WHERE user_id=? AND date=?", (uid, today)); r = c.fetchall(); conn.close(); return r

def open_chest(uid, rarity):
    chest_name = f"Сундук [{rarity}] 📦"
    if get_item_qty(uid, chest_name) <= 0: return "Нет сундука!"
    remove_from_inv(uid, chest_name)
    fn_range = CHEST_CONTENTS.get(rarity, {"fishnets": (10, 30)})
    fishnets = random.randint(fn_range["fishnets"][0], fn_range["fishnets"][1])
    add_fishnets(uid, fishnets)
    msg = f"📦 Сундук [{rarity}] открыт!\n🐟 {fishnets}\n"
    roll = random.random()
    if roll < 0.25:
        art = random.choice(ARTIFACTS.get(rarity, []))
        fn = f"{art['name']} [{rarity}]"; add_to_inv(uid, fn, "artifact", 1); msg += f"✨ Артефакт: {fn}\n"
    elif roll < 0.55:
        w = random.choice(CHEST_WEAPONS.get(rarity, []))
        fn = f"{w['name']} [{rarity}]"; add_to_inv(uid, fn, "weapon", 1); msg += f"⚔️ Оружие: {fn}\n"
    elif roll < 0.80:
        a = random.choice(CHEST_ARMOR.get(rarity, []))
        fn = f"{a['name']} [{rarity}]"; add_to_inv(uid, fn, "armor", 1); msg += f"🛡️ Броня: {fn}\n"
    return msg
# ==================== ОБРАБОТЧИКИ ====================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.from_user.id; uname = message.from_user.username or message.from_user.first_name
    p = get_player(uid)
    if not p:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("INSERT INTO players (user_id,username,display_name,fishnets) VALUES (?,?,?,100)", (uid, uname, uname))
        conn.commit(); conn.close()
        sn = random.choice(["Никифор","Плюха","Шлёпа","Бубль","Тюня","Фрэнк","Сэм"])
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("INSERT INTO seals (owner_id,name,health,max_health,mood,satiety,strength,defense,level,exp) VALUES (?,?,100,100,80,80,10,5,1,0)", (uid, sn))
        conn.commit(); conn.close()
        bot.send_message(uid, f"Добро пожаловать в Мир Тюленей! 🦭\n\nТюлень {sn} и 100 рыбнеток 🐟 ваши!")
    else:
        bot.send_message(uid, "С возвращением! 🦭")
    show_main_menu(uid)

@bot.message_handler(commands=['help'])
def cmd_help(message):
    uid = message.from_user.id
    t = ("🦭 *Справка*\n\n*Основные:*\n/start /help /profile /gallery /setphoto /leaderboard\n"
         "/inventory — инвентарь и ресурсы\n/sell — продажа предметов\n\n"
         "*Тюлень:*\n🦭 Мой тюлень — карточка\n\n"
         "*Экономика:*\n/shop /craft /trade — биржа\n\n"
         "*Сражения:*\n/battle /dungeon /work /duel\n\n"
         "*Активности:*\n/fish /vote /faction /marry /quests\n"
         "/questchain /clan\n\n"
         "*Крафт:* 4 тира, 50+ рецептов, зелья!\n"
         "*Подземелье:* 10 этажей, 25+ монстров, сундуки и артефакты!\n"
         "*Регенерация:* +25 HP/час | Навык каждые 5 уровней\n"
         "*Тюленята:* растут через 3 дня")
    bot.send_message(uid, t, parse_mode='Markdown'); show_main_menu(uid)

def show_main_menu(uid):
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add(types.KeyboardButton("🦭 Мой тюлень"), types.KeyboardButton("👤 Профиль"))
    m.add(types.KeyboardButton("🎒 Инвентарь"), types.KeyboardButton("🛒 Магазин"))
    m.add(types.KeyboardButton("⚔️ Бой"), types.KeyboardButton("🏰 Подземелье"))
    m.add(types.KeyboardButton("💼 Работа"), types.KeyboardButton("🔨 Крафт"))
    m.add(types.KeyboardButton("📋 Задания"), types.KeyboardButton("💍 Брак"))
    m.add(types.KeyboardButton("🎣 Рыбалка"), types.KeyboardButton("🏆 Лидеры"))
    m.add(types.KeyboardButton("📦 Биржа"), types.KeyboardButton("🏛 Фракции"))
    m.add(types.KeyboardButton("🤺 Дуэль"), types.KeyboardButton("📚 Цепочки"))
    m.add(types.KeyboardButton("🐋 Клан"), types.KeyboardButton("💰 Продажа"))
    bot.send_message(uid, "Выберите действие:", reply_markup=m)

@bot.message_handler(commands=['profile'])
@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def cmd_profile(message):
    uid = message.from_user.id; p = get_player(uid)
    if not p: bot.send_message(uid, "Напишите /start"); return
    cnt = get_seal_count(uid); fn = p[4]
    fn2 = FACTIONS[p[5]]["name"] if p[5] and p[5] in FACTIONS else "Нет"
    t = f"👤 *Ваш профиль*\n\nТюленей: {cnt}/{MAX_SEALS}\nРыбнетки: 🐟 {fn}\nФракция: {fn2}"
    if p[5]: t += f" (репутация: {p[6]})"
    t += "\n"
    clan = get_clan_by_user(uid)
    if clan: t += f"Клан: {clan[2]} {clan[3]}\n"
    ev = get_active_event_text()
    if ev: t += f"\n🎉 Активное событие: {ev}\n"
    seals = get_player_seals(uid)
    if seals:
        t += "\n*Ваши тюлени:*\n"
        for s in seals:
            check_baby_growth(s[0])
            es, ed, eh = get_effective_stats(s[0])
            skills = get_seal_skills(s[0])
            baby = " 🍼" if s[11] == 1 else ""
            t += f"\n🦭 *{s[2]}* (ур.{s[9]}){baby}\n"
            t += f"  ❤️ {s[3]}/{s[4]} (экип:{eh})\n  💪 {s[7]} (экип:{es})\n  🛡️ {s[8]} (экип:{ed})\n"
            if skills: t += f"  ✨ {', '.join(sk['name'] for sk in skills)}\n"
    bot.send_message(uid, t, parse_mode='Markdown')

@bot.message_handler(commands=['gallery'])
def cmd_gallery(message):
    uid = message.from_user.id; seals = get_player_seals(uid)
    if not seals: bot.send_message(uid, "Нет тюленей! /start"); return
    married = get_married_ids(); fn = get_fishnets(uid)
    t = f"🖼 *Галерея*\n🐟 {fn}\n\n"
    for s in seals:
        check_baby_growth(s[0]); st = get_seal_status(s, married)
        skills = get_seal_skills(s[0]); baby = " 🍼(растёт)" if s[11] == 1 else ""
        t += f"{st} *{s[2]}* — ур.{s[9]}{baby}\n  💪{s[7]} 🛡️{s[8]} 🍖{s[6]} ❤️{s[3]}/{s[4]}\n"
        if skills: t += f"  Навыки: {', '.join(sk['name'] for sk in skills)}\n"
        t += "\n"
    bot.send_message(uid, t, parse_mode='Markdown')

@bot.message_handler(commands=['leaderboard'])
@bot.message_handler(func=lambda m: m.text == "🏆 Лидеры")
def cmd_leaderboard(message):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT seals.name,seals.level,players.username FROM seals JOIN players ON seals.owner_id=players.user_id ORDER BY seals.level DESC,seals.exp DESC LIMIT 20")
    rows = c.fetchall(); conn.close()
    if not rows: bot.send_message(message.from_user.id, "Пусто!"); return
    t = "🏆 *Лидеры*\n\n"; medals = ["🥇","🥈","🥉"]
    for i, (n, l, u) in enumerate(rows):
        t += f"{medals[i] if i < 3 else str(i+1)+'.'} {n} — ур.{l} (@{u})\n"
    bot.send_message(message.from_user.id, t, parse_mode='Markdown')

@bot.message_handler(commands=['inventory'])
@bot.message_handler(func=lambda m: m.text == "🎒 Инвентарь")
def cmd_inventory(message):
    uid = message.from_user.id; inv = get_inv(uid)
    if not inv: bot.send_message(uid, "Инвентарь пуст!"); return
    t = "🎒 *Инвентарь*\n\n"
    cats = {"food":"🍴 Еда","medkit":"💊 Медицина","weapon":"⚔️ Оружие","armor":"🛡️ Броня",
            "helmet":"🪖 Шлемы","shield":"🛡️ Щиты","accessory":"🎀 Аксессуары",
            "resource":"📦 Ресурсы","artifact":"✨ Артефакты","chest":"📦 Сундуки","potion":"🧪 Зелья"}
    grouped = {}
    for item in inv: grouped.setdefault(item[3], []).append(item)
    for cat, label in cats.items():
        items = grouped.get(cat, [])
        if items:
            t += f"*{label}:*\n"
            for i in items:
                sp = get_sell_price(i[2])
                t += f"  {i[2]} (x{i[4]}) — 🐟{sp}\n"
            t += "\n"
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("💰 Продать предметы", callback_data="sellmenu"))
    m.add(types.InlineKeyboardButton("📦 Открыть сундуки", callback_data="chestmenu"))
    m.add(types.InlineKeyboardButton("🧪 Использовать зелье", callback_data="potionmenu"))
    bot.send_message(uid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data == "sellmenu")
def sell_menu(call):
    uid = call.from_user.id; inv = get_inv(uid)
    if not inv: bot.answer_callback_query(call.id, "Пусто!"); return
    m = types.InlineKeyboardMarkup()
    for i in inv:
        sp = get_sell_price(i[2])
        if sp > 0:
            m.add(types.InlineKeyboardButton(f"{i[2]} x{i[4]} — 🐟{sp}/шт", callback_data=f"sellitem_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="invback"))
    bot.edit_message_text("💰 Что продать?", call.message.chat.id, call.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sellitem_"))
def sell_do(call):
    uid = call.from_user.id; name = call.data[10:]
    qty = get_item_qty(uid, name)
    if qty <= 0: bot.answer_callback_query(call.id, "Нет!"); return
    sp = get_sell_price(name)
    if sp <= 0: bot.answer_callback_query(call.id, "Нельзя продать!"); return
    remove_from_inv(uid, name, 1); add_fishnets(uid, sp)
    bot.answer_callback_query(call.id, f"Продано {name} за 🐟{sp}!")

@bot.callback_query_handler(func=lambda c: c.data == "chestmenu")
def chest_menu(call):
    uid = call.from_user.id; inv = get_inv(uid)
    chests = [i for i in inv if i[3] == "chest"]
    if not chests: bot.answer_callback_query(call.id, "Нет сундуков!"); return
    m = types.InlineKeyboardMarkup()
    for i in chests: m.add(types.InlineKeyboardButton(f"Открыть {i[2]} (x{i[4]})", callback_data=f"openchest_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="invback"))
    bot.edit_message_text("📦 Какие сундуки открыть?", call.message.chat.id, call.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("openchest_"))
def open_chest_do(call):
    uid = call.from_user.id; chest_name = call.data[10:]
    m = re.search(r'
$$
([A-Z])
$$
', chest_name)
    if not m: bot.answer_callback_query(call.id, "Ошибка!"); return
    result = open_chest(uid, m.group(1))
    bot.answer_callback_query(call.id, result[:100])

@bot.callback_query_handler(func=lambda c: c.data == "potionmenu")
def potion_menu(call):
    uid = call.from_user.id; inv = get_inv(uid)
    potions = [i for i in inv if i[3] == "potion"]
    if not potions: bot.answer_callback_query(call.id, "Нет зелий!"); return
    seals = get_player_seals(uid)
    if not seals: bot.answer_callback_query(call.id, "Нет тюленей!"); return
    m = types.InlineKeyboardMarkup()
    for p in potions:
        eff = POTION_EFFECTS.get(p[2], {})
        desc = ""
        if eff.get("stat") == "heal_full": desc = "полное лечение"
        elif eff.get("stat") == "heal": desc = f"+{eff.get('amount',0)} HP"
        elif eff.get("stat") == "str": desc = f"+{eff.get('amount',0)} силы"
        elif eff.get("stat") == "def": desc = f"+{eff.get('amount',0)} защиты"
        else: desc = eff.get("stat", "эффект")
        m.add(types.InlineKeyboardButton(f"{p[2]} x{p[4]} ({desc})", callback_data=f"ptsel_{p[2]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="invback"))
    bot.edit_message_text("🧪 Какое зелье использовать?", call.message.chat.id, call.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("ptsel_"))
def potion_select_seal(call):
    uid = call.from_user.id; pname = call.data[6:]
    seals = get_player_seals(uid)
    if not seals: bot.answer_callback_query(call.id, "Нет тюленей!"); return
    m = types.InlineKeyboardMarkup()
    for s in seals: m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"ptuse_{s[0]}_{pname}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="potionmenu"))
    bot.edit_message_text("Кому дать зелье?", call.message.chat.id, call.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("ptuse_"))
def potion_use(call):
    uid = call.from_user.id; p = call.data.split("_"); sid = int(p[1]); pname = "_".join(p[2:])
    if get_item_qty(uid, pname) <= 0: bot.answer_callback_query(call.id, "Нет зелья!"); return
    seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Нет тюленя!"); return
    eff = POTION_EFFECTS.get(pname, {})
    stat = eff.get("stat"); amt = eff.get("amount", 0)
    msg = f"🧪 {seal[2]} выпил {pname}!\n"
    if stat == "heal_full":
        update_seal(sid, health=seal[4]); msg += "❤️ Полное лечение!"
    elif stat == "heal":
        update_seal(sid, health=min(seal[4], seal[3]+amt)); msg += f"❤️ +{amt} HP!"
    elif stat == "str":
        update_seal(sid, strength=seal[7]+amt); msg += f"💪 +{amt} силы (временно)!"
    elif stat == "def":
        update_seal(sid, defense=seal[8]+amt); msg += f"🛡️ +{amt} защиты (временно)!"
    elif stat == "berserk":
        msg += "😤 Режим берсерка активирован!"
    elif stat == "freeze":
        msg += "🧊 Способность заморозки получена!"
    elif stat == "dodge":
        msg += f"💨 +{amt}% к уклонению!"
    elif stat == "poison":
        msg += f"☠️ Отравление на {amt} урона!"
    elif stat == "light":
        msg += "✨ Подземелье освещено!"
    else:
        msg += "Эффект применён!"
    remove_from_inv(uid, pname)
    bot.answer_callback_query(call.id, msg[:100])

@bot.callback_query_handler(func=lambda c: c.data == "invback")
def inv_back(call):
    uid = call.from_user.id; inv = get_inv(uid)
    if not inv: bot.send_message(call.from_user.id, "Пусто!"); return
    t = "🎒 *Инвентарь*\n\n"
    cats = {"food":"🍴 Еда","medkit":"💊","weapon":"⚔️","armor":"🛡️","helmet":"🪖","shield":"🛡️","accessory":"🎀","resource":"📦","artifact":"✨","chest":"📦","potion":"🧪"}
    grouped = {}
    for item in inv: grouped.setdefault(item[3], []).append(item)
    for cat, label in cats.items():
        items = grouped.get(cat, [])
        if items:
            t += f"*{label}:*\n"
            for i in items: t += f"  {i[2]} (x{i[4]})\n"
            t += "\n"
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("💰 Продать", callback_data="sellmenu"))
    m.add(types.InlineKeyboardButton("📦 Сундуки", callback_data="chestmenu"))
    m.add(types.InlineKeyboardButton("🧪 Зелья", callback_data="potionmenu"))
    bot.edit_message_text(t, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=m)

@bot.message_handler(func=lambda m: m.text == "💰 Продажа")
def menu_sell(message):
    uid = message.from_user.id; inv = get_inv(uid)
    if not inv: bot.send_message(uid, "Инвентарь пуст!"); return
    t = "💰 *Продажа предметов*\n\n"
    m = types.InlineKeyboardMarkup()
    for i in inv:
        sp = get_sell_price(i[2])
        if sp > 0:
            t += f"  {i[2]} x{i[4]} — 🐟{sp}/шт\n"
            m.add(types.InlineKeyboardButton(f"Продать {i[2]} (🐟{sp})", callback_data=f"sellitem_{i[2]}"))
    m.add(types.InlineKeyboardButton("📦 Открыть сундуки", callback_data="chestmenu"))
    bot.send_message(uid, t, parse_mode='Markdown', reply_markup=m)
@bot.message_handler(commands=['setphoto'])
def cmd_setphoto(message):
    uid = message.from_user.id; seals = get_player_seals(uid)
    if not seals: bot.send_message(uid, "Нет тюленей!"); return
    m = types.InlineKeyboardMarkup()
    for s in seals: m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"sphoto_{s[0]}"))
    bot.send_message(uid, "📸 Выберите тюленя:", reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sphoto_"))
def sphoto_sel(call):
    sid = int(call.data.split("_")[1])
    bot.send_message(call.from_user.id, "Отправьте фото:")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, lambda m: proc_seal_photo(m, sid))

def proc_seal_photo(message, sid):
    uid = message.from_user.id
    if not message.photo: bot.send_message(uid, "Не фото!"); return
    try:
        fi = bot.get_file(message.photo[-1].file_id); dl = bot.download_file(fi.file_path)
        os.makedirs("photos", exist_ok=True); p = f"photos/seal_{sid}.jpg"
        with open(p, 'wb') as f: f.write(dl)
        update_seal(sid, photo_path=p); bot.send_message(uid, "✅ Фото обновлено!")
    except Exception as e: bot.send_message(uid, f"❌ {e}")

@bot.message_handler(func=lambda m: m.text == "🦭 Мой тюлень")
def menu_seal(message):
    uid = message.from_user.id; seals = get_player_seals(uid)
    if not seals: bot.send_message(uid, "Нет тюленей! /start"); return
    m = types.InlineKeyboardMarkup()
    for s in seals:
        check_baby_growth(s[0]); baby = " 🍼" if s[11] == 1 else ""
        m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]}){baby}", callback_data=f"sinfo_{s[0]}"))
    bot.send_message(uid, "Выберите тюленя:", reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sinfo_"))
def seal_selected(call, sid=None):
    if sid is None: sid = int(call.data.split("_")[1])
    check_baby_growth(sid); seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    uid = call.from_user.id; fn = get_fishnets(uid)
    es, ed, eh = get_effective_stats(sid); mb = get_mood_bonus(sid); skills = get_seal_skills(sid)
    t = f"🦭 *{seal[2]}*\n🐟 Рыбнетки: {fn}\n\n📊 Ур:{seal[9]} (оп:{seal[10]}/{exp_for_level(seal[9])})\n"
    t += f"❤️ {seal[3]}/{seal[4]}"+(f" (экип:{eh})" if eh!=seal[4] else "")+"\n"
    t += f"😊 {seal[5]}"+(f" (+{mb})" if mb>0 else "")+f"\n🍖 {seal[6]}\n💪 {seal[7]}"+(f" (экип:{es})" if es!=seal[7] else "")+f"\n🛡️ {seal[8]}"+(f" (экип:{ed})" if ed!=seal[8] else "")+"\n"
    if skills:
        t += "\n*Навыки:*\n"
        for sk in skills: t += f"  {sk['name']}\n"
    eq = []
    if seal[13]: eq.append(f"⚔️{seal[13]}")
    if seal[14]: eq.append(f"🛡️{seal[14]}")
    if seal[15]: eq.append(f"🪖{seal[15]}")
    if seal[16]: eq.append(f"🛡️{seal[16]}")
    if seal[17]: eq.append(f"🎀{seal[17]}")
    if len(seal) > 22 and seal[22]: eq.append(f"✨{seal[22]}")
    t += f"\n🎒 Экип: {', '.join(eq) if eq else 'нет'}\n"
    if seal[11] == 1:
        try:
            born = datetime.fromisoformat(seal[12]); days_left = BABY_GROW_DAYS - (datetime.now() - born).days
            t += f"\n🍼 Тюленёнок! Вырастет через {max(0, days_left)} дн.\n"
        except: t += "\n🍼 Тюленёнок!\n"
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🍖 Кормить", callback_data=f"feed_{sid}"), types.InlineKeyboardButton("🎾 Играть", callback_data=f"play_{sid}"))
    m.add(types.InlineKeyboardButton("💊 Лечить", callback_data=f"heal_{sid}"), types.InlineKeyboardButton("👕 Экип", callback_data=f"equip_{sid}"))
    m.add(types.InlineKeyboardButton("📸 Фото", callback_data=f"sphoto_{sid}"), types.InlineKeyboardButton("✏️ Имя", callback_data=f"rename_{sid}"))
    m.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back_main"))
    cid = call.message.chat.id; mid = call.message.message_id; pp = seal[20]
    if pp and os.path.exists(pp):
        try: bot.delete_message(cid, mid)
        except: pass
        try:
            with open(pp, 'rb') as f: bot.send_photo(cid, f, caption=t, reply_markup=m, parse_mode='Markdown')
        except: bot.send_message(cid, t, reply_markup=m, parse_mode='Markdown')
    else:
        try: bot.edit_message_text(t, cid, mid, reply_markup=m, parse_mode='Markdown')
        except: bot.send_message(cid, t, reply_markup=m, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("feed_"))
def seal_feed(call):
    uid = call.from_user.id; sid = int(call.data.split("_")[1]); inv = get_inv(uid)
    food = [i for i in inv if i[3] == "food"]
    if not food: bot.answer_callback_query(call.id, "Нет еды!"); return
    m = types.InlineKeyboardMarkup()
    for i in food:
        info = SHOP_ITEMS.get(i[2], {})
        m.add(types.InlineKeyboardButton(f"{i[2]} (x{i[4]}) +{info.get('satiety',0)}", callback_data=f"dfd_{sid}_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data=f"sinfo_{sid}"))
    bot.edit_message_text("Чем кормить?", call.message.chat.id, call.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dfd_"))
def seal_do_feed(call):
    uid = call.from_user.id; p = call.data.split("_"); sid = int(p[1]); name = "_".join(p[2:])
    info = SHOP_ITEMS.get(name)
    if not info: bot.answer_callback_query(call.id, "Не найден!"); return
    seal = get_seal(sid)
    if not seal: return
    update_seal(sid, satiety=min(100,seal[6]+info["satiety"]), mood=min(100,seal[5]+info.get("mood",5)))
    remove_from_inv(uid, name); bot.answer_callback_query(call.id, f"{seal[2]} съел {name}!")
    update_quest_progress(uid, "feed", 1); seal_selected(call, sid)

@bot.callback_query_handler(func=lambda c: c.data.startswith("heal_"))
def seal_heal(call):
    uid = call.from_user.id; sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal: return
    if seal[3] >= seal[4]: bot.answer_callback_query(call.id, "Здоров!"); return
    if get_item_qty(uid, "Аптечка 💊") <= 0: bot.answer_callback_query(call.id, "Нет аптечек!"); return
    h = SHOP_ITEMS["Аптечка 💊"]["heal"]
    update_seal(sid, health=min(seal[4],seal[3]+h)); remove_from_inv(uid, "Аптечка 💊")
    bot.answer_callback_query(call.id, f"💊 +{h} HP!"); seal_selected(call, sid)

@bot.callback_query_handler(func=lambda c: c.data.startswith("play_"))
def seal_play(call):
    uid = call.from_user.id; sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal: return
    if seal[6] < 10: bot.answer_callback_query(call.id, "Голоден!"); return
    wc = seal[19]
    if wc:
        try:
            rem = timedelta(minutes=PLAY_COOLDOWN_MIN) - (datetime.now() - datetime.fromisoformat(wc))
            if rem.total_seconds() > 0:
                bot.answer_callback_query(call.id, f"⏳ {int(rem.total_seconds()//60)}м {int(rem.total_seconds()%60)}с"); return
        except: pass
    eg = int(random.randint(5,15) * get_exp_mult())
    update_seal(sid, mood=min(100,seal[5]+25), satiety=max(0,seal[6]-5), exp=seal[10]+eg, play_cooldown=datetime.now().isoformat())
    lv = check_levelup(sid); update_quest_progress(uid, "play", 1)
    p = get_player(uid)
    if p and p[5] == "fashion": add_faction_rep(uid, 1)
    msg = f"🎾 Поиграли! +25😊 +{eg}оп"
    if lv: msg += f"\n🎉 Ур.{lv}!"
    enc = trigger_encounter(uid)
    if enc: msg += f"\n\n{enc}"
    bot.answer_callback_query(call.id, msg); seal_selected(call, sid)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rename_"))
def seal_rename(call):
    sid = int(call.data.split("_")[1])
    bot.send_message(call.from_user.id, "Новое имя:")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, lambda m: proc_rename(m, sid))

def proc_rename(message, sid):
    nn = message.text.strip()
    if len(nn) > 20: bot.send_message(message.from_user.id, "Слишком длинное!"); return
    update_seal(sid, name=nn); bot.send_message(message.from_user.id, f"✅ {nn}!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("equip_"))
def seal_equip_menu(call):
    uid = call.from_user.id; sid = int(call.data.split("_")[1]); inv = get_inv(uid)
    gt = ("weapon","armor","helmet","shield","accessory","artifact")
    gi = [i for i in inv if ITEM_TYPES.get(i[3]) in gt or i[3] in gt]
    if not gi: bot.answer_callback_query(call.id, "Нет экипировки!"); return
    m = types.InlineKeyboardMarkup()
    for i in gi: m.add(types.InlineKeyboardButton(f"{i[2]} (x{i[4]})", callback_data=f"deq_{sid}_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data=f"sinfo_{sid}"))
    bot.edit_message_text("Что надеть?", call.message.chat.id, call.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("deq_"))
def seal_do_equip(call):
    uid = call.from_user.id; p = call.data.split("_"); sid = int(p[1]); name = "_".join(p[2:])
    it = ITEM_TYPES.get(name)
    if not it: bot.answer_callback_query(call.id, "Не найден!"); return
    seal = get_seal(sid)
    if not seal: return
    if it == "artifact":
        slot = "equipped_artifact"; ci = 22
    else:
        sm = {"weapon":"equipped_weapon","armor":"equipped_armor","helmet":"equipped_helmet","shield":"equipped_shield","accessory":"equipped_accessory"}
        slot = sm.get(it)
        if not slot: bot.answer_callback_query(call.id, "Неизвестный тип!"); return
        ci = {"equipped_weapon":13,"equipped_armor":14,"equipped_helmet":15,"equipped_shield":16,"equipped_accessory":17}.get(slot)
    cv = seal[ci] if ci is not None and len(seal) > ci else None
    if cv: add_to_inv(uid, cv, ITEM_TYPES.get(cv, "armor"), 1)
    update_seal(sid, **{slot: name}); remove_from_inv(uid, name)
    pl = get_player(uid)
    if pl and pl[5] == "fashion" and it == "accessory": add_faction_rep(uid, 2)
    bot.answer_callback_query(call.id, f"Надето: {name}"); seal_selected(call, sid)

@bot.callback_query_handler(func=lambda c: c.data == "back_main")
def back_to_main(call):
    show_main_menu(call.from_user.id)
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except: pass

@bot.message_handler(commands=['shop'])
@bot.message_handler(func=lambda m: m.text == "🛒 Магазин")
def menu_shop(message):
    uid = message.from_user.id; fn = get_fishnets(uid)
    td = max(get_shop_disc(), get_faction_disc(uid))
    t = f"🛒 *Магазин*\n🐟 {fn}\n"+(f"Скидка: {int(td*100)}%\n" if td>0 else "")+"\n"
    m = types.InlineKeyboardMarkup(row_width=1)
    for n, i in SHOP_ITEMS.items():
        pr = int(i["price"]*(1-td))
        if i["type"]=="food": t += f"  {n} — 🐟{pr} (+{i['satiety']})\n"
        elif i["type"]=="medkit": t += f"  {n} — 🐟{pr} (+{i['heal']}HP)\n"
        elif i["type"]=="accessory": t += f"  {n} — 🐟{pr} (+{ACCESSORY_BONUSES.get(n,0)}😊)\n"
        m.add(types.InlineKeyboardButton(f"{n} — 🐟{pr}", callback_data=f"buy_{n}"))
    bot.send_message(uid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_"))
def shop_buy(call):
    uid = call.from_user.id; name = call.data[4:]; info = SHOP_ITEMS.get(name)
    if not info: bot.answer_callback_query(call.id, "Не найден!"); return
    td = max(get_shop_disc(), get_faction_disc(uid)); pr = int(info["price"]*(1-td))
    if get_fishnets(uid) < pr: bot.answer_callback_query(call.id, "Не хватает 🐟!"); return
    add_fishnets(uid, -pr); add_to_inv(uid, name, info["type"]); update_quest_progress(uid, "shop", 1)
    bot.answer_callback_query(call.id, f"Куплено: {name} за 🐟{pr}!")

# ==================== КРАФТ (с тирами) ====================
@bot.message_handler(commands=['craft'])
@bot.message_handler(func=lambda m: m.text == "🔨 Крафт")
def menu_craft(message):
    uid = message.from_user.id
    m = types.InlineKeyboardMarkup()
    for tid, td_info in CRAFT_TIERS.items():
        recipes_in_tier = [r for r in CRAFT_RECIPES if r.get("tier") == tid]
        cnt = len(recipes_in_tier)
        avail = sum(1 for r in recipes_in_tier if can_craft(uid, r))
        m.add(types.InlineKeyboardButton(f"{td_info['name']} ({avail}/{cnt})", callback_data=f"cfttier_{tid}"))
    bot.send_message(uid, "🔨 *Крафт*\n\nВыберите тиp:", parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cfttier_"))
def craft_tier(call):
    uid = call.from_user.id; tid = int(call.data.split("_")[1])
    recipes = [r for r in CRAFT_RECIPES if r.get("tier") == tid]
    if not recipes: bot.answer_callback_query(call.id, "Пусто!"); return
    td_info = CRAFT_TIERS.get(tid, {"name": "??"})
    t = f"{td_info['name']}\n\n"
    m = types.InlineKeyboardMarkup()
    for r in recipes:
        rt = ", ".join([f"{r2} x{a}" for r2, a in r["resources"].items()])
        b = ITEM_BONUSES.get(r["name"], {}); bt = ""
        if "str" in b: bt += f"💪+{b['str']} "
        if "def" in b: bt += f"🛡️+{b['def']} "
        if "hp" in b: bt += f"❤️+{b['hp']}"
        t += f"{'✅' if can_craft(uid, r) else '❌'} {r['name']} ({bt.strip()})\n  {r.get('desc','')}\n  {rt}\n\n"
        m.add(types.InlineKeyboardButton(f"{'✅' if can_craft(uid, r) else '❌'} {r['name']}", callback_data=f"cft_{r['name']}"))
    m.add(types.InlineKeyboardButton("◀️ Назад", callback_data="cftback"))
    bot.edit_message_text(t, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data == "cftback")
def craft_back(call):
    uid = call.from_user.id; m = types.InlineKeyboardMarkup()
    for tid, td_info in CRAFT_TIERS.items():
        recipes_in_tier = [r for r in CRAFT_RECIPES if r.get("tier") == tid]
        cnt = len(recipes_in_tier); avail = sum(1 for r in recipes_in_tier if can_craft(uid, r))
        m.add(types.InlineKeyboardButton(f"{td_info['name']} ({avail}/{cnt})", callback_data=f"cfttier_{tid}"))
    bot.edit_message_text("🔨 *Крафт*\n\nВыберите тиp:", call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cft_"))
def craft_do(call):
    uid = call.from_user.id; name = call.data[4:]
    r = next((x for x in CRAFT_RECIPES if x["name"] == name), None)
    if not r: bot.answer_callback_query(call.id, "Не найден!"); return
    if not can_craft(uid, r): bot.answer_callback_query(call.id, "Не хватает ресурсов!"); return
    for res, amt in r["resources"].items(): remove_from_inv(uid, res, amt)
    add_to_inv(uid, name, r["type"]); update_quest_progress(uid, "craft", 1)
    update_quest_chain(uid, "craft_item", 1)
    pl = get_player(uid)
    if pl and pl[5] == "hunters": add_faction_rep(uid, 1)
    bot.answer_callback_query(call.id, f"Скрафчено: {name}!")

# ==================== РАБОТА ====================
@bot.message_handler(commands=['work'])
@bot.message_handler(func=lambda m: m.text == "💼 Работа")
def menu_work(message):
    uid = message.from_user.id; seals = get_player_seals(uid)
    if not seals: bot.send_message(uid, "Нет тюленей!"); return
    m = types.InlineKeyboardMarkup()
    for s in seals:
        if s[11] == 1: continue
        m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"wsel_{s[0]}"))
    if not m.keyboard: bot.send_message(uid, "Все малыши!"); return
    bot.send_message(uid, "💼 Выберите тюленя:", reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("wsel_"))
def work_sel(call):
    sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal: return
    if seal[6] < 20: bot.answer_callback_query(call.id, "Сытость<20!"); return
    wc = seal[18]
    if wc:
        try:
            cm = seal[21] if seal[21] else 30
            rem = timedelta(minutes=cm) - (datetime.now() - datetime.fromisoformat(wc))
            if rem.total_seconds() > 0:
                bot.answer_callback_query(call.id, f"⏳ {int(rem.total_seconds()//60)}м {int(rem.total_seconds()%60)}с"); return
        except: pass
    t = f"💼 Работа для {seal[2]}:\n\n"
    for i, j in enumerate(JOBS): t += f"{i+1}. {j['name']} — 🐟{j['reward_min']}-{j['reward_max']}, кд{j['cooldown_min']}м\n"
    m = types.InlineKeyboardMarkup()
    for i, j in enumerate(JOBS): m.add(types.InlineKeyboardButton(f"{j['name']} — 🐟{j['reward_min']}-{j['reward_max']}", callback_data=f"wdo_{sid}_{i}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="back_main"))
    bot.edit_message_text(t, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("wdo_"))
def work_do(call):
    uid = call.from_user.id; p = call.data.split("_"); sid = int(p[1]); ji = int(p[2])
    if ji < 0 or ji >= len(JOBS): bot.answer_callback_query(call.id, "Не найдена!"); return
    job = JOBS[ji]; seal = get_seal(sid)
    if not seal or seal[6] < 20 or seal[5] < 10: bot.answer_callback_query(call.id, "Не может!"); return
    wc = seal[18]
    if wc:
        try:
            prev_cd = seal[21] if seal[21] else job["cooldown_min"]
            rem = timedelta(minutes=prev_cd) - (datetime.now() - datetime.fromisoformat(wc))
            if rem.total_seconds() > 0:
                bot.answer_callback_query(call.id, f"⏳ {int(rem.total_seconds()//60)}м {int(rem.total_seconds()%60)}с"); return
        except: pass
    rw = random.randint(job["reward_min"], job["reward_max"]) + seal[9] * 3
    eg = int(random.randint(10, 25) * get_exp_mult())
    update_seal(sid, mood=max(0,seal[5]-job["mood_cost"]), satiety=max(0,seal[6]-job["satiety_cost"]),
                exp=seal[10]+eg, work_cooldown=datetime.now().isoformat(), work_cooldown_min=job["cooldown_min"])
    add_fishnets(uid, rw); lv = check_levelup(sid)
    log = f"💼 {seal[2]}: {job['name']}\n💰 🐟{rw}\n📈 +{eg}оп\n⏳ кд{job['cooldown_min']}м"
    if lv: log += f"\n🎉 Ур.{lv}!"
    enc = trigger_encounter(uid)
    if enc: log += f"\n\n{enc}"
    update_quest_progress(uid, "work", 1)
    bot.edit_message_text(log, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

# ==================== БОЙ ====================
@bot.message_handler(commands=['battle'])
@bot.message_handler(func=lambda m: m.text == "⚔️ Бой")
def menu_battle(message):
    uid = message.from_user.id; seals = get_player_seals(uid)
    if not seals: bot.send_message(uid, "Нет тюленей!"); return
    m = types.InlineKeyboardMarkup()
    for s in seals:
        if s[11] == 1: continue
        m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"bat_{s[0]}"))
    if not m.keyboard: bot.send_message(uid, "Все малыши!"); return
    bot.send_message(uid, "Выберите тюленя:", reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("bat_"))
def do_battle(call):
    uid = call.from_user.id; sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal or seal[3] <= 0: bot.answer_callback_query(call.id, "Не может!"); return
    es, ed, eh = get_effective_stats(sid); skills = get_seal_skills(sid)
    boss = random.choice(BOSSES); bn = boss["name"]
    bhp = random.randint(60,100) + seal[9]*10; bstr = random.randint(8,15) + seal[9]*2; bdef = random.randint(3,8) + seal[9]
    log = [f"⚔️ *{seal[2]} vs {bn}*\n", f"{seal[2]}: ❤️{eh} 💪{es} 🛡️{ed}", f"{bn}: ❤️{bhp} 💪{bstr} 🛡️{bdef}\n"]
    shp = seal[3]
    for rnd in range(1, 21):
        if shp <= 0 or bhp <= 0: break
        dmg = es
        if any(s["effect"]=="berserk" for s in skills) and shp < eh*0.3: dmg = int(dmg*1.5)
        if random.random() < sum(0.15 for s in skills if s["effect"]=="crit_15"): dmg *= 2; log.append("⚡ Крит!")
        dmg = max(1, dmg - bdef + random.randint(-3,5)); bhp -= dmg
        log.append(f"Р{rnd}: {seal[2]} →{dmg} (босс {max(0,bhp)}❤️)")
        if bhp <= 0: break
        if random.random() < sum
# Монстры и их характеристики
MONSTERS = [
    {"name": "Акула 🦈", "health": 150, "strength": 12, "defense": 8, "level": 5, "xp_reward": 50, "drops": ["Акулий зуб 🦈", "Чешуя 🐟"]},
    {"name": "Кракен 🐙", "health": 200, "strength": 15, "defense": 12, "level": 7, "xp_reward": 75, "drops": ["Щупальце 🐙", "Жемчуг 🫧"]},
    {"name": "Морской дракон 🐲", "health": 180, "strength": 14, "defense": 10, "level": 6, "xp_reward": 60, "drops": ["Чешуя 🐟", "Кристалл 💎"]},
    {"name": "Слизь 🐌", "health": 120, "strength": 7, "defense": 5, "level": 3, "xp_reward": 30, "drops": ["Слизь 🐌"]},
    {"name": "Ледяной Голем ❄️", "health": 220, "strength": 16, "defense": 14, "level": 8, "xp_reward": 85, "drops": ["Лёд 🧊"]},
    {"name": "Тёмный Рыцарь 🖤", "health": 160, "strength": 13, "defense": 11, "level": 5, "xp_reward": 55, "drops": ["Чернила 🖤", "Клык 🦷"]},
]

# Боссы
BOSSES = [
    {"name": "Древний Кракен 🦑", "health": 500, "strength": 25, "defense": 20, "level": 10, "xp_reward": 200, "drops": ["Щупальце 🐙", "Жемчуг 🫧", "Рог нарвала 🦏"]},
    {"name": "Король Акул 🦈👑", "health": 450, "strength": 22, "defense": 18, "level": 9, "xp_reward": 180, "drops": ["Акулий зуб 🦈", "Чешуя 🐟", "Костяной меч 🗡️"]},
    {"name": "Ледяной Властелин ❄️", "health": 480, "strength": 24, "defense": 16, "level": 10, "xp_reward": 190, "drops": ["Лёд 🧊", "Кристалл 💎"]},
]

def get_monster(name):
    for m in MONSTERS:
        if m["name"] == name:
            return m
    return None

def get_boss(name):
    for b in BOSSES:
        if b["name"] == name:
            return b
    return None
# Система квестов
QUESTS = [
    {"type": "daily", "desc": "Поймай 5 рыб", "reward": 50, "item": "Апельсин 🍊"},
    {"type": "weekly", "desc": "Сразись с 3 акулами", "reward": 100, "item": "Мороженое 🍦"},
    {"type": "dungeon", "desc": "Пройди 3 этажа подземелья", "reward": 150, "item": "Компас мудреца 🧭"},
    {"type": "hunt", "desc": "Убей 5 слизней", "reward": 75, "item": "Жемчужное ожерелье 🫧"},
]

def get_quest(user_id, quest_type):
    for q in QUESTS:
        if q["type"] == quest_type:
            return q
    return None

# Награды за квесты
REWARDS = {
        if random.random() < sum(0.10 for s in skills if s["effect"]=="double_strike") and bhp > 0:
            d2 = max(1, es - bdef + random.randint(-3,5)); bhp -= d2; log.append(f"⚔️ Двойной! →{d2}")
        if bhp <= 0: break
        if random.random() < sum(0.10 for s in skills if s["effect"]=="dodge_10"): log.append("💨 Уклонение!"); continue
        dm = max(1, bstr - ed + random.randint(-2,4))
        if any(s["effect"]=="dmg_reduce_10" for s in skills): dm = int(dm*0.9)
        shp -= dm; log.append(f"{bn} →{dm} ({seal[2]} {max(0,shp)}❤️)")
        ls = sum(1 for s in skills if s["effect"]=="lifesteal_5")
        if ls: heal = int(dm*0.05*ls); shp = min(eh, shp+heal)
        if any(s["effect"]=="thorns" for s in skills): bhp -= int(dm*0.2)
    if bhp <= 0:
        rw = random.randint(20,50) + seal[9]*5; eg = int(random.randint(20,40) * get_exp_mult())
        add_fishnets(uid, rw); update_seal(sid, exp=seal[10]+eg, mood=min(100,seal[5]+15))
        lv = check_levelup(sid)
        log.append(f"\n🎉 *Победа!* 🐟{rw} +{eg}оп")
        if lv: log.append(f"📈 Ур.{lv}!")
        d = process_drops(uid, boss["drops"])
        if d: log.append(f"📦 {', '.join(d)}")
        update_quest_progress(uid, "battle", 1); update_quest_chain(uid, "battle_count", 1)
        pl = get_player(uid)
        if pl and pl[5] == "hunters": add_faction_rep(uid, 2)
    elif shp <= 0:
        update_seal(sid, health=max(1,seal[3]//4), mood=max(0,seal[5]-20))
        log.append("\n💀 *Поражение...*")
    else: log.append("\n🤝 Ничья!")
    bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown')

# ==================== ПОДЗЕМЕЛЬЕ ====================
@bot.message_handler(commands=['dungeon'])
@bot.message_handler(func=lambda m: m.text == "🏰 Подземелье")
def menu_dungeon(message):
    uid = message.from_user.id; seals = get_player_seals(uid)
    if not seals: bot.send_message(uid, "Нет тюленей!"); return
    m = types.InlineKeyboardMarkup()
    for s in seals:
        if s[11] == 1: continue
        m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"ds_{s[0]}"))
    if not m.keyboard: bot.send_message(uid, "Все малыши!"); return
    bot.send_message(uid, "🏰 Выберите тюленя (10 этажей, сундуки!):", reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("ds_"))
def dng_start(call):
    uid = call.from_user.id; sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal: return
    if seal[3] <= 20: bot.answer_callback_query(call.id, "HP<20!"); return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("DELETE FROM dungeon_runs WHERE user_id=?", (uid,))
    c.execute("INSERT INTO dungeon_runs (user_id,seal_id,current_floor,active,current_monster) VALUES (?,?,1,1,0)", (uid, sid))
    conn.commit(); conn.close()
    dng_floor(call, sid, 1, 0)

def dng_floor(call, sid, fl, mon_idx):
    seal = get_seal(sid)
    if not seal: return
    config = DUNGEON_FLOORS_CONFIG[min(fl-1, len(DUNGEON_FLOORS_CONFIG)-1)]
    total_mons = config["monsters"]
    if mon_idx >= total_mons:
        rarity = config["chest_rarity"]
        chest_name = f"Сундук [{rarity}] 📦"
        add_to_inv(call.from_user.id, chest_name, "chest", 1)
        if fl >= DUNGEON_TOTAL_FLOORS:
            eg = int((100 + fl * 30) * get_exp_mult())
            s = get_seal(sid); update_seal(sid, exp=s[10]+eg); lv = check_levelup(sid)
            t = f"🏆 *Подземелье пройдено!*\n🎁 {chest_name}\n📈 +{eg}оп"
            if lv: t += f"\n🎉 Ур.{lv}!"
            update_quest_progress(call.from_user.id, "dungeon", 1)
            update_quest_chain(call.from_user.id, "dungeon_complete", 1)
            update_quest_chain(call.from_user.id, "dungeon_floor", fl)
            pl = get_player(call.from_user.id)
            if pl and pl[5] == "explorers": add_faction_rep(call.from_user.id, 3)
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("UPDATE dungeon_runs SET active=0 WHERE user_id=?", (call.from_user.id,))
            conn.commit(); conn.close()
            bot.edit_message_text(t, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        else:
            nf = fl + 1
            t = f"✅ Этаж {fl} пройден!\n🎁 {chest_name}\nОткрыт этаж {nf}!"
            m = types.InlineKeyboardMarkup()
            m.add(types.InlineKeyboardButton("➡️ Дальше", callback_data=f"dn_{sid}_{nf}"))
            m.add(types.InlineKeyboardButton("🏃 Выйти", callback_data=f"df_{sid}_{fl}"))
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("UPDATE dungeon_runs SET current_monster=0 WHERE user_id=?", (call.from_user.id,))
            conn.commit(); conn.close()
            bot.edit_message_text(t, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=m)
        return
    mon = get_floor_monster(fl, mon_idx)
    es, ed, eh = get_effective_stats(sid)
    t = f"🏰 *Этаж {fl}/{DUNGEON_TOTAL_FLOORS}* | Монстр {mon_idx+1}/{total_mons}\n\n"
    t += f"🦭 {seal[2]}: ❤️{eh} 💪{es} 🛡️{ed}\n{mon['name']}: ❤️{mon['hp']} 💪{mon['str']} 🛡️{mon['def']}\n"
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("⚔️ Атаковать", callback_data=f"da_{sid}_{fl}_{mon_idx}"))
    m.add(types.InlineKeyboardButton("🏃 Сбежать", callback_data=f"df_{sid}_{fl}"))
    bot.edit_message_text(t, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("da_"))
def dng_atk(call):
    uid = call.from_user.id; p = call.data.split("_"); sid = int(p[1]); fl = int(p[2]); mon_idx = int(p[3])
    seal = get_seal(sid)
    if not seal: return
    mon = get_floor_monster(fl, mon_idx)
    es, ed, eh = get_effective_stats(sid); shp = eh
    log = [f"⚔️ Этаж {fl}: {seal[2]} vs {mon['name']}"]
    while shp > 0 and mon["hp"] > 0:
        d = max(1, es - mon["def"] + random.randint(-2, 5)); mon["hp"] -= d
        log.append(f"{seal[2]} →{d} (монстр {max(0, mon['hp'])}❤️)")
        if mon["hp"] <= 0: break
        dm = max(1, mon["str"] - ed + random.randint(-1, 4)); shp -= dm
        log.append(f"{mon['name']} →{dm} ({seal[2]} {max(0, shp)}❤️)")
    if mon["hp"] <= 0:
        update_seal(sid, health=max(1, shp)); log.append("\n✅ Повержен!")
        d = process_drops(uid, mon.get("drops", {}))
        if d: log.append(f"📦 {', '.join(d)}")
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("UPDATE dungeon_runs SET current_monster=? WHERE user_id=?", (mon_idx+1, uid))
        conn.commit(); conn.close()
        next_idx = mon_idx + 1
        config = DUNGEON_FLOORS_CONFIG[min(fl-1, len(DUNGEON_FLOORS_CONFIG)-1)]
        if next_idx >= config["monsters"]:
            log.append("\n🎁 Этаж зачищен!")
        m = types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("➡️ Дальше", callback_data=f"dn_{sid}_{fl}_{next_idx}"))
        m.add(types.InlineKeyboardButton("🏃 Выйти", callback_data=f"df_{sid}_{fl}"))
        bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    elif shp <= 0:
        update_seal(sid, health=1, mood=max(0, seal[5]-30)); log.append(f"\n💀 {seal[2]} пал...")
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("UPDATE dungeon_runs SET active=0 WHERE user_id=?", (uid,))
        conn.commit(); conn.close()
        bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("dn_"))
def dng_next(call):
    p = call.data.split("_"); dng_floor(call, int(p[1]), int(p[2]), int(p[3]))

@bot.callback_query_handler(func=lambda c: c.data.startswith("df_"))
def dng_flee(call):
    uid = call.from_user.id
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE dungeon_runs SET active=0 WHERE user_id=?", (uid,))
    conn.commit(); conn.close()
    bot.edit_message_text("🏃 Сбежали.", call.message.chat.id, call.message.message_id)

# ==================== РЫБАЛКА ====================
fish_active = {}

@bot.message_handler(commands=['fish'])
@bot.message_handler(func=lambda m: m.text == "🎣 Рыбалка")
def cmd_fish(message):
    uid = message.from_user.id; p = get_player(uid)
    if not p: bot.send_message(uid, "/start"); return
    fc = p[7]
    if fc:
        try:
            rem = timedelta(minutes=FISHING_COOLDOWN_MIN) - (datetime.now() - datetime.fromisoformat(fc))
            if rem.total_seconds() > 0:
                bot.send_message(uid, f"⏳ {int(rem.total_seconds()//60)}м {int(rem.total_seconds()%60)}с"); return
        except: pass
    fish = random.choice(FISH_TYPES)
    opts = ["Подсечь!","Ждать","Отпустить"]; opts.remove(fish["correct"]); opts.append(fish["correct"]); random.shuffle(opts)
    t = f"🎣 *Рыбалка!*\n\nПоклёвка: {fish['name']}\nУ вас 5 секунд!\n"
    m = types.InlineKeyboardMarkup(row_width=3)
    for o in opts: m.add(types.InlineKeyboardButton(o, callback_data=f"fh_{o}_{fish['name']}"))
    msg = bot.send_message(uid, t, parse_mode='Markdown', reply_markup=m)
    fish_active[uid] = True
    def timeout():
        time.sleep(5)
        if not fish_active.get(uid): return
        try: bot.edit_message_text(f"⏰ Время! {fish['name']} уплыл.", msg.chat.id, msg.message_id)
        except: pass
        update_player(uid, fish_cooldown=datetime.now().isoformat())
    threading.Thread(target=timeout, daemon=True).start()

@bot.callback_query_handler(func=lambda c: c.data.startswith("fh_"))
def fish_cb(call):
    uid = call.from_user.id
    if not fish_active.get(uid): bot.answer_callback_query(call.id, "Время вышло!"); return
    fish_active[uid] = False
    p = call.data.split("_", 2); act, fn = p[1], p[2]
    fish = next((f for f in FISH_TYPES if f["name"] == fn), None)
    if not fish: bot.answer_callback_query(call.id, "Истекла!"); return
    bonus = get_fish_bonus()
    rm, rx = int(fish["reward"][0]*bonus), int(fish["reward"][1]*bonus)
    if act == fish["correct"]:
        rw = random.randint(rm, rx); add_fishnets(uid, rw)
        bot.edit_message_text(f"🎣 *Поймано!*\n\n{fn}!\n🐟{rw}", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        update_quest_progress(uid, "fish", 1)
    else:
        bot.edit_message_text(f"💨 {fn} сорвался!\nНужно: {fish['correct']}", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    update_player(uid, fish_cooldown=datetime.now().isoformat())
# ==================== ДУЭЛИ ====================
@bot.message_handler(commands=['duel'])
@bot.message_handler(func=lambda m: m.text == "🤺 Дуэль")
def cmd_duel(message):
    uid = message.from_user.id; seals = get_player_seals(uid)
    if not seals: bot.send_message(uid, "Нет тюленей!"); return
    m = types.InlineKeyboardMarkup()
    for s in seals:
        if s[11] == 1: continue
        m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"dusel_{s[0]}"))
    if not m.keyboard: bot.send_message(uid, "Все малыши!"); return
    bot.send_message(uid, "🤺 Выберите тюленя:", reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dusel_"))
def duel_sel(call):
    sid = int(call.data.split("_")[1])
    bot.send_message(call.from_user.id, "Введите @username или ID соперника:")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, lambda m: duel_target(m, sid))

def duel_target(message, sid):
    uid = message.from_user.id; txt = message.text.strip()
    if txt.startswith("@"):
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT user_id FROM players WHERE username=?", (txt[1:],)); r = c.fetchone(); conn.close()
        if not r: bot.send_message(uid, "Не найден!"); return
        oid = r[0]
    else:
        try: oid = int(txt)
        except: bot.send_message(uid, "Неверный формат!"); return
    if oid == uid: bot.send_message(uid, "Нельзя с собой!"); return
    seal = get_seal(sid); did = create_duel(uid, oid, sid)
    bot.send_message(uid, "🤺 Вызов отправлен! Ожидайте ответа.")
    try:
        m2 = types.InlineKeyboardMarkup()
        m2.add(types.InlineKeyboardButton("⚔️ Принять", callback_data=f"duac_{did}"),
               types.InlineKeyboardButton("❌ Отказать", callback_data=f"durj_{did}"))
        bot.send_message(oid, f"🤺 Вас вызвал на дуэль @{message.from_user.username}!\nТюлень: {seal[2]} (ур.{seal[9]})", reply_markup=m2)
    except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("duac_"))
def duel_accept(call):
    uid = call.from_user.id; did = int(call.data.split("_")[1]); duel = get_duel(did)
    if not duel or duel[5] != 'pending': bot.answer_callback_query(call.id, "Недоступна!"); return
    if duel[2] != uid: bot.answer_callback_query(call.id, "Не вам!"); return
    seals = get_player_seals(uid)
    if not seals: bot.answer_callback_query(call.id, "Нет тюленей!"); return
    m = types.InlineKeyboardMarkup()
    for s in seals:
        if s[11] == 1: continue
        m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"duseal_{did}_{s[0]}"))
    bot.edit_message_text("Выберите тюленя:", call.message.chat.id, call.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("duseal_"))
def duel_seal(call):
    uid = call.from_user.id; p = call.data.split("_"); did = int(p[1]); osid = int(p[2])
    duel = get_duel(did)
    if not duel or duel[5] != 'pending': bot.answer_callback_query(call.id, "Недоступна!"); return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE duels SET status='active',opponent_seal_id=? WHERE duel_id=?", (osid, did))
    conn.commit(); conn.close()
    csid = duel[3]; cseal = get_seal(csid); oseal = get_seal(osid)
    if not cseal or not oseal: bot.answer_callback_query(call.id, "Тюлень не найден!"); return
    ces, ced, ceh = get_effective_stats(csid); oes, oed, oeh = get_effective_stats(osid)
    csk = get_seal_skills(csid); osk = get_seal_skills(osid)
    chp = ceh; ohp = oeh
    log = [f"🤺 *Дуэль: {cseal[2]} vs {oseal[2]}*\n",
           f"{cseal[2]}: ❤️{ceh} 💪{ces} 🛡️{ced}", f"{oseal[2]}: ❤️{oeh} 💪{oes} 🛡️{oed}\n"]
    rnd = 0; rw = 0
    while chp > 0 and ohp > 0:
        rnd += 1
        if rnd > 15: break
        cd = ces
        if any(s["effect"]=="berserk" for s in csk) and chp < ceh*0.3: cd = int(cd*1.5)
        if random.random() < sum(0.15 for s in csk if s["effect"]=="crit_15"): cd *= 2; log.append("⚡ Крит!")
        cd = max(1, cd - oed + random.randint(-3,5)); ohp -= cd
        log.append(f"Р{rnd}: {cseal[2]} →{cd} ({oseal[2]} {max(0,ohp)}❤️)")
        if ohp <= 0: break
        od = oes
        if any(s["effect"]=="berserk" for s in osk) and ohp < oeh*0.3: od = int(od*1.5)
        if random.random() < sum(0.15 for s in osk if s["effect"]=="crit_15"): od *= 2; log.append("⚡ Крит в ответ!")
        od = max(1, od - ced + random.randint(-3,5)); chp -= od
        log.append(f"{oseal[2]} →{od} ({cseal[2]} {max(0,chp)}❤️)")
    winner_id = 0
    if ohp <= 0:
        winner_id = duel[1]; log.append(f"\n🎉 *{cseal[2]} победил!*")
        rw = min(get_fishnets(duel[2])//10, 100); add_fishnets(duel[1], rw); add_fishnets(duel[2], -rw)
        log.append(f"💰 Награда: 🐟{rw}"); update_quest_chain(duel[1], "duel_win", 1)
    elif chp <= 0:
        winner_id = duel[2]; log.append(f"\n🎉 *{oseal[2]} победил!*")
        rw = min(get_fishnets(duel[1])//10, 100); add_fishnets(duel[2], rw); add_fishnets(duel[1], -rw)
        log.append(f"💰 Награда: 🐟{rw}"); update_quest_chain(duel[2], "duel_win", 1)
    else: log.append("\n🤝 Ничья!")
    update_seal(csid, health=max(1,chp)); update_seal(osid, health=max(1,ohp))
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE duels SET status='completed',winner_id=?,reward=? WHERE duel_id=?", (winner_id, rw, did))
    conn.commit(); conn.close()
    bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    try: bot.send_message(duel[1] if duel[1]!=uid else duel[2], "\n".join(log), parse_mode='Markdown')
    except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("durj_"))
def duel_reject(call):
    did = int(call.data.split("_")[1]); duel = get_duel(did)
    if not duel: bot.answer_callback_query(call.id, "Не найдена!"); return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE duels SET status='rejected' WHERE duel_id=?", (did,)); conn.commit(); conn.close()
    bot.edit_message_text("❌ Дуэль отклонена.", call.message.chat.id, call.message.message_id)
    try: bot.send_message(duel[1], "❌ Ваш вызов отклонён.")
    except: pass

# ==================== КВЕСТОВЫЕ ЦЕПОЧКИ ====================
def show_quest_chains(uid, chat_id, message_id=None):
    chains = get_quest_chains()
    t = "📚 *Квестовые цепочки*\n\n"; m = types.InlineKeyboardMarkup()
    for ch in chains:
        cid, name, story = ch[0], ch[1], ch[2]
        pc = get_player_chain(uid, cid)
        if pc and pc[5] == 1: t += f"✅ *{name}* — завершена\n"
        elif pc:
            steps = json.loads(ch[3]); step = steps[pc[3]]
            t += f"🔄 *{name}* — шаг {pc[3]+1}/{len(steps)}\n  {step['desc']} ({pc[4]}/{step['target']})\n"
        else:
            t += f"⬜ *{name}*\n  {story}\n"
            m.add(types.InlineKeyboardButton(f"Начать: {name}", callback_data=f"qcs_{cid}"))
        t += "\n"
    if message_id:
        try: bot.edit_message_text(t, chat_id, message_id, parse_mode='Markdown', reply_markup=m)
        except: bot.send_message(chat_id, t, parse_mode='Markdown', reply_markup=m)
    else: bot.send_message(chat_id, t, parse_mode='Markdown', reply_markup=m)

@bot.message_handler(commands=['questchain'])
@bot.message_handler(func=lambda m: m.text == "📚 Цепочки")
def cmd_questchain(message):
    show_quest_chains(message.from_user.id, message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("qcs_"))
def qc_start(call):
    uid = call.from_user.id; cid = int(call.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO player_quest_chains (user_id,chain_id,current_step,step_progress,completed) VALUES (?,?,0,0,0)", (uid, cid))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "Цепочка начата!")
    show_quest_chains(uid, call.message.chat.id, call.message.message_id)

# ==================== БИРЖА ====================
@bot.message_handler(commands=['trade'])
@bot.message_handler(func=lambda m: m.text == "📦 Биржа")
def menu_trade(message):
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("📤 Создать", callback_data="trc"))
    m.add(types.InlineKeyboardButton("📋 Активные", callback_data="trl_0"))
    m.add(types.InlineKeyboardButton("📦 Мои", callback_data="trm"))
    bot.send_message(message.from_user.id, "📦 *Биржа*", parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data == "trc")
def trade_create(call):
    uid = call.from_user.id; inv = get_inv(uid)
    if not inv: bot.answer_callback_query(call.id, "Пусто!"); return
    m = types.InlineKeyboardMarkup()
    for i in inv:
        if i[3] == "resource": continue
        m.add(types.InlineKeyboardButton(f"{i[2]} (x{i[4]})", callback_data=f"trs_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="trb"))
    bot.edit_message_text("Что продать?", call.message.chat.id, call.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("trs_"))
def trade_price(call):
    name = call.data[4:]
    bot.send_message(call.from_user.id, f"Цена для {name}?")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, lambda m: tr_set(m, name))

def tr_set(message, name):
    uid = message.from_user.id
    try: pr = int(message.text.strip())
    except: bot.send_message(uid, "Число!"); return
    if pr < 1: bot.send_message(uid, ">0!"); return
    it = ITEM_TYPES.get(name, "misc")
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO trade_offers (seller_id,item_name,item_type,price,created_at,active) VALUES (?,?,?,?,?,1)", (uid, name, it, pr, datetime.now().isoformat()))
    conn.commit(); conn.close(); remove_from_inv(uid, name)
    bot.send_message(uid, f"✅ {name} за 🐟{pr}!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("trl_"))
def trade_list(call):
    uid = call.from_user.id; pg = int(call.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT offer_id,item_name,price FROM trade_offers WHERE active=1 AND seller_id!=? ORDER BY created_at DESC LIMIT 10 OFFSET ?", (uid, pg*10))
    offers = c.fetchall(); conn.close()
    if not offers: bot.edit_message_text("Пусто.", call.message.chat.id, call.message.message_id); return
    t = "📋 *Офферы*\n\n"; m = types.InlineKeyboardMarkup()
    for oid, nm, pr in offers:
        t += f"  {nm} — 🐟{pr}\n"
        m.add(types.InlineKeyboardButton(f"Купить {nm} — 🐟{pr}", callback_data=f"trbuy_{oid}"))
    nav = []
    if pg > 0: nav.append(types.InlineKeyboardButton("◀️", callback_data=f"trl_{pg-1}"))
    nav.append(types.InlineKeyboardButton("➡️", callback_data=f"trl_{pg+1}"))
    m.add(*nav); m.add(types.InlineKeyboardButton("◀️ В меню", callback_data="trb"))
    bot.edit_message_text(t, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("trbuy_"))
def trade_buy(call):
    uid = call.from_user.id; oid = int(call.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT seller_id,item_name,item_type,price,active FROM trade_offers WHERE offer_id=?", (oid,)); r = c.fetchone()
    if not r or not r[4]: bot.answer_callback_query(call.id, "Не найден!"); conn.close(); return
    sid, nm, it, pr, _ = r
    if sid == uid: bot.answer_callback_query(call.id, "Своё!"); conn.close(); return
    if get_fishnets(uid) < pr: bot.answer_callback_query(call.id, "Не хватает 🐟!"); conn.close(); return
    add_fishnets(uid, -pr); add_fishnets(sid, pr); add_to_inv(uid, nm, it)
    c.execute("UPDATE trade_offers SET active=0 WHERE offer_id=?", (oid,)); conn.commit(); conn.close()
    bot.answer_callback_query(call.id, f"Куплено: {nm}!")
    try: bot.send_message(sid, f"💰 {nm} продан за 🐟{pr}!")
    except: pass

@bot.callback_query_handler(func=lambda c: c.data == "trm")
def trade_mine(call):
    uid = call.from_user.id
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT offer_id,item_name,price,active FROM trade_offers WHERE seller_id=? ORDER BY created_at DESC", (uid,))
    offers = c.fetchall(); conn.close()
    if not offers: bot.answer_callback_query(call.id, "Пусто!"); return
    t = "📦 *Мои офферы*\n\n"; m = types.InlineKeyboardMarkup()
    for oid, nm, pr, act in offers:
        t += f"  {'✅' if act else '❌'} {nm} — 🐟{pr}\n"
        if act: m.add(types.InlineKeyboardButton(f"Снять {nm}", callback_data=f"trcan_{oid}"))
    m.add(types.InlineKeyboardButton("◀️ В меню", callback_data="trb"))
    bot.edit_message_text(t, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("trcan_"))
def trade_cancel(call):
    uid = call.from_user.id; oid = int(call.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT item_name,item_type,active FROM trade_offers WHERE offer_id=? AND seller_id=?", (oid, uid)); r = c.fetchone()
    if not r or not r[2]: bot.answer_callback_query(call.id, "Не найден!"); conn.close(); return
    c.execute("UPDATE trade_offers SET active=0 WHERE offer_id=?", (oid,)); conn.commit(); conn.close()
    add_to_inv(uid, r[0], r[1]); bot.answer_callback_query(call.id, f"Снято: {r[0]}!")

@bot.callback_query_handler(func=lambda c: c.data == "trb")
def trade_back(call):
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("📤 Создать", callback_data="trc"))
    m.add(types.InlineKeyboardButton("📋 Активные", callback_data="trl_0"))
    m.add(types.InlineKeyboardButton("📦 Мои", callback_data="trm"))
    bot.edit_message_text("📦 *Биржа*", call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=m)

# ==================== КЛАНЫ ====================
@bot.message_handler(commands=['clan'])
@bot.message_handler(func=lambda m: m.text == "🐋 Клан")
def menu_clan(message):
    uid = message.from_user.id; clan = get_clan_by_user(uid)
    if clan:
        cid = clan[0]; members = get_clan_members(cid); mc = len(members)
        t = f"🐋 *Клан: {clan[2]} {clan[3]}*\n\nЛидер: @{clan[1]}\nУчастников: {mc}/{MAX_CLAN_MEMBERS}\n\n"
        m = types.InlineKeyboardMarkup()
        if clan[1] == uid:
            m.add(types.InlineKeyboardButton("🏰 Клановое подземелье", callback_data=f"cds_{cid}"))
            m.add(types.InlineKeyboardButton("📋 Участники", callback_data=f"cmem_{cid}"))
        m.add(types.InlineKeyboardButton("🚪 Покинуть", callback_data=f"cleave_{cid}"))
        bot.send_message(uid, t, parse_mode='Markdown', reply_markup=m)
    else:
        t = "🐋 Вы не состоите в клане.\n\nСоздайте свой или попросите пригласить!"
        m = types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("➕ Создать клан", callback_data="ccreate"))
        bot.send_message(uid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data == "ccreate")
def clan_create(call):
    bot.send_message(call.from_user.id, "Введите название клана:")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, clan_create_name)

def clan_create_name(message):
    uid = message.from_user.id; name = message.text.strip()
    if len(name) > 30: bot.send_message(uid, "Слишком длинное!"); return
    bot.send_message(uid, f"Выберите эмблему: {' '.join(CLAN_EMOJIS)}\nОтправьте номер (1-{len(CLAN_EMOJIS)}):")
    bot.register_next_step_handler_by_chat_id(message.chat.id, lambda m: clan_create_emblem(m, name))

def clan_create_emblem(message, name):
    uid = message.from_user.id
    try: idx = int(message.text.strip()) - 1
    except: bot.send_message(uid, "Число!"); return
    if idx < 0 or idx >= len(CLAN_EMOJIS): bot.send_message(uid, "Неверный номер!"); return
    emblem = CLAN_EMOJIS[idx]
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO clans (name,emblem,leader_id,created_at) VALUES (?,?,?,?)", (name, emblem, uid, datetime.now().isoformat()))
    cid = c.lastrowid
    c.execute("INSERT INTO clan_members (clan_id,user_id,joined_at) VALUES (?,?,?)", (cid, uid, datetime.now().isoformat()))
    conn.commit(); conn.close()
    bot.send_message(uid, f"✅ Клан {name} {emblem} создан!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("cleave_"))
def clan_leave(call):
    uid = call.from_user.id; cid = int(call.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("DELETE FROM clan_members WHERE user_id=? AND clan_id=?", (uid, cid))
    c.execute("SELECT leader_id FROM clans WHERE clan_id=?", (cid,)); r = c.fetchone()
    if r and r[0] == uid:
        c.execute("DELETE FROM clan_members WHERE clan_id=?", (cid,))
        c.execute("DELETE FROM clans WHERE clan_id=?", (cid,))
        c.execute("DELETE FROM clan_dungeons WHERE clan_id=?", (cid,))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "Вы покинули клан!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("cmem_"))
def clan_members(call):
    cid = int(call.data.split("_")[1]); members = get_clan_members(cid)
    t = "📋 *Участники клана*\n\n"
    for mid in members:
        p = get_player(mid)
        if p: t += f"  @{p[1]} ({get_seal_count(mid)} тюленей)\n"
    bot.edit_message_text(t, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("cds_"))
def clan_dng_start(call):
    uid = call.from_user.id; cid = int(call.data.split("_")[1]); clan = get_clan_by_user(uid)
    if not clan or clan[1] != uid: bot.answer_callback_query(call.id, "Только лидер!"); return
    members = get_clan_members(cid); all_seals = []
    for mid in members:
        for s in get_player_seals(mid):
            if s[11] == 0 and s[9] >= CLAN_DUNGEON_MIN_LEVEL: all_seals.append(s)
    if not all_seals: bot.answer_callback_query(call.id, "Нет тюленей 4+ уровня!"); return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("DELETE FROM clan_dungeons WHERE clan_id=?", (cid,))
    c.execute("INSERT INTO clan_dungeons (clan_id,current_floor,active,started_by) VALUES (?,1,1,?)", (cid, uid))
    conn.commit(); conn.close()
    clan_dng_floor(call, cid, 1)

def clan_dng_floor(call, cid, fl):
    members = get_clan_members(cid); all_seals = []
    for mid in members:
        for s in get_player_seals(mid):
            if s[11] == 0 and s[9] >= CLAN_DUNGEON_MIN_LEVEL: all_seals.append(s)
    if not all_seals: bot.edit_message_text("Нет доступных тюленей!", call.message.chat.id, call.message.message_id); return
    mon = CLAN_DUNGEON_MONSTERS[fl-1].copy()
    total_str = sum(get_effective_stats(s[0])[0] for s in all_seals)
    total_def = sum(get_effective_stats(s[0])[1] for s in all_seals)
    total_hp = sum(s[3] for s in all_seals)
    t = f"🏰 *Клановое подземелье — Этаж {fl}/{CLAN_DUNGEON_FLOORS}*\n\n"
    t += f"🦭 Тюленей: {len(all_seals)}\n💪 Сум. сила: {total_str}\n🛡️ Сум. защита: {total_def}\n❤️ Сум. HP: {total_hp}\n\n"
    t += f"{mon['name']}: ❤️{mon['hp']} 💪{mon['str']} 🛡️{mon['def']}\n"
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("⚔️ Атаковать", callback_data=f"cda_{cid}_{fl}"))
    m.add(types.InlineKeyboardButton("🏃 Отступить", callback_data=f"cdf_{cid}_{fl}"))
    bot.edit_message_text(t, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cda_"))
def clan_dng_atk(call):
    uid = call.from_user.id; p = call.data.split("_"); cid = int(p[1]); fl = int(p[2])
    members = get_clan_members(cid); all_seals = []
    for mid in members:
        for s in get_player_seals(mid):
            if s[11] == 0 and s[9] >= CLAN_DUNGEON_MIN_LEVEL: all_seals.append(s)
    if not all_seals: bot.answer_callback_query(call.id, "Нет тюленей!"); return
    mon = CLAN_DUNGEON_MONSTERS[fl-1].copy()
    ts = sum(get_effective_stats(s[0])[0] for s in all_seals)
    td = sum(get_effective_stats(s[0])[1] for s in all_seals)
    seal_hp = {s[0]: s[3] for s in all_seals}; thp = sum(seal_hp.values())
    log = [f"🏰 Этаж {fl}: {len(all_seals)} тюленей vs {mon['name']}"]
    while thp > 0 and mon["hp"] > 0:
        dmg = max(1, ts - mon["def"] + random.randint(-5, 10)); mon["hp"] -= dmg
        log.append(f"Тюлени →{dmg} (монстр {max(0, mon['hp'])}❤️)")
        if mon["hp"] <= 0: break
        dm = max(1, mon["str"] - td + random.randint(-2, 6))
        target = random.choice(all_seals); new_hp = max(1, seal_hp[target[0]] - dm)
        seal_hp[target[0]] = new_hp; update_seal(target[0], health=new_hp)
        thp -= dm; log.append(f"{mon['name']} →{target[2]} на {dm} (осталось {max(0, thp)}❤️)")
    if mon["hp"] <= 0:
        log.append("\n✅ Монстр повержен!")
        rw = 200 + fl * 50; eg = 100 + fl * 30
        for mid in members:
            add_fishnets(mid, rw)
            for s in get_player_seals(mid):
                if s[11] == 0: update_seal(s[0], exp=s[10]+eg)
        log.append(f"🏆 Все получили 🐟{rw} и +{eg}оп!")
        if fl >= CLAN_DUNGEON_FLOORS:
            log.append("👑 *Клановое подземелье пройдено!*")
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("UPDATE clan_dungeons SET active=0 WHERE clan_id=?", (cid,)); conn.commit(); conn.close()
            bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        else:
            nf = fl + 1; log.append(f"Открыт этаж {nf}!")
            m = types.InlineKeyboardMarkup()
            m.add(types.InlineKeyboardButton("➡️ Дальше", callback_data=f"cdn_{cid}_{nf}"))
            m.add(types.InlineKeyboardButton("🏃 Выйти", callback_data=f"cdf_{cid}_{fl}"))
            bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    elif thp <= 0:
        log.append("\n💀 Все тюлени пали...")
        for s in all_seals: update_seal(s[0], health=1, mood=max(0, s[5]-20))
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("UPDATE clan_dungeons SET active=0 WHERE clan_id=?", (cid,)); conn.commit(); conn.close()
        bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("cdn_"))
def clan_dng_next(call):
    p = call.data.split("_"); clan_dng_floor(call, int(p[1]), int(p[2]))

@bot.callback_query_handler(func=lambda c: c.data.startswith("cdf_"))
def clan_dng_flee(call):
    cid = int(call.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE clan_dungeons SET active=0 WHERE clan_id=?", (cid,)); conn.commit(); conn.close()
    bot.edit_message_text("🏃 Отступление.", call.message.chat.id, call.message.message_id)

# ==================== ФРАКЦИИ ====================
@bot.message_handler(commands=['faction'])
@bot.message_handler(func=lambda m: m.text == "🏛 Фракции")
def menu_faction(message):
    uid = message.from_user.id; p = get_player(uid)
    if not p: bot.send_message(uid, "/start"); return
    t = "🏛 *Фракции*\n\n"
    for fid, fd in FACTIONS.items():
        mk = " ✅" if p[5] == fid else ""
        t += f"*{fd['name']}*{mk}\n  {fd['desc']}\n"
        if p[5] == fid: t += f"  Репутация: {p[6]}\n"
        t += "\n"
    m = types.InlineKeyboardMarkup()
    for fid, fd in FACTIONS.items():
        if p[5] == fid: m.add(types.InlineKeyboardButton(f"🔄 Сменить: {fd['name']}", callback_data=f"fj_{fid}"))
        else: m.add(types.InlineKeyboardButton(f"Вступить: {fd['name']}", callback_data=f"fj_{fid}"))
    bot.send_message(uid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("fj_"))
def faction_join(call):
    fid = call.data.split("_")[1]
    if fid not in FACTIONS: bot.answer_callback_query(call.id, "Не найдена!"); return
    update_player(call.from_user.id, faction=fid, faction_rep=0)
    bot.answer_callback_query(call.id, f"Вступили: {FACTIONS[fid]['name']}!")

# ==================== ГОЛОСОВАНИЕ ====================
@bot.message_handler(commands=['vote'])
def cmd_vote(message):
    uid = message.from_user.id; today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT vote FROM votes WHERE user_id=? AND date=?", (uid, today)); ex = c.fetchone(); conn.close()
    ev = get_todays_event(); t = f"🗳 *Голосование*\n\n{ev['desc']}\n\n"
    act = get_active_event_text()
    if act: t += f"✅ Активно: {act}\n\n"
    if ex: t += f"Вы голосовали: {ex[0].upper()}"; bot.send_message(uid, t, parse_mode='Markdown'); return
    t += "Голосуем?"
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("✅ За", callback_data="vy"), types.InlineKeyboardButton("❌ Против", callback_data="vn"))
    bot.send_message(uid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data in ("vy", "vn"))
def vote_cb(call):
    uid = call.from_user.id; vote = "yes" if call.data == "vy" else "no"; today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("INSERT INTO votes (user_id,event_type,vote,date) VALUES (?,?,?,?)", (uid, "daily", vote, today)); conn.commit()
    except sqlite3.IntegrityError:
        bot.answer_callback_query(call.id, "Уже голосовали!"); conn.close(); return
    conn.close()
    if check_vote_result():
        ev = get_todays_event(); activate_event(ev["event_type"], ev["effect"])
        bot.answer_callback_query(call.id, f"Активировано: {ev['desc']}")
        bot.edit_message_text(f"✅ *Активировано!*\n{ev['desc']}", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    else:
        bot.answer_callback_query(call.id, "Голос принят!")

# ==================== БРАКИ ====================
@bot.message_handler(commands=['marry'])
@bot.message_handler(func=lambda m: m.text == "💍 Брак")
def menu_marry(message):
    uid = message.from_user.id; seals = get_player_seals(uid)
    if not seals: bot.send_message(uid, "Нет тюленей!"); return
    if get_seal_count(uid) >= MAX_SEALS: bot.send_message(uid, f"Макс {MAX_SEALS}!"); return
    m = types.InlineKeyboardMarkup()
    for s in seals: m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"msel_{s[0]}"))
    bot.send_message(uid, "Выберите тюленя:", reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("msel_"))
def marry_sel(call):
    sid = int(call.data.split("_")[1])
    bot.send_message(call.from_user.id, "ID или @username партнёра:")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, lambda m: marry_partner(m, sid))

def marry_partner(message, sid1):
    uid = message.from_user.id; txt = message.text.strip()
    if txt.startswith("@"):
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT user_id FROM players WHERE username=?", (txt[1:],)); r = c.fetchone(); conn.close()
        if not r: bot.send_message(uid, "Не найден!"); return
        pid = r[0]
    else:
        try: pid = int(txt)
        except: bot.send_message(uid, "Формат!"); return
    if pid == uid: bot.send_message(uid, "С собой нельзя!"); return
    ps = get_player_seals(pid)
    if not ps: bot.send_message(uid, "Нет тюленей у игрока!"); return
    m = types.InlineKeyboardMarkup()
    for s in ps: m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"mdo_{sid1}_{s[0]}_{pid}"))
    bot.send_message(uid, "Выберите тюленя партнёра:", reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("mdo_"))
def marry_do(call):
    uid = call.from_user.id; p = call.data.split("_"); s1, s2, pid = int(p[1]), int(p[2]), int(p[3])
    se1, se2 = get_seal(s1), get_seal(s2)
    if not se1 or not se2: bot.answer_callback_query(call.id, "Не найден!"); return
    if get_seal_count(uid) >= MAX_SEALS: bot.answer_callback_query(call.id, f"Макс {MAX_SEALS}!"); return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM marriages WHERE (seal1_id=? AND seal2_id=?) OR (seal1_id=? AND seal2_id=?)", (s1, s2, s2, s1))
    if c.fetchone(): bot.answer_callback_query(call.id, "Уже в браке!"); conn.close(); return
    c.execute("INSERT INTO marriages (seal1_id,seal2_id,player1_id,player2_id,created_at) VALUES (?,?,?,?,?)", (s1, s2, uid, pid, datetime.now().isoformat()))
    conn.commit(); conn.close()
    msg = f"💍 Брак! {se1[2]} ❤️ {se2[2]}\n"
    if random.random() < 0.5:
        bn = random.choice(["Малыш","Кроха","Пузырь","Лапик","Шлёпик","Ням"])
        bs = (se1[7]+se2[7])//4 + random.randint(1,3); bd = (se1[8]+se2[8])//4 + random.randint(0,2)
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("INSERT INTO seals (owner_id,name,health,max_health,mood,satiety,strength,defense,level,exp,is_baby,born_at) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
                  (uid, bn, 60, 60, 70, 70, bs, bd, 1, 0, datetime.now().isoformat()))
        conn.commit(); conn.close()
        msg += f"🍼 Тюленёнок — {bn}! С:{bs} З:{bd}\nВырастет через {BABY_GROW_DAYS} дн."
    else: msg += "Нет тюленёнка..."
    bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

# ==================== ЕЖЕДНЕВНЫЕ ЗАДАНИЯ ====================
def show_quests(uid, chat_id, message_id=None):
    try: generate_daily_quests(uid); quests = get_daily_quests(uid)
    except Exception as e: bot.send_message(chat_id, f"⚠️ Ошибка БД: {e}"); return
    if not quests: bot.send_message(chat_id, "Задания не сгенерированы."); return
    t = "📋 *Ежедневные задания*\n\n"; m = types.InlineKeyboardMarkup()
    qd = {q["type"]: q["desc"] for q in QUEST_TEMPLATES}
    for q in quests:
        qid, qt, qtgt, qprog, qrew, cl = q[0], q[2], q[3], q[4], q[5], q[7]
        d = qd.get(qt, qt); s = f"{qprog}/{qtgt}"
        if cl: t += f"  ✅ {d} — {s} (🐟{qrew}) — получено\n"
        elif qprog >= qtgt:
            t += f"  🎁 {d} — {s} (🐟{qrew}) — готово!\n"
            m.add(types.InlineKeyboardButton(f"Забрать 🐟{qrew}", callback_data=f"qclaim_{qid}"))
        else: t += f"  ⬜ {d} — {s} (🐟{qrew})\n"
    if m.keyboard:
        if message_id:
            try: bot.edit_message_text(t, chat_id, message_id, parse_mode='Markdown', reply_markup=m)
            except: bot.send_message(chat_id, t, parse_mode='Markdown', reply_markup=m)
        else: bot.send_message(chat_id, t, parse_mode='Markdown', reply_markup=m)
    else:
        if message_id:
            try: bot.edit_message_text(t, chat_id, message_id, parse_mode='Markdown')
            except: bot.send_message(chat_id, t, parse_mode='Markdown')
        else: bot.send_message(chat_id, t, parse_mode='Markdown')

@bot.message_handler(commands=['quests'])
@bot.message_handler(func=lambda m: m.text == "📋 Задания")
def menu_quests(message):
    show_quests(message.from_user.id, message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("qclaim_"))
def quest_claim(call):
    uid = call.from_user.id; qid = int(call.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT quest_id,quest_target,quest_progress,quest_reward,claimed FROM daily_quests WHERE quest_id=? AND claimed=0", (qid,)); r = c.fetchone()
    if not r: bot.answer_callback_query(call.id, "Уже получено!"); conn.close(); return
    qid_db, qtgt, qprog, qrew, cl = r
    if qprog < qtgt: bot.answer_callback_query(call.id, "Не выполнено!"); conn.close(); return
    c.execute("UPDATE daily_quests SET claimed=1 WHERE quest_id=?", (qid,)); conn.commit(); conn.close()
    add_fishnets(uid, qrew); bot.answer_callback_query(call.id, f"Получено 🐟{qrew}!")
    show_quests(uid, call.message.chat.id, call.message.message_id)

# ==================== ФОНОВЫЕ ПОТОКИ ====================
def stats_decay():
    while True:
        time.sleep(3600)
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10); c = conn.cursor()
            c.execute("SELECT seal_id,health,mood,satiety,is_baby FROM seals")
            for sid, hp, mood, sat, is_baby in c.fetchall():
                nm = max(0, mood - random.randint(3, 8)); ns = max(0, sat - random.randint(5, 10))
                nh = max(1, hp - random.randint(3, 8)) if ns < 20 else hp
                c.execute("UPDATE seals SET mood=?,satiety=?,health=? WHERE seal_id=?", (nm, ns, nh, sid))
                if is_baby == 1: check_baby_growth(sid)
            conn.commit(); conn.close()
        except: pass

def health_regen():
    while True:
        time.sleep(3600)
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10); c = conn.cursor()
            c.execute("SELECT seal_id,health,max_health FROM seals WHERE health<max_health")
            for sid, hp, mhp in c.fetchall():
                bonus = 25
                c2 = conn.cursor()
                c2.execute("SELECT COUNT(*) FROM seal_skills WHERE seal_id=? AND skill_effect='regen'", (sid,))
                if c2.fetchone()[0] > 0: bonus += 5
                c.execute("UPDATE seals SET health=? WHERE seal_id=?", (min(mhp, hp+bonus), sid))
            conn.commit(); conn.close()
        except: pass

threading.Thread(target=stats_decay, daemon=True).start()
threading.Thread(target=health_regen, daemon=True).start()

# ==================== КОМАНДЫ В МЕНЮ ====================
bot.set_my_commands([
    types.BotCommand("start", "Главное меню"), types.BotCommand("help", "Справка"),
    types.BotCommand("profile", "Профиль"), types.BotCommand("gallery", "Галерея"),
    types.BotCommand("inventory", "Инвентарь"), types.BotCommand("setphoto", "Фото тюленя"),
    types.BotCommand("shop", "Магазин"), types.BotCommand("craft", "Крафт"),
    types.BotCommand("trade", "Биржа"), types.BotCommand("battle", "Бой с боссом"),
    types.BotCommand("dungeon", "Подземолье"), types.BotCommand("work", "Работа"),
    types.BotCommand("duel", "PvP-дуэль"), types.BotCommand("fish", "Рыбалка"),
    types.BotCommand("vote", "Голосование"), types.BotCommand("faction", "Фракции"),
    types.BotCommand("questchain", "Квестовые цепочки"), types.BotCommand("clan", "Клан"),
    types.BotCommand("marry", "Брак"), types.BotCommand("quests", "Задания"),
    types.BotCommand("leaderboard", "Лидеры"),
])

if __name__ == "__main__":
    run_migrations()
    print("Бот запущен! 🦭")
    bot.polling(none_stop=True)

import telebot
from telebot import types
import sqlite3, random, threading, time, os, shutil, json, re
from datetime import datetime, date, timedelta

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "PLACEHOLDER_TOKEN")
bot = telebot.TeleBot(TOKEN)
DB_PATH = "seal_life.db"
BACKUP_DIR = "backups"
MAX_SEALS = 5
FISH_COOLDOWN_MIN = 10
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
    c.execute("CREATE TABLE IF NOT EXISTS votes (vote_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, event_type TEXT, vote TEXT, date TEXT, UNIQUE(user_id, date))")
    c.execute("CREATE TABLE IF NOT EXISTS active_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, effect TEXT, expires_at TEXT, active INTEGER DEFAULT 1)")

def migration_2(c):
    c.execute("CREATE TABLE IF NOT EXISTS seal_skills (skill_id INTEGER PRIMARY KEY AUTOINCREMENT, seal_id INTEGER, skill_name TEXT, skill_effect TEXT, acquired_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS duels (duel_id INTEGER PRIMARY KEY AUTOINCREMENT, challenger_id INTEGER, opponent_id INTEGER, challenger_seal_id INTEGER, opponent_seal_id INTEGER, status TEXT DEFAULT 'pending', winner_id INTEGER, reward INTEGER, created_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS quest_chains (chain_id INTEGER PRIMARY KEY, name TEXT, story TEXT, steps_json TEXT, reward_json TEXT, reward_fishnets INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS player_quest_chains (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chain_id INTEGER, current_step INTEGER DEFAULT 0, step_progress INTEGER DEFAULT 0, completed INTEGER DEFAULT 0)")
    c.execute("""CREATE TABLE IF NOT EXISTS clans (
        clan_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, emblem TEXT,
        leader_id INTEGER, leader_name TEXT, created_at TEXT, treasury INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS clan_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT, clan_id INTEGER, user_id INTEGER,
        role TEXT DEFAULT 'member', joined_at TEXT
    )""")
    c.execute("CREATE TABLE IF NOT EXISTS clan_dungeons (id INTEGER PRIMARY KEY AUTOINCREMENT, clan_id INTEGER, current_floor INTEGER DEFAULT 1, active INTEGER DEFAULT 0, started_by INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS trades (trade_id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, item_name TEXT, price INTEGER, created_at TEXT)")
    chains = [
        (1,"Потерянный компас","Старый мудрый тюлень потерял компас во время шторма.",
         json.dumps([{"type":"dungeon_floor","target":3,"desc":"Дойдите до 3-го этажа подземелья"},{"type":"battle_count","target":2,"desc":"Победите 2 боссов"},{"type":"craft_item","target":1,"desc":"Скрафтите 1 предмет"}]),
         json.dumps({"item":"Компас мудреца","type":"accessory"}),200),
        (2,"Тайна глубин","Древняя табличка говорит о сокровище на дне океана.",
         json.dumps([{"type":"dungeon_complete","target":1,"desc":"Пройдите 1 подземелье полностью"},{"type":"reach_level","target":10,"desc":"Достигните 10 уровня"}]),
         json.dumps({"item":"Амулет глубин","type":"accessory"}),500),
        (3,"Король арены","Станьте легендой среди тюленей!",
         json.dumps([{"type":"duel_win","target":3,"desc":"Победите 3 игроков в дуэлях"},{"type":"battle_count","target":5,"desc":"Победите 5 боссов"}]),
         json.dumps({"item":"Корона чемпиона","type":"accessory"}),1000),
    ]
    c.executemany("INSERT OR REPLACE INTO quest_chains VALUES (?,?,?,?,?,?)", chains)

def migration_3(c):
    try: c.execute("ALTER TABLE seals ADD COLUMN equipped_artifact TEXT")
    except sqlite3.OperationalError: pass
    try: c.execute("ALTER TABLE dungeon_runs ADD COLUMN current_monster INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass

def migration_4(c):
    try: c.execute("ALTER TABLE seals ADD COLUMN active_potion TEXT")
    except sqlite3.OperationalError: pass
    try: c.execute("ALTER TABLE seals ADD COLUMN potion_uses INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    c.execute("""CREATE TABLE IF NOT EXISTS item_enchantments (
        ench_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, item_name TEXT,
        enchantment TEXT, created_at TEXT
    )""")

MIGRATIONS = [migration_1, migration_2, migration_3, migration_4]

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
# ==================== КОНСТАНТЫ ====================
SEAL_NAMES = ["Лунтик","Няша","Бубу","Кусь","Плюх","Снежок","Батон","Фрося","Гоша","Масик",
              "Тяпа","Шлёпа","Дюйм","Пиксель","Сёмга","Карамель","Пушок","Грация","Буббл","Мармелад"]
START_FISHNETS = 100

SHOP_ITEMS = {
    "Апельсин": {"price": 15, "type": "food", "satiety": 25, "mood": 10},
    "Рыба": {"price": 10, "type": "food", "satiety": 20, "mood": 5},
    "Кальмар": {"price": 25, "type": "food", "satiety": 35, "mood": 15},
    "Мороженое": {"price": 20, "type": "food", "satiety": 15, "mood": 30},
    "Креветка": {"price": 18, "type": "food", "satiety": 22, "mood": 8},
    "Устрица": {"price": 30, "type": "food", "satiety": 40, "mood": 20},
    "Водоросли": {"price": 8, "type": "food", "satiety": 15, "mood": 3},
    "Аптечка": {"price": 100, "type": "medkit", "heal": 50},
    "Бантик": {"price": 40, "type": "accessory"},
    "Шарф": {"price": 35, "type": "accessory"},
    "Корона": {"price": 200, "type": "accessory"},
    "Очки": {"price": 50, "type": "accessory"},
    "Цветок": {"price": 25, "type": "accessory"},
    "Морская звезда": {"price": 60, "type": "accessory"},
    "Жемчужное ожерелье": {"price": 120, "type": "accessory"},
    "Перо чайки": {"price": 30, "type": "accessory"},
    "Радужный пояс": {"price": 80, "type": "accessory"},
    "Пустая колба": {"price": 15, "type": "potion_base"},
}

ITEM_BONUSES = {
    "Костяной меч": {"str": 5}, "Акулий клык": {"str": 8}, "Трезубец": {"str": 12}, "Китовый клинок": {"str": 15},
    "Ядовитый клинок": {"str": 10}, "Ядовитый дротик": {"str": 7},
    "Чешуйчатая броня": {"def": 5, "hp": 10}, "Панцирь краба": {"def": 8, "hp": 15},
    "Плетёная броня": {"def": 10, "hp": 25}, "Кракеновый панцирь": {"def": 15, "hp": 40},
    "Шлем из ракушек": {"def": 3, "hp": 10}, "Костяной шлем": {"def": 5, "hp": 15}, "Корона из зубов": {"def": 8, "hp": 20},
    "Ядовитый шлем": {"def": 4, "hp": 12},
    "Щит из чешуи": {"def": 5}, "Панцирный щит": {"def": 8}, "Щит кракена": {"def": 12}, "Ядовитый щит": {"def": 7},
    "Ледяной клинок": {"str": 18}, "Огненный меч": {"str": 20}, "Коралловый меч": {"str": 16},
    "Ледяная броня": {"def": 18, "hp": 50}, "Огненная броня": {"def": 16, "hp": 55},
    "Морозный шлем": {"def": 10, "hp": 30}, "Пламенный шлем": {"def": 12, "hp": 25},
    "Ледяной щит": {"def": 15}, "Щит пламени": {"def": 16},
    "Молниевый клинок": {"str": 25}, "Призрачный меч": {"str": 28}, "Кристальный клинок": {"str": 22},
    "Молниевая броня": {"def": 22, "hp": 70}, "Призрачная броня": {"def": 24, "hp": 65},
    "Громовой шлем": {"def": 15, "hp": 45}, "Призрачный шлем": {"def": 16, "hp": 40},
    "Щит молний": {"def": 20}, "Призрачный щит": {"def": 22},
    "Клинок дракона": {"str": 35}, "Буревой топор": {"str": 38},
    "Драконья броня": {"def": 30, "hp": 100}, "Буревая броня": {"def": 28, "hp": 110},
    "Драконий шлем": {"def": 20, "hp": 60}, "Шлем бури": {"def": 18, "hp": 65},
    "Драконий щит": {"def": 28}, "Щит бури": {"def": 26},
    "Меч Богов": {"str": 50}, "Клинок Бездны": {"str": 55},
    "Броня Богов": {"def": 45, "hp": 200}, "Броня Бездны": {"def": 50, "hp": 180},
    "Шлем Богов": {"def": 30, "hp": 120}, "Шлем Бездны": {"def": 32, "hp": 110},
    "Щит Богов": {"def": 40}, "Щит Бездны": {"def": 42},
}

ACCESSORY_BONUSES = {
    "Бантик": 10, "Шарф": 8, "Корона": 20, "Очки": 7, "Цветок": 5,
    "Компас мудреца": 25, "Амулет глубин": 22, "Корона чемпиона": 30,
    "Морская звезда": 12, "Жемчужное ожерелье": 18, "Перо чайки": 6, "Радужный пояс": 14,
}

CRAFT_TIERS = ["common", "uncommon", "rare", "epic", "legendary"]
CRAFT_TIER_MULT = {"common": 1.0, "uncommon": 1.3, "rare": 1.6, "epic": 2.0, "legendary": 2.5}
CRAFT_TIER_LABEL = {"common": "Обычный", "uncommon": "Необычный", "rare": "Редкий", "epic": "Эпический", "legendary": "Легендарный"}

CRAFT_RECIPES = [
    {"name": "Костяной меч", "type": "weapon", "tier": "common", "resources": {"Акулий зуб": 3}},
    {"name": "Акулий клык", "type": "weapon", "tier": "common", "resources": {"Акулий зуб": 5, "Чешуя": 2}},
    {"name": "Трезубец", "type": "weapon", "tier": "common", "resources": {"Щупальце": 4, "Акулий зуб": 3}},
    {"name": "Китовый клинок", "type": "weapon", "tier": "common", "resources": {"Китовый ус": 3, "Жемчуг": 1}},
    {"name": "Ядовитый клинок", "type": "weapon", "tier": "common", "resources": {"Жало": 3, "Акулий зуб": 2}},
    {"name": "Ядовитый дротик", "type": "weapon", "tier": "common", "resources": {"Жало": 2, "Чешуя": 3}},
    {"name": "Чешуйчатая броня", "type": "armor", "tier": "common", "resources": {"Чешуя": 4}},
    {"name": "Панцирь краба", "type": "armor", "tier": "common", "resources": {"Панцирь": 3}},
    {"name": "Плетёная броня", "type": "armor", "tier": "common", "resources": {"Щупальце": 3, "Чешуя": 2}},
    {"name": "Кракеновый панцирь", "type": "armor", "tier": "common", "resources": {"Щупальце": 5, "Жемчуг": 1}},
    {"name": "Шлем из ракушек", "type": "helmet", "tier": "common", "resources": {"Панцирь": 3, "Чешуя": 1}},
    {"name": "Костяной шлем", "type": "helmet", "tier": "common", "resources": {"Акулий зуб": 3}},
    {"name": "Корона из зубов", "type": "helmet", "tier": "common", "resources": {"Акулий зуб": 5, "Жемчуг": 1}},
    {"name": "Ядовитый шлем", "type": "helmet", "tier": "common", "resources": {"Жало": 3, "Чешуя": 2}},
    {"name": "Щит из чешуи", "type": "shield", "tier": "common", "resources": {"Чешуя": 4, "Панцирь": 1}},
    {"name": "Панцирный щит", "type": "shield", "tier": "common", "resources": {"Панцирь": 4}},
    {"name": "Щит кракена", "type": "shield", "tier": "common", "resources": {"Щупальце": 3, "Панцирь": 2}},
    {"name": "Ядовитый щит", "type": "shield", "tier": "common", "resources": {"Жало": 4, "Панцирь": 2}},
    {"name": "Коралловый меч", "type": "weapon", "tier": "uncommon", "resources": {"Коралл": 4, "Акулий зуб": 2}},
    {"name": "Ледяной клинок", "type": "weapon", "tier": "uncommon", "resources": {"Ледяной кристалл": 3, "Чешуя": 3}},
    {"name": "Огненный меч", "type": "weapon", "tier": "uncommon", "resources": {"Огненный камень": 3, "Акулий зуб": 3}},
    {"name": "Ледяная броня", "type": "armor", "tier": "uncommon", "resources": {"Ледяной кристалл": 4, "Панцирь": 2}},
    {"name": "Огненная броня", "type": "armor", "tier": "uncommon", "resources": {"Огненный камень": 4, "Чешуя": 3}},
    {"name": "Морозный шлем", "type": "helmet", "tier": "uncommon", "resources": {"Ледяной кристалл": 3, "Панцирь": 2}},
    {"name": "Пламенный шлем", "type": "helmet", "tier": "uncommon", "resources": {"Огненный камень": 3, "Акулий зуб": 2}},
    {"name": "Ледяной щит", "type": "shield", "tier": "uncommon", "resources": {"Ледяной кристалл": 3, "Панцирь": 2}},
    {"name": "Щит пламени", "type": "shield", "tier": "uncommon", "resources": {"Огненный камень": 3, "Панцирь": 2}},
    {"name": "Кристальный клинок", "type": "weapon", "tier": "rare", "resources": {"Кристальный осколок": 4, "Коралл": 2}},
    {"name": "Молниевый клинок", "type": "weapon", "tier": "rare", "resources": {"Грозовой камень": 4, "Ледяной кристалл": 2}},
    {"name": "Призрачный меч", "type": "weapon", "tier": "rare", "resources": {"Призрачная эссенция": 4, "Огненный камень": 2}},
    {"name": "Молниевая броня", "type": "armor", "tier": "rare", "resources": {"Грозовой камень": 5, "Ледяной кристалл": 3}},
    {"name": "Призрачная броня", "type": "armor", "tier": "rare", "resources": {"Призрачная эссенция": 5, "Огненный камень": 3}},
    {"name": "Громовой шлем", "type": "helmet", "tier": "rare", "resources": {"Грозовой камень": 3, "Кристальный осколок": 1}},
    {"name": "Призрачный шлем", "type": "helmet", "tier": "rare", "resources": {"Призрачная эссенция": 3, "Кристальный осколок": 1}},
    {"name": "Щит молний", "type": "shield", "tier": "rare", "resources": {"Грозовой камень": 3, "Панцирь": 3}},
    {"name": "Призрачный щит", "type": "shield", "tier": "rare", "resources": {"Призрачная эссенция": 3, "Панцирь": 3}},
    {"name": "Клинок дракона", "type": "weapon", "tier": "epic", "resources": {"Драконья чешуя": 5, "Грозовой камень": 3}},
    {"name": "Буревой топор", "type": "weapon", "tier": "epic", "resources": {"Драконья чешуя": 5, "Огненный камень": 3}},
    {"name": "Драконья броня", "type": "armor", "tier": "epic", "resources": {"Драконья чешуя": 6, "Кристальный осколок": 3}},
    {"name": "Буревая броня", "type": "armor", "tier": "epic", "resources": {"Драконья чешуя": 6, "Грозовой камень": 3}},
    {"name": "Драконий шлем", "type": "helmet", "tier": "epic", "resources": {"Драконья чешуя": 4, "Кровь кракена": 2}},
    {"name": "Шлем бури", "type": "helmet", "tier": "epic", "resources": {"Драконья чешуя": 4, "Тёмная эссенция": 2}},
    {"name": "Драконий щит", "type": "shield", "tier": "epic", "resources": {"Драконья чешуя": 4, "Кровь кракена": 2}},
    {"name": "Щит бури", "type": "shield", "tier": "epic", "resources": {"Драконья чешуя": 4, "Тёмная эссенция": 2}},
    {"name": "Меч Богов", "type": "weapon", "tier": "legendary", "resources": {"Слеза Посейдона": 2, "Драконья чешуя": 5}},
    {"name": "Клинок Бездны", "type": "weapon", "tier": "legendary", "resources": {"Слеза Посейдона": 2, "Тёмная эссенция": 5}},
    {"name": "Броня Богов", "type": "armor", "tier": "legendary", "resources": {"Слеза Посейдона": 3, "Драконья чешуя": 5}},
    {"name": "Броня Бездны", "type": "armor", "tier": "legendary", "resources": {"Слеза Посейдона": 3, "Тёмная эссенция": 5}},
    {"name": "Шлем Богов", "type": "helmet", "tier": "legendary", "resources": {"Слеза Посейдона": 2, "Кровь кракена": 3}},
    {"name": "Шлем Бездны", "type": "helmet", "tier": "legendary", "resources": {"Слеза Посейдона": 2, "Тёмная эссенция": 3}},
    {"name": "Щит Богов", "type": "shield", "tier": "legendary", "resources": {"Слеза Посейдона": 2, "Кровь кракена": 3}},
    {"name": "Щит Бездны", "type": "shield", "tier": "legendary", "resources": {"Слеза Посейдона": 2, "Тёмная эссенция": 3}},
    {"name": "Зелье лечения", "type": "potion", "tier": "common", "resources": {"Водоросли": 3, "Пустая колба": 1}, "effect": "heal", "value": 40},
    {"name": "Зелье силы", "type": "potion", "tier": "common", "resources": {"Акулий зуб": 2, "Пустая колба": 1}, "effect": "str_boost", "value": 10, "duration": 5},
    {"name": "Зелье защиты", "type": "potion", "tier": "common", "resources": {"Панцирь": 2, "Пустая колба": 1}, "effect": "def_boost", "value": 10, "duration": 5},
    {"name": "Зелье скорости", "type": "potion", "tier": "uncommon", "resources": {"Жало": 3, "Пустая колба": 1}, "effect": "speed_boost", "value": 3, "duration": 3},
    {"name": "Зелье ярости", "type": "potion", "tier": "uncommon", "resources": {"Кровь кракена": 1, "Огненный камень": 2, "Пустая колба": 1}, "effect": "rage", "value": 50, "duration": 3},
    {"name": "Зелье регенерации", "type": "potion", "tier": "rare", "resources": {"Кристальный осколок": 2, "Водоросли": 3, "Пустая колба": 1}, "effect": "regen_potion", "value": 15, "duration": 5},
    {"name": "Зелье невидимости", "type": "potion", "tier": "rare", "resources": {"Призрачная эссенция": 3, "Пустая колба": 1}, "effect": "dodge_boost", "value": 30, "duration": 3},
    {"name": "Эликсир титана", "type": "potion", "tier": "epic", "resources": {"Драконья чешуя": 2, "Кровь кракена": 2, "Пустая колба": 1}, "effect": "titan", "value": 25, "duration": 5},
    {"name": "Антидот", "type": "potion", "tier": "common", "resources": {"Водоросли": 2, "Жало": 1, "Пустая колба": 1}, "effect": "antidote", "value": 0},
]

ENCHANTMENTS = {
    "Огненное зачарование": {"bonus_str": 5, "bonus_def": 0, "cost": {"Огненный камень": 3}},
    "Ледяное зачарование": {"bonus_str": 0, "bonus_def": 5, "cost": {"Ледяной кристалл": 3}},
    "Теневое зачарование": {"bonus_str": 3, "bonus_def": 3, "cost": {"Тёмная эссенция": 3}},
    "Кристальное зачарование": {"bonus_str": 4, "bonus_def": 2, "cost": {"Кристальный осколок": 3}},
    "Кровавое зачарование": {"bonus_str": 6, "bonus_def": 0, "cost": {"Кровь кракена": 2, "Жало": 2}},
    "Древнее зачарование": {"bonus_str": 8, "bonus_def": 4, "cost": {"Слеза Посейдона": 1, "Кристальный осколок": 2}},
}

POTION_EFFECTS = {
    "heal": "Восстанавливает HP", "str_boost": "Бонус к силе", "def_boost": "Бонус к защите",
    "speed_boost": "Доп. атака", "rage": "+50% урон", "regen_potion": "Регенерация HP",
    "dodge_boost": "Шанс уклонения", "titan": "+25 стр и +25 защ", "antidote": "Снимает отравление",
}

ARTIFACTS = {
    "F": [{"name":"Ржавый ключ","str":2,"def":1,"hp":5},{"name":"Старый компас","str":1,"def":2,"hp":5},{"name":"Обломок ракушки","str":2,"def":2,"hp":3}],
    "E": [{"name":"Медный амулет","str":4,"def":3,"hp":10},{"name":"Рыбацкий талисман","str":3,"def":4,"hp":12}],
    "D": [{"name":"Серебряный медальон","str":7,"def":5,"hp":20},{"name":"Коралловый браслет","str":6,"def":6,"hp":18}],
    "C": [{"name":"Жемчужина силы","str":12,"def":8,"hp":30},{"name":"Акулий талисман","str":10,"def":10,"hp":25}],
    "B": [{"name":"Кристалл глубин","str":18,"def":12,"hp":50},{"name":"Раковина Левиафана","str":15,"def":15,"hp":45}],
    "A": [{"name":"Сердце океана","str":28,"def":18,"hp":80},{"name":"Корона Морского Царя","str":25,"def":20,"hp":75}],
    "S": [{"name":"Слеза Посейдона","str":45,"def":30,"hp":150},{"name":"Трезубец Бездны","str":50,"def":25,"hp":120}],
}

CHEST_WEAPONS = {
    "F": [{"name":"Ржавый нож","str":4},{"name":"Деревянный меч","str":5}],
    "E": [{"name":"Каменный топор","str":7},{"name":"Костяной клинок","str":8}],
    "D": [{"name":"Коралловый меч","str":11},{"name":"Осколочный клинок","str":12}],
    "C": [{"name":"Ледяной клинок","str":16},{"name":"Огненный меч","str":18}],
    "B": [{"name":"Молниевый клинок","str":22},{"name":"Призрачный меч","str":25}],
    "A": [{"name":"Клинок дракона","str":32},{"name":"Буревой топор","str":35}],
    "S": [{"name":"Меч Богов","str":50},{"name":"Клинок Бездны","str":55}],
}

CHEST_ARMOR = {
    "F": [{"name":"Тряпьё","def":3,"hp":5},{"name":"Кожаная броня","def":4,"hp":8}],
    "E": [{"name":"Медная броня","def":6,"hp":15},{"name":"Костяная броня","def":7,"hp":12}],
    "D": [{"name":"Коралловая броня","def":10,"hp":25},{"name":"Акулья чешуя","def":12,"hp":20}],
    "C": [{"name":"Ледяная броня","def":15,"hp":40},{"name":"Огненная броня","def":14,"hp":45}],
    "B": [{"name":"Молниевая броня","def":20,"hp":60},{"name":"Призрачная броня","def":22,"hp":55}],
    "A": [{"name":"Драконья броня","def":30,"hp":100},{"name":"Буревая броня","def":28,"hp":110}],
    "S": [{"name":"Броня Богов","def":45,"hp":200},{"name":"Броня Бездны","def":50,"hp":180}],
}

CHEST_CONTENTS = {
    "F": {"fishnets": (10, 30), "price": 50}, "E": {"fishnets": (30, 60), "price": 100},
    "D": {"fishnets": (60, 120), "price": 200}, "C": {"fishnets": (120, 250), "price": 400},
    "B": {"fishnets": (250, 500), "price": 800}, "A": {"fishnets": (500, 1000), "price": 1500},
    "S": {"fishnets": (1000, 2000), "price": 3000},
}

RESOURCE_SELL_PRICES = {
    "Чешуя": 5, "Панцирь": 7, "Акулий зуб": 10, "Щупальце": 12,
    "Жемчуг": 25, "Китовый ус": 15, "Жало": 8, "Коралл": 15,
    "Ледяной кристалл": 20, "Огненный камень": 20, "Грозовой камень": 30,
    "Кристальный осколок": 35, "Призрачная эссенция": 35, "Драконья чешуя": 60,
    "Кровь кракена": 50, "Тёмная эссенция": 55, "Слеза Посейдона": 120,
}

POTION_SELL_PRICES = {
    "Зелье лечения": 30, "Зелье силы": 40, "Зелье защиты": 40,
    "Зелье скорости": 60, "Зелье ярости": 80, "Зелье регенерации": 100,
    "Зелье невидимости": 100, "Эликсир титана": 200, "Антидот": 25,
}

RARITY_SELL_PRICES = {"F": 15, "E": 35, "D": 75, "C": 150, "B": 350, "A": 700, "S": 1500}

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

ITEM_TYPES = {}
for _n, _i in SHOP_ITEMS.items(): ITEM_TYPES[_n] = _i["type"]
for _r in CRAFT_RECIPES:
    ITEM_TYPES[_r["name"]] = _r["type"]
    if "effect" in _r: ITEM_TYPES[_r["name"]] = "potion"
for _r in "FEDCBAS":
    ITEM_TYPES[f"Сундук [{_r}]"] = "chest"
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
ITEM_TYPES.update({"Компас мудреца": "accessory", "Амулет глубин": "accessory", "Корона чемпиона": "accessory"})
for _p in POTION_SELL_PRICES: ITEM_TYPES[_p] = "potion"

SEAL_SKILLS_POOL = [
    {"name": "Критический удар", "effect": "crit_15", "desc": "15% шанс двойного урона"},
    {"name": "Толстая кожа", "effect": "dmg_reduce_10", "desc": "-10% получаемого урона"},
    {"name": "Вампиризм", "effect": "lifesteal_5", "desc": "Восстанавливает 5% урона"},
    {"name": "Уклонение", "effect": "dodge_10", "desc": "10% шанс увернуться"},
    {"name": "Берсерк", "effect": "berserk", "desc": "+50% урона при HP<30%"},
    {"name": "Регенерация", "effect": "regen", "desc": "+5 HP/час"},
    {"name": "Шипы", "effect": "thorns", "desc": "Отражает 20% урона"},
    {"name": "Двойной удар", "effect": "double_strike", "desc": "10% шанс 2 атаки"},
]

DUNGEON_MONSTERS = [
    {"name": "Фугу", "hp": 30, "str": 8, "def": 3, "drops": {"Жало": 0.7}},
    {"name": "Креветка-ниндзя", "hp": 35, "str": 9, "def": 8, "drops": {"Панцирь": 0.5, "Чешуя": 0.3}},
    {"name": "Акула", "hp": 50, "str": 12, "def": 5, "drops": {"Акулий зуб": 0.7}},
    {"name": "Морской змей", "hp": 60, "str": 15, "def": 6, "drops": {"Чешуя": 0.7}},
    {"name": "Кракен", "hp": 80, "str": 18, "def": 8, "drops": {"Щупальце": 0.7, "Жемчуг": 0.1}},
    {"name": "Лобстер", "hp": 40, "str": 10, "def": 10, "drops": {"Панцирь": 0.7}},
    {"name": "Кашалот", "hp": 120, "str": 20, "def": 12, "drops": {"Китовый ус": 0.6}},
    {"name": "Электрический скат", "hp": 55, "str": 14, "def": 4, "drops": {"Чешуя": 0.5, "Жало": 0.3}},
    {"name": "Гигантская медуза", "hp": 45, "str": 11, "def": 3, "drops": {"Жало": 0.6}},
    {"name": "Морской дьявол", "hp": 90, "str": 16, "def": 9, "drops": {"Жемчуг": 0.3, "Чешуя": 0.4}},
    {"name": "Коралловый голем", "hp": 70, "str": 12, "def": 14, "drops": {"Коралл": 0.7}},
    {"name": "Ледяной краб", "hp": 65, "str": 14, "def": 10, "drops": {"Ледяной кристалл": 0.4, "Панцирь": 0.4}},
    {"name": "Огненный спрут", "hp": 75, "str": 16, "def": 6, "drops": {"Огненный камень": 0.4, "Щупальце": 0.3}},
    {"name": "Громовой скат", "hp": 60, "str": 18, "def": 5, "drops": {"Грозовой камень": 0.35, "Жало": 0.3}},
    {"name": "Призрачная медуза", "hp": 50, "str": 13, "def": 8, "drops": {"Призрачная эссенция": 0.35}},
    {"name": "Кристальный страж", "hp": 85, "str": 15, "def": 16, "drops": {"Кристальный осколок": 0.3}},
    {"name": "Дракончик", "hp": 100, "str": 22, "def": 12, "drops": {"Драконья чешуя": 0.3}},
    {"name": "Кровавый кракен", "hp": 90, "str": 20, "def": 10, "drops": {"Кровь кракена": 0.25}},
    {"name": "Теневой змей", "hp": 80, "str": 19, "def": 11, "drops": {"Тёмная эссенция": 0.25}},
    {"name": "Глубинный левиафан", "hp": 130, "str": 24, "def": 14, "drops": {"Слеза Посейдона": 0.05, "Чешуя": 0.5}},
]

BOSS_LIST = [
    {"name": "Краб-босс", "hp": 80, "str": 12, "def": 8, "drops": {"Панцирь": 0.8, "Коралл": 0.3}},
    {"name": "Акула", "hp": 100, "str": 15, "def": 5, "drops": {"Акулий зуб": 0.8, "Чешуя": 0.3}},
    {"name": "Осьминог", "hp": 90, "str": 14, "def": 6, "drops": {"Щупальце": 0.8, "Жемчуг": 0.1}},
    {"name": "Морской ёжик", "hp": 70, "str": 10, "def": 12, "drops": {"Жало": 0.8}},
    {"name": "Кашалот", "hp": 150, "str": 18, "def": 10, "drops": {"Китовый ус": 0.7}},
    {"name": "Морской змей", "hp": 120, "str": 16, "def": 7, "drops": {"Чешуя": 0.8}},
    {"name": "Гигантский краб", "hp": 130, "str": 17, "def": 14, "drops": {"Панцирь": 0.8, "Жемчуг": 0.15}},
    {"name": "Электрический скат", "hp": 100, "str": 16, "def": 8, "drops": {"Чешуя": 0.7, "Жало": 0.3, "Грозовой камень": 0.2}},
    {"name": "Глубинный монстр", "hp": 160, "str": 20, "def": 12, "drops": {"Жемчуг": 0.4, "Щупальце": 0.5, "Тёмная эссенция": 0.15}},
    {"name": "Король креветок", "hp": 110, "str": 15, "def": 13, "drops": {"Панцирь": 0.7, "Чешуя": 0.3, "Ледяной кристалл": 0.2}},
    {"name": "Огненный кракен", "hp": 180, "str": 22, "def": 10, "drops": {"Огненный камень": 0.5, "Щупальце": 0.3, "Кровь кракена": 0.15}},
    {"name": "Ледяной левиафан", "hp": 200, "str": 24, "def": 14, "drops": {"Ледяной кристалл": 0.5, "Чешуя": 0.3, "Кристальный осколок": 0.1}},
    {"name": "Грозовой дракон", "hp": 220, "str": 26, "def": 16, "drops": {"Грозовой камень": 0.5, "Драконья чешуя": 0.15}},
    {"name": "Призрачный король", "hp": 180, "str": 23, "def": 15, "drops": {"Призрачная эссенция": 0.5, "Тёмная эссенция": 0.15}},
    {"name": "Древний кракен", "hp": 250, "str": 28, "def": 18, "drops": {"Кровь кракена": 0.3, "Жемчуг": 0.3, "Слеза Посейдона": 0.05}},
    {"name": "Повелитель глубин", "hp": 300, "str": 32, "def": 20, "drops": {"Тёмная эссенция": 0.3, "Драконья чешуя": 0.15, "Слеза Посейдона": 0.08}},
]

JOBS = [
    {"name": "Рыболов", "desc": "Ловить рыбу", "reward_min": 20, "reward_max": 50, "cooldown_min": 30, "mood_cost": 5, "satiety_cost": 10},
    {"name": "Почтальон", "desc": "Разносить почту", "reward_min": 30, "reward_max": 60, "cooldown_min": 45, "mood_cost": 8, "satiety_cost": 15},
    {"name": "Укротитель", "desc": "Укрощать морских зверей", "reward_min": 50, "reward_max": 100, "cooldown_min": 60, "mood_cost": 12, "satiety_cost": 20},
    {"name": "Водолаз", "desc": "Исследовать глубины", "reward_min": 40, "reward_max": 80, "cooldown_min": 50, "mood_cost": 10, "satiety_cost": 18},
    {"name": "Актёр", "desc": "Выступать в шоу", "reward_min": 35, "reward_max": 70, "cooldown_min": 40, "mood_cost": 6, "satiety_cost": 12},
]

DAILY_EVENTS = [
    {"event_type": "exp_boost", "effect": "1.5", "desc": "+50% к опыту!"},
    {"event_type": "shop_discount", "effect": "0.2", "desc": "Скидки 20% в магазине!"},
    {"event_type": "fishing_bonus", "effect": "2.0", "desc": "x2 рыбнеток за рыбалку!"},
]

FACTIONS = {
    "hunters": {"name": "Стая охотников", "desc": "Бонус за бои"},
    "fashion": {"name": "Клуб модников", "desc": "Бонус к настроению"},
    "explorers": {"name": "Гильдия исследователей", "desc": "Бонус к опыту"},
}

RANDOM_ENCOUNTERS = [
    {"name": "Сундук на берегу!", "type": "item", "chance": 0.12, "items": ["Чешуя", "Панцирь", "Акулий зуб", "Жемчуг", "Коралл", "Ледяной кристалл"]},
    {"name": "Злой краб!", "type": "battle", "chance": 0.10, "mood_cost": 10, "satiety_cost": 10, "drop": {"Панцирь": 0.5}},
    {"name": "Дружелюбный дельфин", "type": "hint", "chance": 0.08, "fishnet_reward": (10, 30)},
    {"name": "Затонувший корабль", "type": "fishnets", "chance": 0.06, "fishnet_reward": (30, 80)},
    {"name": "Морская ведьма", "type": "item", "chance": 0.05, "items": ["Тёмная эссенция", "Кровь кракена", "Призрачная эссенция"]},
    {"name": "Драконья пещера", "type": "item", "chance": 0.03, "items": ["Драконья чешуя", "Огненный камень"]},
]

QUEST_TEMPLATES = [
    {"type": "play", "target": 3, "reward": 30, "desc": "Поиграть 3 раза"}, {"type": "feed", "target": 3, "reward": 30, "desc": "Покормить 3 раза"},
    {"type": "battle", "target": 1, "reward": 40, "desc": "Победить 1 босса"}, {"type": "dungeon", "target": 1, "reward": 50, "desc": "Пройти 1 подземелье"},
    {"type": "shop", "target": 1, "reward": 20, "desc": "Купить 1 предмет"}, {"type": "work", "target": 1, "reward": 35, "desc": "Отправить на работу"},
    {"type": "craft", "target": 1, "reward": 25, "desc": "Скрафтить 1 предмет"}, {"type": "fish", "target": 1, "reward": 25, "desc": "Поймать 1 рыбу"},
    {"type": "potion", "target": 1, "reward": 30, "desc": "Сварить 1 зелье"}, {"type": "enchant", "target": 1, "reward": 40, "desc": "Зачаровать 1 предмет"},
]
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
    m = re.search(r'$$([A-Z])$$', item_name)
    if m and m.group(1) in RARITY_SELL_PRICES:
        return RARITY_SELL_PRICES[m.group(1)]
    for recipe in CRAFT_RECIPES:
        if recipe["name"] == item_name:
            total = sum(RESOURCE_SELL_PRICES.get(r, 5) * a for r, a in recipe["resources"].items())
            return int(total * 0.6)
    return 5

def exp_for_level(lvl):
    return lvl * 100 + (lvl - 1) * 50

def get_exp_mult():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT effect FROM active_events WHERE active=1 AND event_type='exp_boost' AND expires_at > ?", (now,)); r = c.fetchone(); conn.close()
    if r:
        try: return float(r[0])
        except ValueError: return 1.0
    return 1.0

def get_shop_disc():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT effect FROM active_events WHERE active=1 AND event_type='shop_discount' AND expires_at > ?", (now,)); r = c.fetchone(); conn.close()
    if r:
        try: return float(r[0])
        except ValueError: return 0.0
    return 0.0

def get_fish_bonus():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT effect FROM active_events WHERE active=1 AND event_type='fishing_bonus' AND expires_at > ?", (now,)); r = c.fetchone(); conn.close()
    if r:
        try: return float(r[0])
        except ValueError: return 1.0
    return 1.0

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
            update_seal(sid, level=nl, exp=ne, strength=seal[7]+random.randint(2,5),
                        defense=seal[8]+random.randint(1,3), max_health=new_max_hp, health=new_max_hp)
            results.append(nl)
            if nl % 5 == 0:
                skill = random.choice(SEAL_SKILLS_POOL)
                conn = sqlite3.connect(DB_PATH); c = conn.cursor()
                c.execute("INSERT INTO seal_skills (seal_id, skill_name, skill_effect, acquired_at) VALUES (?, ?, ?, ?)",
                          (sid, skill["name"], skill["effect"], datetime.now().isoformat()))
                conn.commit(); conn.close()
            uid = uid_owner(sid)
            if uid: update_quest_chain(uid, "reach_level", nl)
        else: break
    return results[-1] if results else False

def get_potion_info(potion_name):
    for r in CRAFT_RECIPES:
        if r["name"] == potion_name and r.get("effect"):
            return r
    return None

def apply_potion_to_seal(sid, potion_name):
    info = get_potion_info(potion_name)
    if not info: return "Неизвестное зелье!"
    seal = get_seal(sid)
    if not seal: return "Тюлень не найден!"
    eff = info["effect"]; val = info.get("value", 0)
    if eff == "heal":
        nh = min(seal[4], seal[3] + val)
        update_seal(sid, health=nh)
        return f"💚 +{val} HP! ({seal[3]}->{nh})"
    elif eff == "antidote":
        update_seal(sid, mood=min(100, seal[5] + 10))
        return "💊 Отравление снято!"
    else:
        dur = info.get("duration", 3)
        update_seal(sid, active_potion=f"{eff}:{val}:{dur}", potion_uses=dur)
        return f"🧪 {potion_name} активно! Эффект: {POTION_EFFECTS.get(eff, '?')} на {dur} боёв"

def get_active_potion_mods(sid):
    seal = get_seal(sid)
    if not seal: return 0, 0, 0, 0, 0, 0
    ap = seal[23] if len(seal) > 23 else None
    if not ap: return 0, 0, 0, 0, 0, 0
    try:
        eff, val, _ = ap.split(":"); val = int(val)
    except: return 0, 0, 0, 0, 0, 0
    bs = bd = dd = rg = sp = tn = 0
    if eff == "str_boost": bs = val
    elif eff == "def_boost": bd = val
    elif eff == "dodge_boost": dd = val
    elif eff == "regen_potion": rg = val
    elif eff == "speed_boost": sp = 1
    elif eff == "rage": bs = int(val * 0.5)
    elif eff == "titan": bs = val; bd = val
    return bs, bd, dd, rg, sp, tn

def decrement_potion_use(sid):
    seal = get_seal(sid)
    if not seal: return
    uses = _safe_int(seal[24]) if len(seal) > 24 else 0
    if uses <= 1:
        update_seal(sid, active_potion=None, potion_uses=0)
    else:
        update_seal(sid, potion_uses=uses - 1)

def get_enchantment_for_item(uid, item_name):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT enchantment FROM item_enchantments WHERE user_id=? AND item_name=?", (uid, item_name)); r = c.fetchone(); conn.close()
    return r[0] if r else None

def can_enchant(uid, ench_name):
    ench = ENCHANTMENTS.get(ench_name)
    if not ench: return False
    return all(get_item_qty(uid, r) >= a for r, a in ench["cost"].items())

def do_enchant_item(uid, item_name, ench_name):
    ench = ENCHANTMENTS.get(ench_name)
    if not ench: return "Неизвестное зачарование!"
    if get_item_qty(uid, item_name) <= 0: return "Нет предмета!"
    if not can_enchant(uid, ench_name): return "Не хватает ресурсов!"
    for res, amt in ench["cost"].items(): remove_from_inv(uid, res, amt)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT ench_id FROM item_enchantments WHERE user_id=? AND item_name=?", (uid, item_name)); ex = c.fetchone()
    if ex:
        c.execute("UPDATE item_enchantments SET enchantment=? WHERE ench_id=?", (ench_name, ex[0]))
    else:
        c.execute("INSERT INTO item_enchantments (user_id,item_name,enchantment,created_at) VALUES (?,?,?,?)",
                  (uid, item_name, ench_name, datetime.now().isoformat()))
    conn.commit(); conn.close()
    return f"✨ {item_name} зачарован: {ench_name}!"

def get_enchanted_stats(uid, item_name):
    ench_name = get_enchantment_for_item(uid, item_name)
    if not ench_name: return 0, 0
    ench = ENCHANTMENTS.get(ench_name, {})
    return ench.get("bonus_str", 0), ench.get("bonus_def", 0)

def get_effective_stats(sid):
    seal = get_seal(sid)
    if not seal: return 0, 0, 0
    base_str = _safe_int(seal[7]); base_def = _safe_int(seal[8]); base_hp = _safe_int(seal[4])
    uid = uid_owner(sid)
    slots = [seal[13], seal[14], seal[15], seal[16], seal[17]]
    if len(seal) > 22 and seal[22]: slots.append(seal[22])
    bs = bd = bh = 0
    for item_name in slots:
        if not item_name: continue
        if item_name in ITEM_BONUSES:
            b = ITEM_BONUSES[item_name]; bs += _safe_int(b.get("str",0)); bd += _safe_int(b.get("def",0)); bh += _safe_int(b.get("hp",0))
        if uid:
            es, ed = get_enchanted_stats(uid, item_name)
            bs += es; bd += ed
    ps, pd, _, _, _, _ = get_active_potion_mods(sid)
    bs += ps; bd += pd
    return base_str + bs, base_def + bd, base_hp + bh

def get_mood_bonus(sid):
    seal = get_seal(sid)
    if not seal or len(seal) < 18: return 0
    acc = seal[17]
    return _safe_int(ACCESSORY_BONUSES.get(acc, 0)) if acc else 0

def can_craft(uid, recipe): return all(get_item_qty(uid, r) >= a for r, a in recipe["resources"].items())

def get_craft_tier_label(recipe):
    tier = recipe.get("tier", "common")
    return CRAFT_TIER_LABEL.get(tier, "Обычный")

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
    wc = seal[18] if len(seal) > 18 else None
    if wc:
        try:
            cm = _safe_int(seal[21]) if len(seal) > 21 else 30
            if datetime.now() - datetime.fromisoformat(wc) < timedelta(minutes=cm): return "💼"
        except: pass
    if mood >= 50 and satiety >= 50: return "🎮"
    return "🦭"

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
        c2.execute("SELECT steps_json, reward_json, reward_fishnets FROM quest_chains WHERE chain_id=?", (cid,)); chain = c2.fetchone()
        if not chain: continue
        try: steps = json.loads(chain[0])
        except json.JSONDecodeError: continue
        if cs < len(steps) and steps[cs]["type"] == step_type:
            if step_type in ("reach_level", "dungeon_floor"):
                ns = max(sp, amount)
            else:
                ns = sp + 1
            if ns >= steps[cs]["target"]:
                ns = 0; cs2 = cs + 1
                if cs2 >= len(steps):
                    c2.execute("UPDATE player_quest_chains SET completed=1 WHERE id=?", (pc_id,))
                    try:
                        reward = json.loads(chain[1])
                        add_to_inv(uid, reward["item"], reward.get("type", "accessory"), 1)
                    except: pass
                    if chain[2]: add_fishnets(uid, chain[2])
                else:
                    c2.execute("UPDATE player_quest_chains SET current_step=?, step_progress=0 WHERE id=?", (cs2, pc_id))
            else:
                c2.execute("UPDATE player_quest_chains SET step_progress=? WHERE id=?", (ns, pc_id))
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
    c.execute("INSERT INTO duels (challenger_id, opponent_id, challenger_seal_id, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
              (cid, oid, csid, datetime.now().isoformat()))
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
        c.execute("INSERT INTO daily_quests (user_id,quest_type,quest_target,quest_progress,quest_reward,date,claimed) VALUES (?,?,?,0,?,?,0)",
                  (uid, q["type"], q["target"], q["reward"], today))
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
    chest_name = f"Сундук [{rarity}]"
    if get_item_qty(uid, chest_name) <= 0: return "Нет сундука!"
    remove_from_inv(uid, chest_name)
    fn_range = CHEST_CONTENTS.get(rarity, {"fishnets": (10, 30)})
    fishnets = random.randint(fn_range["fishnets"][0], fn_range["fishnets"][1])
    add_fishnets(uid, fishnets)
    msg = f"📦 Сундук [{rarity}] открыт!\n🐟 {fishnets}\n"
    roll = random.random()
    if roll < 0.25:
        items = ARTIFACTS.get(rarity, [])
        if items:
            art = random.choice(items)
            fn = f"{art['name']} [{rarity}]"
            add_to_inv(uid, fn, "artifact", 1)
            msg += f"✨ Артефакт: {fn}\n"
    elif roll < 0.55:
        items = CHEST_WEAPONS.get(rarity, [])
        if items:
            w = random.choice(items)
            fn = f"{w['name']} [{rarity}]"
            add_to_inv(uid, fn, "weapon", 1)
            msg += f"⚔️ Оружие: {fn}\n"
    elif roll < 0.80:
        items = CHEST_ARMOR.get(rarity, [])
        if items:
            a = random.choice(items)
            fn = f"{a['name']} [{rarity}]"
            add_to_inv(uid, fn, "armor", 1)
            msg += f"🛡️ Броня: {fn}\n"
    return msg
# ==================== ГЛАВНОЕ МЕНЮ ====================
def show_main_menu(chat_id):
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add(types.KeyboardButton("🦭 Мой тюлень"), types.KeyboardButton("👤 Профиль"))
    m.add(types.KeyboardButton("🎒 Инвентарь"), types.KeyboardButton("🛒 Магазин"))
    m.add(types.KeyboardButton("⚔️ Бой"), types.KeyboardButton("🏰 Подземелье"))
    m.add(types.KeyboardButton("💼 Работа"), types.KeyboardButton("🔨 Крафт"))
    m.add(types.KeyboardButton("🧪 Зелья"), types.KeyboardButton("✨ Зачарование"))
    m.add(types.KeyboardButton("📋 Задания"), types.KeyboardButton("💍 Брак"))
    m.add(types.KeyboardButton("🎣 Рыбалка"), types.KeyboardButton("🏆 Лидеры"))
    m.add(types.KeyboardButton("📦 Биржа"), types.KeyboardButton("🏛 Фракции"))
    m.add(types.KeyboardButton("🤺 Дуэль"), types.KeyboardButton("📚 Цепочки"))
    m.add(types.KeyboardButton("🐋 Клан"), types.KeyboardButton("💰 Продажа"))
    bot.send_message(chat_id, "🦭 Выберите действие:", reply_markup=m)

def show_inline_menu(chat_id):
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🦭 Тюлень", callback_data="menu_seal"),
          types.InlineKeyboardButton("👤 Профиль", callback_data="menu_profile"))
    m.add(types.InlineKeyboardButton("🎒 Инвентарь", callback_data="menu_inv"),
          types.InlineKeyboardButton("🛒 Магазин", callback_data="menu_shop"))
    m.add(types.InlineKeyboardButton("⚔️ Бой", callback_data="menu_battle"),
          types.InlineKeyboardButton("🏰 Подземелье", callback_data="menu_dungeon"))
    m.add(types.InlineKeyboardButton("💼 Работа", callback_data="menu_work"),
          types.InlineKeyboardButton("🔨 Крафт", callback_data="menu_craft"))
    m.add(types.InlineKeyboardButton("🧪 Зелья", callback_data="menu_potion"),
          types.InlineKeyboardButton("✨ Зачарование", callback_data="menu_enchant"))
    m.add(types.InlineKeyboardButton("📋 Задания", callback_data="menu_quests"),
          types.InlineKeyboardButton("💍 Брак", callback_data="menu_marry"))
    m.add(types.InlineKeyboardButton("🎣 Рыбалка", callback_data="menu_fish"),
          types.InlineKeyboardButton("🏆 Лидеры", callback_data="menu_lb"))
    m.add(types.InlineKeyboardButton("📦 Биржа", callback_data="menu_trade"),
          types.InlineKeyboardButton("🏛 Фракции", callback_data="menu_faction"))
    m.add(types.InlineKeyboardButton("🤺 Дуэль", callback_data="menu_duel"),
          types.InlineKeyboardButton("📚 Цепочки", callback_data="menu_qc"))
    m.add(types.InlineKeyboardButton("🐋 Клан", callback_data="menu_clan"),
          types.InlineKeyboardButton("💰 Продажа", callback_data="menu_sell"))
    bot.send_message(chat_id, "🦭 *Мир Тюленей*\nВыберите действие:", reply_markup=m, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("menu_"))
def menu_router(call):
    uid = call.from_user.id; cid = call.message.chat.id
    action = call.data[5:]
    class FakeMsg:
        def __init__(self, from_user, chat, message_id):
            self.from_user = from_user
            self.chat = chat
            self.message_id = message_id
            self.text = ""
    class FakeChat:
        def __init__(self, cid):
            self.id = cid
            self.type = "private"
    fake = FakeMsg(call.from_user, FakeChat(cid), call.message.message_id)
    handlers = {
        "seal": menu_seal, "profile": cmd_profile, "inv": cmd_inventory,
        "shop": menu_shop, "battle": menu_battle, "dungeon": menu_dungeon,
        "work": menu_work, "craft": menu_craft, "potion": menu_potion,
        "enchant": menu_enchant, "quests": menu_quests, "marry": menu_marry,
        "fish": cmd_fish, "lb": cmd_leaderboard, "trade": menu_trade,
        "faction": menu_faction, "duel": cmd_duel, "qc": cmd_questchain,
        "clan": menu_clan, "sell": menu_sell,
    }
    fn = handlers.get(action)
    if fn:
        try: fn(fake)
        except Exception as e: bot.send_message(cid, f"⚠️ {e}")
    else:
        bot.answer_callback_query(call.id, "Неизвестное действие")

# ==================== /start ====================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.from_user.id; cid = message.chat.id
    uname = message.from_user.username or message.from_user.first_name
    p = get_player(uid)
    if not p:
        sn = random.choice(SEAL_NAMES)
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("INSERT INTO players (user_id, username, fishnets, faction, faction_rep, fish_cooldown) VALUES (?,?,?,NULL,0,NULL)",
                  (uid, uname, START_FISHNETS))
        c.execute("INSERT INTO seals (owner_id, name, health, max_health, mood, satiety, strength, defense, level, exp, is_baby, born_at) VALUES (?,?,?,?,?,?,?,?,?,0,0,?)",
                  (uid, sn, 100, 100, 80, 80, random.randint(10,15), random.randint(5,10), 1, datetime.now().isoformat()))
        conn.commit(); conn.close()
        bot.send_message(cid, f"🦭 Добро пожаловать в Мир Тюленей!\n\nТюлень *{sn}* и 🐟{START_FISHNETS} рыбнеток ваши!\nКормите, воспитывайте, сражайтесь!", parse_mode='Markdown')
    else:
        update_player(uid, username=uname)
        bot.send_message(cid, f"🦭 С возвращением, {uname}!")
    if message.chat.type == "private":
        show_main_menu(cid)
    else:
        show_inline_menu(cid)

# ==================== /help ====================
@bot.message_handler(commands=['help'])
def cmd_help(message):
    cid = message.chat.id
    t = ("🦭 *Справка по миру тюленей*\n\n"
         "• `/start` — начать игру\n"
         "• `/menu` — главное меню (в беседах)\n"
         "• `/profile` — профиль игрока\n"
         "• `/gallery` — галерея тюленей\n"
         "• `/inventory` — инвентарь\n"
         "• `/shop` — магазин\n"
         "• `/craft` — крафт предметов\n"
         "• `/potion` — варка зелий\n"
         "• `/enchant` — зачарование\n"
         "• `/battle` — бой с боссом\n"
         "• `/dungeon` — подземелье (10 этажей)\n"
         "• `/work` — отправить тюленя на работу\n"
         "• `/duel` — PvP-дуэль\n"
         "• `/fish` — рыбалка\n"
         "• `/vote` — голосование за событие\n"
         "• `/faction` — фракции\n"
         "• `/questchain` — квестовые цепочки\n"
         "• `/clan` — кланы\n"
         "• `/marry` — брак тюленей\n"
         "• `/quests` — ежедневные задания\n"
         "• `/leaderboard` — таблица лидеров\n\n"
         "🐟 — рыбнеток (валюта)\n"
         "💪 — сила, 🛡️ — защита, ❤️ — здоровье\n"
         "😊 — настроение, 🍖 — сытость\n")
    bot.send_message(cid, t, parse_mode='Markdown')

# ==================== /menu ====================
@bot.message_handler(commands=['menu'])
def cmd_menu(message):
    show_inline_menu(message.chat.id)

# ==================== ЛИДЕРЫ ====================
@bot.message_handler(commands=['leaderboard'])
@bot.message_handler(func=lambda m: m.text == "🏆 Лидеры" and m.chat.type == "private")
def cmd_leaderboard(message):
    cid = message.chat.id
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT username, fishnets FROM players ORDER BY fishnets DESC LIMIT 10")
    rows = c.fetchall(); conn.close()
    t = "🏆 *Топ-10 по рыбнеткам*\n\n"
    for i, (uname, fn) in enumerate(rows, 1):
        t += f"{i}. @{uname or '?'} — 🐟{fn}\n"
    bot.send_message(cid, t, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data == "back_main")
def back_main(call):
    cid = call.message.chat.id
    if call.message.chat.type == "private":
        try: bot.delete_message(cid, call.message.message_id)
        except: pass
        show_main_menu(cid)
    else:
        show_inline_menu(cid)

# ==================== ПРОФИЛЬ ====================
@bot.message_handler(commands=['profile'])
@bot.message_handler(func=lambda m: m.text == "👤 Профиль" and m.chat.type == "private")
def cmd_profile(message):
    uid = message.from_user.id; cid = message.chat.id
    p = get_player(uid)
    if not p: bot.send_message(cid, "Напишите /start"); return
    seals = get_player_seals(uid); sc = len(seals)
    fn = get_fishnets(uid); uname = p[1] or message.from_user.first_name
    faction = p[5] if len(p) > 5 else None
    rep = _safe_int(p[6]) if len(p) > 6 else 0
    fn_name = FACTIONS.get(faction, {}).get("name", "Нет") if faction else "Нет"
    t = f"👤 *Профиль: {uname}*\n\n"
    t += f"🐟 Рыбнетки: {fn}\n"
    t += f"🦭 Тюленей: {sc}/{MAX_SEALS}\n"
    t += f"🏛 Фракция: {fn_name}\n"
    if faction: t += f"🏅 Репутация: {rep}\n"
    clan = get_clan_by_user(uid)
    if clan: t += f"🐋 Клан: {clan[1]} {clan[2]}\n"
    act = get_active_event_text()
    if act: t += f"\n🎉 Активное событие: {act}\n"
    bot.send_message(cid, t, parse_mode='Markdown')

# ==================== ИНВЕНТАРЬ ====================
@bot.message_handler(commands=['inventory'])
@bot.message_handler(func=lambda m: m.text == "🎒 Инвентарь" and m.chat.type == "private")
def cmd_inventory(message):
    uid = message.from_user.id; cid = message.chat.id
    inv = get_inv(uid)
    if not inv: bot.send_message(cid, "🎒 Пусто!"); return
    t = "🎒 *Инвентарь*\n\n"
    m = types.InlineKeyboardMarkup()
    chests = [i for i in inv if i[3] == "chest"]
    other = [i for i in inv if i[3] != "chest"]
    if chests:
        t += "*Сундуки:*\n"
        for i in chests:
            t += f"  📦 {i[2]} (x{i[4]})\n"
            m.add(types.InlineKeyboardButton(f"Открыть {i[2]} (x{i[4]})", callback_data=f"openchest_{i[2]}"))
        t += "\n"
    categories = {}
    for i in other:
        cat = i[3] if i[3] else "misc"
        categories.setdefault(cat, []).append(i)
    for cat, items in categories.items():
        t += f"*{cat}:*\n"
        for i in items:
            t += f"  {i[2]} (x{i[4]}) — 🐟{get_sell_price(i[2])}\n"
            m.add(types.InlineKeyboardButton(f"Продать {i[2]} — 🐟{get_sell_price(i[2])}", callback_data=f"sellitem_{i[2]}"))
        t += "\n"
    m.add(types.InlineKeyboardButton("◀️ В меню", callback_data="invback"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("openchest_"))
def open_chest_do(call):
    uid = call.from_user.id; cid = call.message.chat.id
    chest_name = call.data[len("openchest_"):]
    start = chest_name.find('['); end = chest_name.find(']')
    if start == -1 or end == -1 or end <= start:
        bot.answer_callback_query(call.id, f"Не удалось определить редкость: {chest_name}"); return
    rarity = chest_name[start+1:end]
    try: result = open_chest(uid, rarity)
    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка: {e}"); return
    bot.answer_callback_query(call.id, "✅ Открыт!")
    bot.send_message(cid, result, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("sellitem_"))
def sell_do(call):
    uid = call.from_user.id; cid = call.message.chat.id
    name = call.data[9:]
    qty = get_item_qty(uid, name)
    if qty <= 0: bot.answer_callback_query(call.id, "Нет!"); return
    sp = get_sell_price(name)
    if sp <= 0: bot.answer_callback_query(call.id, "Нельзя продать!"); return
    remove_from_inv(uid, name, 1); add_fishnets(uid, sp)
    bot.answer_callback_query(call.id, f"Продано {name} за 🐟{sp}!")

@bot.callback_query_handler(func=lambda c: c.data == "invback")
def inv_back(call):
    cid = call.message.chat.id
    if call.message.chat.type == "private":
        show_main_menu(cid)
    else:
        show_inline_menu(cid)

# ==================== ПРОДАЖА (меню) ====================
@bot.message_handler(commands=['sell'])
@bot.message_handler(func=lambda m: m.text == "💰 Продажа" and m.chat.type == "private")
def menu_sell(message):
    uid = message.from_user.id; cid = message.chat.id
    inv = get_inv(uid)
    if not inv: bot.send_message(cid, "🎒 Пусто!"); return
    t = "💰 *Продажа*\n\n"; m = types.InlineKeyboardMarkup()
    for i in inv:
        sp = get_sell_price(i[2])
        if sp > 0:
            t += f"  {i[2]} (x{i[4]}) — 🐟{sp}\n"
            m.add(types.InlineKeyboardButton(f"Продать {i[2]} — 🐟{sp}", callback_data=f"sellitem_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="invback"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

# ==================== ГАЛЕРЕЯ ====================
@bot.message_handler(commands=['gallery'])
@bot.message_handler(func=lambda m: m.text == "🦭 Мой тюлень" and m.chat.type == "private")
def menu_seal(message):
    uid = message.from_user.id; cid = message.chat.id
    seals = get_player_seals(uid)
    if not seals: bot.send_message(cid, "Нет тюленей! /start"); return
    married = get_married_ids()
    t = "🦭 *Ваши тюлени*\n\n"; m = types.InlineKeyboardMarkup()
    for s in seals:
        st = get_seal_status(s, married)
        t += f"  {st} {s[2]} (ур.{s[9]}) ❤️{s[3]}/{s[4]} 😊{s[5]} 🍖{s[6]}\n"
        m.add(types.InlineKeyboardButton(f"{st} {s[2]}", callback_data=f"sinfo_{s[0]}"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sinfo_"))
def seal_selected(call):
    uid = call.from_user.id; cid = call.message.chat.id
    sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    es, ed, eh = get_effective_stats(sid)
    skills = get_seal_skills(sid); sk = ", ".join(s["name"] for s in skills) if skills else "нет"
    ench = get_enchantment_for_item(uid, seal[13]) if seal[13] else None
    ap = seal[23] if len(seal) > 23 and seal[23] else None
    t = (f"🦭 *{seal[2]}*\n\n"
         f"❤️ {seal[3]}/{seal[4]} (макс {eh})\n"
         f"💪 {es} (база {seal[7]})\n"
         f"🛡️ {ed} (база {seal[8]})\n"
         f"😊 {seal[5]}  🍖 {seal[6]}\n"
         f"📈 Ур.{seal[9]} (оп {seal[10]}/{exp_for_level(seal[9])})\n")
    if seal[11] == 1: t += f"🍼 Малыш (вырастет через {BABY_GROW_DAYS} дн.)\n"
    if seal[13]: t += f"⚔️ Оружие: {seal[13]}" + (f" [{ench}]" if ench else "") + "\n"
    if seal[14]: t += f"🛡️ Броня: {seal[14]}\n"
    if seal[15]: t += f"🪖 Шлем: {seal[15]}\n"
    if seal[16]: t += f"🛡️ Щит: {seal[16]}\n"
    if seal[17]: t += f"🎖️ Аксессуар: {seal[17]} (+{ACCESSORY_BONUSES.get(seal[17], 0)}😊)\n"
    if ap: t += f"🧪 Активное зелье: {ap}\n"
    t += f"🎯 Навыки: {sk}\n"
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("🍖 Кормить", callback_data=f"feed_{sid}"),
          types.InlineKeyboardButton("🎮 Играть", callback_data=f"play_{sid}"))
    m.add(types.InlineKeyboardButton("⚔️ Бой", callback_data=f"bat_{sid}"),
          types.InlineKeyboardButton("🏰 Подземелье", callback_data=f"ds_{sid}"))
    m.add(types.InlineKeyboardButton("💼 Работа", callback_data=f"wsel_{sid}"),
          types.InlineKeyboardButton("🧪 Зелье", callback_data=f"spot_{sid}"))
    m.add(types.InlineKeyboardButton("⚔️ Экипировка", callback_data=f"equip_{sid}"),
          types.InlineKeyboardButton("✏️ Переименовать", callback_data=f"rename_{sid}"))
    if seal[11] == 0:
        m.add(types.InlineKeyboardButton("📷 Фото", callback_data=f"setphoto_{sid}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="back_main"))
    photo = seal[20] if len(seal) > 20 and seal[20] else None
    if photo:
        try:
            bot.send_photo(cid, photo, t, parse_mode='Markdown', reply_markup=m)
        except:
            bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)
    else:
        bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("feed_"))
def seal_feed(call):
    uid = call.from_user.id; cid = call.message.chat.id
    sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    inv = get_inv(uid)
    food = [i for i in inv if i[3] == "food"]
    if not food: bot.answer_callback_query(call.id, "Нет еды!"); return
    m = types.InlineKeyboardMarkup()
    for i in food:
        info = SHOP_ITEMS.get(i[2], {})
        m.add(types.InlineKeyboardButton(f"{i[2]} (x{i[4]}) +{info.get('satiety',0)}", callback_data=f"dfd_{sid}_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data=f"sinfo_{sid}"))
    try: bot.edit_message_text("Чем кормить?", cid, call.message.message_id, reply_markup=m)
    except:
        try: bot.delete_message(cid, call.message.message_id)
        except: pass
        bot.send_message(cid, "Чем кормить?", reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dfd_"))
def seal_feed_do(call):
    uid = call.from_user.id; cid = call.message.chat.id
    p = call.data.split("_", 2); sid = int(p[1]); fname = p[2]
    seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    if get_item_qty(uid, fname) <= 0: bot.answer_callback_query(call.id, "Нет еды!"); return
    info = SHOP_ITEMS.get(fname, {}); sat = info.get("satiety", 10)
    ns = min(100, seal[6] + sat); remove_from_inv(uid, fname, 1)
    update_seal(sid, satiety=ns, mood=min(100, seal[5] + 5))
    update_quest_progress(uid, "feed", 1)
    bot.answer_callback_query(call.id, f"🍖 {fname}! Сытость {ns}/100")

@bot.callback_query_handler(func=lambda c: c.data.startswith("play_"))
def seal_play(call):
    uid = call.from_user.id; cid = call.message.chat.id
    sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    if seal[6] < 20: bot.answer_callback_query(call.id, "Сытость<20!"); return
    pc = seal[19] if len(seal) > 19 else None
    if pc:
        try:
            if datetime.now() - datetime.fromisoformat(pc) < timedelta(minutes=PLAY_COOLDOWN_MIN):
                bot.answer_callback_query(call.id, "Тюлень устал! Подождите."); return
        except: pass
    nm = min(100, seal[5] + random.randint(15, 25))
    ns = max(0, seal[6] - random.randint(5, 10))
    update_seal(sid, mood=nm, satiety=ns, play_cooldown=datetime.now().isoformat())
    update_quest_progress(uid, "play", 1)
    bot.answer_callback_query(call.id, f"🎮 Настроение {nm}/100! Сытость {ns}/100")
    enc = trigger_encounter(uid)
    if enc:
        try: bot.send_message(cid, enc, parse_mode='Markdown')
        except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("equip_"))
def seal_equip_menu(call):
    uid = call.from_user.id; cid = call.message.chat.id
    sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    inv = get_inv(uid)
    gt = ("weapon", "armor", "helmet", "shield", "accessory", "artifact")
    gi = [i for i in inv if ITEM_TYPES.get(i[2]) in gt]
    if not gi: bot.answer_callback_query(call.id, "Нет экипировки!"); return
    m = types.InlineKeyboardMarkup()
    for i in gi:
        ench = get_enchantment_for_item(uid, i[2])
        label = f"{i[2]} (x{i[4]})" + (f" [{ench}]" if ench else "")
        m.add(types.InlineKeyboardButton(label, callback_data=f"deq_{sid}_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data=f"sinfo_{sid}"))
    try: bot.edit_message_text("Что надеть?", cid, call.message.message_id, reply_markup=m)
    except:
        try: bot.delete_message(cid, call.message.message_id)
        except: pass
        bot.send_message(cid, "Что надеть?", reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("deq_"))
def seal_equip_do(call):
    uid = call.from_user.id; cid = call.message.chat.id
    p = call.data.split("_", 2); sid = int(p[1]); item_name = p[2]
    seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    if get_item_qty(uid, item_name) <= 0: bot.answer_callback_query(call.id, "Нет предмета!"); return
    it_type = ITEM_TYPES.get(item_name, "misc")
    slot_map = {"weapon": 13, "armor": 14, "helmet": 15, "shield": 16, "accessory": 17, "artifact": 22}
    if it_type not in slot_map: bot.answer_callback_query(call.id, "Нельзя надеть!"); return
    old = seal[slot_map[it_type]]
    if old: add_to_inv(uid, old, ITEM_TYPES.get(old, it_type), 1)
    slot_col_map = {"weapon": "equipped_weapon", "armor": "equipped_armor", "helmet": "equipped_helmet",
                    "shield": "equipped_shield", "accessory": "equipped_accessory", "artifact": "equipped_artifact"}
    update_seal(sid, **{slot_col_map[it_type]: item_name})
    remove_from_inv(uid, item_name)
    bot.answer_callback_query(call.id, f"✅ Надето: {item_name}!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("spot_"))
def seal_potion_menu(call):
    uid = call.from_user.id; cid = call.message.chat.id
    sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    inv = get_inv(uid)
    potions = [i for i in inv if i[3] == "potion"]
    if not potions: bot.answer_callback_query(call.id, "Нет зелий! /potion"); return
    m = types.InlineKeyboardMarkup()
    for i in potions:
        info = get_potion_info(i[2])
        desc = POTION_EFFECTS.get(info["effect"], "?") if info else "?"
        m.add(types.InlineKeyboardButton(f"{i[2]} (x{i[4]}) — {desc}", callback_data=f"spotuse_{sid}_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data=f"sinfo_{sid}"))
    try: bot.edit_message_text("🧪 Какое зелье использовать?", cid, call.message.message_id, reply_markup=m)
    except:
        try: bot.delete_message(cid, call.message.message_id)
        except: pass
        bot.send_message(cid, "🧪 Какое зелье использовать?", reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("spotuse_"))
def seal_potion_use(call):
    uid = call.from_user.id; cid = call.message.chat.id
    p = call.data.split("_", 2); sid = int(p[1]); pname = p[2]
    seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    if get_item_qty(uid, pname) <= 0: bot.answer_callback_query(call.id, "Нет зелья!"); return
    result = apply_potion_to_seal(sid, pname)
    if "🧪" in result or "💚" in result or "💊" in result:
        remove_from_inv(uid, pname); update_quest_progress(uid, "potion", 1)
    bot.answer_callback_query(call.id, result)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rename_"))
def seal_rename(call):
    uid = call.from_user.id; cid = call.message.chat.id
    sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    bot.send_message(cid, f"{call.from_user.first_name}, введите новое имя (до 20 символов):")
    bot.register_next_step_handler_by_chat_id(cid, lambda m: proc_rename(m, sid) if m.from_user.id == uid else None)

def proc_rename(message, sid):
    uid = message.from_user.id; cid = message.chat.id
    nn = message.text.strip()
    if len(nn) > 20: bot.send_message(cid, "Слишком длинное!"); return
    update_seal(sid, name=nn); bot.send_message(cid, f"✅ Теперь его зовут *{nn}*", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("setphoto_"))
def seal_setphoto(call):
    uid = call.from_user.id; cid = call.message.chat.id
    sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    bot.send_message(cid, f"{call.from_user.first_name}, отправьте фото тюленя:")
    bot.register_next_step_handler_by_chat_id(cid, lambda m: proc_setphoto(m, sid) if m.from_user.id == uid else None)

def proc_setphoto(message, sid):
    uid = message.from_user.id; cid = message.chat.id
    if not message.photo: bot.send_message(cid, "Нужно фото!"); return
    file_id = message.photo[-1].file_id
    update_seal(sid, photo_path=file_id); bot.send_message(cid, "✅ Фото установлено!")
# ==================== МАГАЗИН ====================
@bot.message_handler(commands=['shop'])
@bot.message_handler(func=lambda m: m.text == "🛒 Магазин" and m.chat.type == "private")
def menu_shop(message):
    cid = message.chat.id
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🛒 Купить", callback_data="shbuy"),
          types.InlineKeyboardButton("💰 Продать", callback_data="shsell"))
    m.add(types.InlineKeyboardButton("📦 Сундуки", callback_data="shchest"))
    bot.send_message(cid, "🛒 *Магазин*\n\nВыберите действие:", parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data == "shbuy")
def shop_buy_menu(call):
    uid = call.from_user.id; cid = call.message.chat.id
    disc = get_shop_disc(); mult = 1.0 - disc
    t = "🛒 *Покупка*\n\n"; m = types.InlineKeyboardMarkup()
    for name, info in SHOP_ITEMS.items():
        price = int(info["price"] * mult)
        t += f"  {name} — 🐟{price}\n"
        m.add(types.InlineKeyboardButton(f"{name} — 🐟{price}", callback_data=f"buy_{name}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="shback"))
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except: bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_"))
def shop_buy_do(call):
    uid = call.from_user.id; cid = call.message.chat.id
    name = call.data[4:]; info = SHOP_ITEMS.get(name)
    if not info: bot.answer_callback_query(call.id, "Не найден!"); return
    disc = get_shop_disc(); price = int(info["price"] * (1.0 - disc))
    if get_fishnets(uid) < price: bot.answer_callback_query(call.id, "Не хватает 🐟!"); return
    add_fishnets(uid, -price); add_to_inv(uid, name, info.get("type", "misc"), 1)
    update_quest_progress(uid, "shop", 1)
    bot.answer_callback_query(call.id, f"Куплено: {name} за 🐟{price}!")

@bot.callback_query_handler(func=lambda c: c.data == "shsell")
def shop_sell_menu(call):
    uid = call.from_user.id; cid = call.message.chat.id
    inv = get_inv(uid)
    if not inv: bot.answer_callback_query(call.id, "Пусто!"); return
    t = "💰 *Продажа*\n\n"; m = types.InlineKeyboardMarkup()
    for i in inv:
        sp = get_sell_price(i[2])
        if sp > 0:
            t += f"  {i[2]} (x{i[4]}) — 🐟{sp}\n"
            m.add(types.InlineKeyboardButton(f"Продать {i[2]} — 🐟{sp}", callback_data=f"sellitem_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="shback"))
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except: bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data == "shchest")
def shop_chest_menu(call):
    uid = call.from_user.id; cid = call.message.chat.id
    t = "📦 *Сундуки*\n\n"; m = types.InlineKeyboardMarkup()
    for rarity, info in CHEST_CONTENTS.items():
        price = info.get("price", 100)
        t += f"  Сундук [{rarity}] 📦 — 🐟{price}\n"
        m.add(types.InlineKeyboardButton(f"Сундук [{rarity}] — 🐟{price}", callback_data=f"buychest_{rarity}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="shback"))
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except: bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("buychest_"))
def shop_buy_chest(call):
    uid = call.from_user.id; cid = call.message.chat.id
    rarity = call.data[9:]; info = CHEST_CONTENTS.get(rarity)
    if not info: bot.answer_callback_query(call.id, "Не найден!"); return
    price = info.get("price", 100)
    if get_fishnets(uid) < price: bot.answer_callback_query(call.id, "Не хватает 🐟!"); return
    add_fishnets(uid, -price)
    chest_name = f"Сундук [{rarity}]"
    add_to_inv(uid, chest_name, "chest", 1)
    bot.answer_callback_query(call.id, f"Куплено: {chest_name} за 🐟{price}!")

@bot.callback_query_handler(func=lambda c: c.data == "shback")
def shop_back(call):
    cid = call.message.chat.id
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🛒 Купить", callback_data="shbuy"),
          types.InlineKeyboardButton("💰 Продать", callback_data="shsell"))
    m.add(types.InlineKeyboardButton("📦 Сундуки", callback_data="shchest"))
    try: bot.edit_message_text("🛒 *Магазин*", cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except: bot.send_message(cid, "🛒 *Магазин*", parse_mode='Markdown', reply_markup=m)

# ==================== КРАФТ ====================
@bot.message_handler(commands=['craft'])
@bot.message_handler(func=lambda m: m.text == "🔨 Крафт" and m.chat.type == "private")
def menu_craft(message):
    uid = message.from_user.id; cid = message.chat.id
    t = "🔨 *Крафт*\n\n"; m = types.InlineKeyboardMarkup()
    for r in CRAFT_RECIPES:
        if r.get("effect"): continue
        can = can_craft(uid, r)
        label = "✅" if can else "❌"
        res_str = ", ".join(f"{rn}x{amt}" for rn, amt in r["resources"].items())
        tier = get_craft_tier_label(r)
        t += f"  {label} {r['name']} ({tier})\n     Нужно: {res_str}\n"
        m.add(types.InlineKeyboardButton(f"{label} {r['name']}", callback_data=f"cft_{r['name']}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="cftback"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cft_") and not c.data.startswith("cftback"))
def craft_do(call):
    uid = call.from_user.id; cid = call.message.chat.id
    name = call.data[4:]
    recipe = None
    for r in CRAFT_RECIPES:
        if r["name"] == name: recipe = r; break
    if not recipe: bot.answer_callback_query(call.id, "Рецепт не найден!"); return
    if not can_craft(uid, recipe): bot.answer_callback_query(call.id, "Не хватает ресурсов!"); return
    for res, amt in recipe["resources"].items(): remove_from_inv(uid, res, amt)
    it_type = recipe.get("type", "misc")
    add_to_inv(uid, name, it_type, 1)
    update_quest_progress(uid, "craft", 1)
    update_quest_chain(uid, "craft_item", 1)
    bot.answer_callback_query(call.id, f"✅ Создано: {name}!")

@bot.callback_query_handler(func=lambda c: c.data == "cftback")
def craft_back(call):
    cid = call.message.chat.id
    if call.message.chat.type == "private":
        show_main_menu(cid)
    else:
        show_inline_menu(cid)

# ==================== ЗЕЛЬЯ ====================
@bot.message_handler(commands=['potion'])
@bot.message_handler(func=lambda m: m.text == "🧪 Зелья" and m.chat.type == "private")
def menu_potion(message):
    uid = message.from_user.id; cid = message.chat.id
    potion_recipes = [r for r in CRAFT_RECIPES if r.get("effect")]
    if not potion_recipes: bot.send_message(cid, "Нет рецептов зелий!"); return
    t = "🧪 *Варка зелий*\n\n"; m = types.InlineKeyboardMarkup()
    for r in potion_recipes:
        can = can_craft(uid, r)
        label = "✅" if can else "❌"
        res_str = ", ".join(f"{rn}x{amt}" for rn, amt in r["resources"].items())
        eff = POTION_EFFECTS.get(r.get("effect"), "?")
        t += f"  {label} {r['name']}\n     {eff}\n     Нужно: {res_str}\n"
        m.add(types.InlineKeyboardButton(f"{label} {r['name']}", callback_data=f"pw_{r['name']}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="pwback"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("pw_") and not c.data.startswith("pwback"))
def potion_do(call):
    uid = call.from_user.id; cid = call.message.chat.id
    name = call.data[3:]
    recipe = None
    for r in CRAFT_RECIPES:
        if r["name"] == name: recipe = r; break
    if not recipe: bot.answer_callback_query(call.id, "Рецепт не найден!"); return
    if not can_craft(uid, recipe): bot.answer_callback_query(call.id, "Не хватает ресурсов!"); return
    for res, amt in recipe["resources"].items(): remove_from_inv(uid, res, amt)
    add_to_inv(uid, name, "potion", 1)
    update_quest_progress(uid, "potion", 1)
    bot.answer_callback_query(call.id, f"✅ Сварено: {name}!")

@bot.callback_query_handler(func=lambda c: c.data == "pwback")
def potion_back(call):
    cid = call.message.chat.id
    if call.message.chat.type == "private":
        show_main_menu(cid)
    else:
        show_inline_menu(cid)

# ==================== ЗАЧАРОВАНИЕ ====================
@bot.message_handler(commands=['enchant'])
@bot.message_handler(func=lambda m: m.text == "✨ Зачарование" and m.chat.type == "private")
def menu_enchant(message):
    uid = message.from_user.id; cid = message.chat.id
    inv = get_inv(uid)
    ench_items = [i for i in inv if ITEM_TYPES.get(i[2]) in ("weapon", "armor", "helmet", "shield", "accessory", "artifact")]
    if not ench_items: bot.send_message(cid, "Нет предметов для зачарования!"); return
    t = "✨ *Зачарование*\n\nВыберите предмет:\n\n"; m = types.InlineKeyboardMarkup()
    for i in ench_items:
        ench = get_enchantment_for_item(uid, i[2])
        label = f"{i[2]} (x{i[4]})" + (f" [{ench}]" if ench else "")
        m.add(types.InlineKeyboardButton(label, callback_data=f"ensel_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="enback"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("ensel_") and not c.data.startswith("enback"))
def enchant_select(call):
    uid = call.from_user.id; cid = call.message.chat.id
    item_name = call.data[6:]
    t = f"✨ *Зачарование: {item_name}*\n\nВыберите зачарование:\n\n"
    m = types.InlineKeyboardMarkup()
    for ench_name, ench in ENCHANTMENTS.items():
        can = can_enchant(uid, ench_name)
        label = "✅" if can else "❌"
        cost_str = ", ".join(f"{r}x{a}" for r, a in ench["cost"].items())
        t += f"  {label} {ench_name} — {cost_str}\n"
        m.add(types.InlineKeyboardButton(f"{label} {ench_name}", callback_data=f"endo_{item_name}_{ench_name}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="enback"))
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except: bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("endo_"))
def enchant_do(call):
    uid = call.from_user.id; cid = call.message.chat.id
    p = call.data.split("_", 2); item_name = p[1]; ench_name = p[2]
    result = do_enchant_item(uid, item_name, ench_name)
    bot.answer_callback_query(call.id, result)
    if "✅" in result or "✨" in result:
        update_quest_progress(uid, "enchant", 1)
        try: bot.edit_message_text(result, cid, call.message.message_id, parse_mode='Markdown')
        except: pass

@bot.callback_query_handler(func=lambda c: c.data == "enback")
def enchant_back(call):
    cid = call.message.chat.id
    if call.message.chat.type == "private":
        show_main_menu(cid)
    else:
        show_inline_menu(cid)

# ==================== РАБОТА ====================
@bot.message_handler(commands=['work'])
@bot.message_handler(func=lambda m: m.text == "💼 Работа" and m.chat.type == "private")
def menu_work(message):
    uid = message.from_user.id; cid = message.chat.id
    seals = get_player_seals(uid)
    if not seals: bot.send_message(cid, "Нет тюленей!"); return
    t = "💼 *Работа*\n\nВыберите тюленя:\n\n"; m = types.InlineKeyboardMarkup()
    for s in seals:
        st = get_seal_status(s, set())
        wc = s[18] if len(s) > 18 else None
        if wc:
            try:
                cm = _safe_int(s[21]) if len(s) > 21 else 30
                if datetime.now() - datetime.fromisoformat(wc) < timedelta(minutes=cm):
                    m.add(types.InlineKeyboardButton(f"💼 {s[2]} (занят)", callback_data=f"wsel_{s[0]}"))
                else:
                    m.add(types.InlineKeyboardButton(f"{st} {s[2]}", callback_data=f"wsel_{s[0]}"))
            except:
                m.add(types.InlineKeyboardButton(f"{st} {s[2]}", callback_data=f"wsel_{s[0]}"))
        else:
            m.add(types.InlineKeyboardButton(f"{st} {s[2]}", callback_data=f"wsel_{s[0]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="wback"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("wsel_") and not c.data.startswith("wback"))
def work_select(call):
    uid = call.from_user.id; cid = call.message.chat.id
    sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    wc = seal[18] if len(seal) > 18 else None
    if wc:
        try:
            cm = _safe_int(seal[21]) if len(seal) > 21 else 30
            if datetime.now() - datetime.fromisoformat(wc) < timedelta(minutes=cm):
                bot.answer_callback_query(call.id, "Тюлень ещё работает!"); return
        except: pass
    if seal[6] < 30: bot.answer_callback_query(call.id, "Сытость<30!"); return
    t = "💼 *Выберите работу*\n\n"; m = types.InlineKeyboardMarkup()
    for job in JOBS:
        t += f"  {job['name']} — 🐟{job['reward_min']}-{job['reward_max']} ({job['cooldown_min']} мин)\n"
        m.add(types.InlineKeyboardButton(f"{job['name']} — 🐟{job['reward_min']}-{job['reward_max']}", callback_data=f"wdo_{sid}_{job['name']}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="wback"))
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except: bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("wdo_"))
def work_do(call):
    uid = call.from_user.id; cid = call.message.chat.id
    p = call.data.split("_", 2); sid = int(p[1]); job_name = p[2]
    seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    job = None
    for j in JOBS:
        if j["name"] == job_name: job = j; break
    if not job: bot.answer_callback_query(call.id, "Работа не найдена!"); return
    wc = seal[18] if len(seal) > 18 else None
    if wc:
        try:
            cm = _safe_int(seal[21]) if len(seal) > 21 else 30
            if datetime.now() - datetime.fromisoformat(wc) < timedelta(minutes=cm):
                bot.answer_callback_query(call.id, "Ещё работает!"); return
        except: pass
    if seal[6] < 30: bot.answer_callback_query(call.id, "Сытость<30!"); return
    reward = random.randint(job["reward_min"], job["reward_max"]) + seal[9] * 2
    fd = get_faction_disc(uid); reward = int(reward * (1.0 + fd))
    add_fishnets(uid, reward)
    ns = max(0, seal[6] - job.get("satiety_cost", 15))
    nm = max(0, seal[5] - job.get("mood_cost", 5))
    cd = job["cooldown_min"]
    end_time = (datetime.now() + timedelta(minutes=cd)).isoformat()
    update_seal(sid, satiety=ns, mood=nm, work_cooldown=end_time, work_cooldown_min=cd)
    update_quest_progress(uid, "work", 1)
    add_faction_rep(uid, 1)
    bot.answer_callback_query(call.id, f"💼 {job_name}! +🐟{reward} (через {cd} мин)")
    try: bot.edit_message_text(
        f"💼 *{seal[2]}* уходит на работу: {job_name}\n"
        f"🐟 Награда: {reward}\n"
        f"⏱ Вернётся через {cd} мин",
        cid, call.message.message_id, parse_mode='Markdown')
    except: pass

@bot.callback_query_handler(func=lambda c: c.data == "wback")
def work_back(call):
    cid = call.message.chat.id
    if call.message.chat.type == "private":
        show_main_menu(cid)
    else:
        show_inline_menu(cid)

# ==================== БОЙ С БОССОМ ====================
@bot.message_handler(commands=['battle'])
@bot.message_handler(func=lambda m: m.text == "⚔️ Бой" and m.chat.type == "private")
def menu_battle(message):
    uid = message.from_user.id; cid = message.chat.id
    seals = get_player_seals(uid)
    if not seals: bot.send_message(cid, "Нет тюленей!"); return
    t = "⚔️ *Бой с боссом*\n\nВыберите тюленя:\n\n"; m = types.InlineKeyboardMarkup()
    married = get_married_ids()
    for s in seals:
        st = get_seal_status(s, married)
        t += f"  {st} {s[2]} (ур.{s[9]}) ❤️{s[3]}/{s[4]}\n"
        m.add(types.InlineKeyboardButton(f"{st} {s[2]}", callback_data=f"bat_{s[0]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="batback"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("bat_") and not c.data.startswith("batback"))
def battle_select(call):
    uid = call.from_user.id; cid = call.message.chat.id
    sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    if seal[3] <= 0: bot.answer_callback_query(call.id, "Тюлень мёртв!"); return
    if seal[6] < 30: bot.answer_callback_query(call.id, "Сытость<30!"); return
    t = "⚔️ *Выберите босса*\n\n"; m = types.InlineKeyboardMarkup()
    for b in BOSS_LIST:
        t += f"  {b['name']} ❤️{b['hp']} 💪{b['str']} 🛡️{b['def']}\n"
        m.add(types.InlineKeyboardButton(b['name'], callback_data=f"batdo_{sid}_{b['name']}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="batback"))
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except:
        try: bot.delete_message(cid, call.message.message_id)
        except: pass
        bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("batdo_"))
def do_battle(call):
    uid = call.from_user.id; cid = call.message.chat.id
    p = call.data.split("_", 2); sid = int(p[1]); boss_name = p[2]
    seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    if seal[3] <= 0: bot.answer_callback_query(call.id, "Тюлень мёртв!"); return
    if seal[6] < 30: bot.answer_callback_query(call.id, "Сытость<30!"); return
    boss = None
    for b in BOSS_LIST:
        if b["name"] == boss_name: boss = b; break
    if not boss: bot.answer_callback_query(call.id, "Босс не найден!"); return
    es, ed, eh = get_effective_stats(sid)
    shp = seal[3]; bhp = boss["hp"]
    mood_b = get_mood_bonus(sid)
    str_mod = 1.0 + mood_b / 100.0
    bs = es; bd = ed; bstr = boss["str"]; bdef = boss["def"]
    for rnd in range(1, 21):
        dmg_to_boss = max(1, int(bs * str_mod) - bdef // 2)
        bhp -= dmg_to_boss
        if bhp <= 0: break
        dmg_to_seal = max(1, bstr - bd // 2)
        shp -= dmg_to_seal
        if shp <= 0: break
    if bhp <= 0:
        rw = random.randint(20,50) + seal[9]*5; eg = int(random.randint(20,40) * get_exp_mult())
        add_fishnets(uid, rw)
        update_seal(sid, health=max(1,shp), exp=seal[10]+eg, mood=min(100,seal[5]+15))
        update_quest_progress(uid, "battle", 1)
        update_quest_chain(uid, "battle_count", 1)
        add_faction_rep(uid, 1)
        drops = process_drops(uid, boss.get("drops", {}))
        t = f"🏆 *Победа!* {seal[2]} одолел {boss['name']}!\n\n"
        t += f"🐟 +{rw} (ур.{seal[9]} бонус)\n"
        t += f"📈 +{eg} опыта\n"
        t += f"❤️ Осталось {max(1,shp)}/{seal[4]}\n"
        if drops: t += f"🎁 Добыча: {', '.join(drops)}\n"
        lvl = check_levelup(sid)
        if lvl: t += f"🎉 Уровень повышен до {lvl}!\n"
        bot.answer_callback_query(call.id, "🏆 Победа!")
        try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown')
        except: bot.send_message(cid, t, parse_mode='Markdown')
    else:
        if shp <= 0: shp = 0
        update_seal(sid, health=shp, mood=max(0,seal[5]-10), satiety=max(0,seal[6]-10))
        t = f"💀 *Поражение...* {seal[2]} не смог одолеть {boss['name']}.\n\n"
        t += f"❤️ {shp}/{seal[4]}\n"
        bot.answer_callback_query(call.id, "💀 Поражение")
        try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown')
        except: bot.send_message(cid, t, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data == "batback")
def battle_back(call):
    cid = call.message.chat.id
    if call.message.chat.type == "private":
        show_main_menu(cid)
    else:
        show_inline_menu(cid)

# ==================== ПОДЗЕМЕЛЬЕ ====================
@bot.message_handler(commands=['dungeon'])
@bot.message_handler(func=lambda m: m.text == "🏰 Подземелье" and m.chat.type == "private")
def menu_dungeon(message):
    uid = message.from_user.id; cid = message.chat.id
    seals = get_player_seals(uid)
    if not seals: bot.send_message(cid, "Нет тюленей!"); return
    t = "🏰 *Подземелье*\n\nВыберите тюленя:\n\n"; m = types.InlineKeyboardMarkup()
    married = get_married_ids()
    for s in seals:
        st = get_seal_status(s, married)
        t += f"  {st} {s[2]} (ур.{s[9]}) ❤️{s[3]}/{s[4]}\n"
        m.add(types.InlineKeyboardButton(f"{st} {s[2]}", callback_data=f"ds_{s[0]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="dngback"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("ds_") and not c.data.startswith("dngback"))
def dungeon_select(call):
    uid = call.from_user.id; cid = call.message.chat.id
    sid = int(call.data.split("_")[1]); seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    if seal[3] <= 0: bot.answer_callback_query(call.id, "Тюлень мёртв!"); return
    if seal[6] < 30: bot.answer_callback_query(call.id, "Сытость<30!"); return
    es, ed, eh = get_effective_stats(sid)
    t = (f"🏰 *Подземелье — {seal[2]}*\n\n"
         f"❤️ {seal[3]}/{seal[4]} (эфф {eh})\n"
         f"💪 {es} (база {seal[7]})\n"
         f"🛡️ {ed} (база {seal[8]})\n\n"
         f"Выберите этаж (1–{len(DUNGEON_FLOORS_CONFIG)}):\n")
    m = types.InlineKeyboardMarkup(row_width=3)
    for fl in range(1, len(DUNGEON_FLOORS_CONFIG)+1):
        m.add(types.InlineKeyboardButton(str(fl), callback_data=f"dngfl_{sid}_{fl}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="dngback"))
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except:
        try: bot.delete_message(cid, call.message.message_id)
        except: pass
        bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dngfl_"))
def dungeon_floor(call):
    uid = call.from_user.id; cid = call.message.chat.id
    p = call.data.split("_"); sid = int(p[1]); fl = int(p[2])
    seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    if seal[3] <= 0: bot.answer_callback_query(call.id, "Тюлень мёртв!"); return
    if seal[6] < 30: bot.answer_callback_query(call.id, "Сытость<30!"); return
    mon = get_floor_monster(fl, 0)
    es, ed, eh = get_effective_stats(sid)
    shp = seal[3]; mhp = mon["hp"]
    mood_b = get_mood_bonus(sid)
    str_mod = 1.0 + mood_b / 100.0
    bs = es; bd = ed; mstr = mon["str"]; mdef = mon["def"]
    for rnd in range(1, 21):
        dmg = max(1, int(bs * str_mod) - mdef // 2)
        mhp -= dmg
        if mhp <= 0: break
        mdmg = max(1, mstr - bd // 2)
        shp -= mdmg
        if shp <= 0: break
    if mhp <= 0:
        rw = int((random.randint(30,60) + seal[9]*5) * (1 + fl*0.2))
        eg = int(random.randint(30,50) * get_exp_mult() * (1 + fl*0.1))
        add_fishnets(uid, rw)
        update_seal(sid, health=min(seal[4], max(1,shp)), exp=seal[10]+eg, mood=min(100,seal[5]+15))
        update_quest_progress(uid, "dungeon", 1)
        update_quest_chain(uid, "dungeon_floor", fl)
        add_faction_rep(uid, 1)
        drops = process_drops(uid, DUNGEON_FLOORS_CONFIG[min(fl-1, len(DUNGEON_FLOORS_CONFIG)-1)].get("drops", {}))
        t = f"🏆 *Победа!* {seal[2]} прошёл {fl} этаж!\n\n"
        t += f"🐟 +{rw}\n📈 +{eg} опыта\n❤️ Осталось {max(1,shp)}/{seal[4]}\n"
        if drops: t += f"🎁 Добыча: {', '.join(drops)}\n"
        lvl = check_levelup(sid)
        if lvl: t += f"🎉 Уровень повышен до {lvl}!\n"
        bot.answer_callback_query(call.id, "🏆 Победа!")
        try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown')
        except: bot.send_message(cid, t, parse_mode='Markdown')
    else:
        if shp <= 0: shp = 0
        update_seal(sid, health=shp, mood=max(0,seal[5]-10), satiety=max(0,seal[6]-10))
        t = f"💀 *Поражение...* {seal[2]} не прошёл {fl} этаж.\n\n"
        t += f"❤️ {shp}/{seal[4]}\n"
        bot.answer_callback_query(call.id, "💀 Поражение")
        try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown')
        except: bot.send_message(cid, t, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data == "dngback")
def dungeon_back(call):
    cid = call.message.chat.id
    if call.message.chat.type == "private":
        show_main_menu(cid)
    else:
        show_inline_menu(cid)

# ==================== РЫБАЛКА ====================
@bot.message_handler(commands=['fish'])
@bot.message_handler(func=lambda m: m.text == "🎣 Рыбалка" and m.chat.type == "private")
def cmd_fish(message):
    uid = message.from_user.id; cid = message.chat.id
    p = get_player(uid)
    if not p: bot.send_message(cid, "Напишите /start"); return
    cd = p[7] if len(p) > 7 else None
    if cd:
        try:
            if datetime.now() - datetime.fromisoformat(cd) < timedelta(minutes=FISH_COOLDOWN_MIN):
                bot.send_message(cid, "Ещё не готово! Подождите.")
                return
        except: pass
    bonus = get_fish_bonus()
    catch = random.randint(5, 15) * int(bonus)
    add_fishnets(uid, catch)
    update_player(uid, fish_cooldown=datetime.now().isoformat())
    update_quest_progress(uid, "fish", 1)
    t = f"🎣 Улов: 🐟{catch}!"
    if bonus > 1: t += f" (бонус x{bonus:.1f})"
    bot.send_message(cid, t, parse_mode='Markdown')
    enc = trigger_encounter(uid)
    if enc:
        try: bot.send_message(cid, enc, parse_mode='Markdown')
        except: pass

# ==================== ЕЖЕДНЕВНЫЕ ЗАДАНИЯ ====================
@bot.message_handler(commands=['quests'])
@bot.message_handler(func=lambda m: m.text == "📋 Задания" and m.chat.type == "private")
def menu_quests(message):
    uid = message.from_user.id; cid = message.chat.id
    generate_daily_quests(uid)
    quests = get_daily_quests(uid)
    if not quests: bot.send_message(cid, "Заданий нет!"); return
    t = "📋 *Ежедневные задания*\n\n"; m = types.InlineKeyboardMarkup()
    for q in quests:
        qid, qtype, qtarget, qprog, qreward, qdate, claimed = q[0], q[2], q[3], q[4], q[5], q[6], q[7]
        if claimed: t += f"  ✅ {qtype}: {qtarget} — 🐟{qreward}\n"
        elif qprog >= qtarget:
            t += f"  🎁 {qtype}: {qtarget} — 🐟{qreward}\n"
            m.add(types.InlineKeyboardButton(f"🎁 Забрать 🐟{qreward}", callback_data=f"qclaim_{qid}"))
        else:
            t += f"  ⬜ {qtype}: {qprog}/{qtarget} — 🐟{qreward}\n"
    m.add(types.InlineKeyboardButton("◀️", callback_data="qback"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("qclaim_"))
def quest_claim(call):
    uid = call.from_user.id; cid = call.message.chat.id
    qid = int(call.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT quest_reward, claimed FROM daily_quests WHERE quest_id=?", (qid,))
    r = c.fetchone()
    if not r: bot.answer_callback_query(call.id, "Не найдено!"); return
    if r[1]: bot.answer_callback_query(call.id, "Уже получено!"); return
    reward = r[0]; add_fishnets(uid, reward)
    c.execute("UPDATE daily_quests SET claimed=1 WHERE quest_id=?", (qid,))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, f"Получено 🐟{reward}!")
    try: bot.edit_message_text(f"✅ Награда 🐟{reward} получена!", cid, call.message.message_id)
    except: pass

@bot.callback_query_handler(func=lambda c: c.data == "qback")
def quest_back(call):
    cid = call.message.chat.id
    if call.message.chat.type == "private":
        show_main_menu(cid)
    else:
        show_inline_menu(cid)
# ==================== ГОЛОСОВАНИЕ ====================
@bot.message_handler(commands=['vote'])
def cmd_vote(message):
    uid = message.from_user.id; cid = message.chat.id
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT vote FROM votes WHERE user_id=? AND date=?", (uid, today))
    if c.fetchone(): conn.close(); bot.send_message(cid, "Вы уже голосовали сегодня!"); return
    ev = get_todays_event()
    t = f"🗳 *Голосование за событие дня*\n\n{ev['desc']}\n\nЗапустить?"
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("✅ Да", callback_data="voteyes"),
          types.InlineKeyboardButton("❌ Нет", callback_data="voteno"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)
    conn.close()

@bot.callback_query_handler(func=lambda c: c.data == "voteyes")
def vote_yes(call):
    uid = call.from_user.id; cid = call.message.chat.id
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT vote FROM votes WHERE user_id=? AND date=?", (uid, today))
    if c.fetchone(): bot.answer_callback_query(call.id, "Уже голосовали!"); conn.close(); return
    c.execute("INSERT INTO votes (user_id, vote, date) VALUES (?, 'yes', ?)", (uid, today))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "✅ Голос за!")
    if check_vote_result():
        ev = get_todays_event()
        activate_event(ev["event_type"], ev["effect"])
        bot.send_message(cid, f"🎉 Событие активировано: {ev['desc']}")

@bot.callback_query_handler(func=lambda c: c.data == "voteno")
def vote_no(call):
    uid = call.from_user.id; cid = call.message.chat.id
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT vote FROM votes WHERE user_id=? AND date=?", (uid, today))
    if c.fetchone(): bot.answer_callback_query(call.id, "Уже голосовали!"); conn.close(); return
    c.execute("INSERT INTO votes (user_id, vote, date) VALUES (?, 'no', ?)", (uid, today))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "❌ Голос против!")

# ==================== ФРАКЦИИ ====================
@bot.message_handler(commands=['faction'])
@bot.message_handler(func=lambda m: m.text == "🏛 Фракции" and m.chat.type == "private")
def menu_faction(message):
    uid = message.from_user.id; cid = message.chat.id
    p = get_player(uid)
    if not p: bot.send_message(cid, "Напишите /start"); return
    cur_faction = p[5] if len(p) > 5 else None
    if cur_faction:
        fn = FACTIONS.get(cur_faction, {})
        rep = _safe_int(p[6]) if len(p) > 6 else 0
        disc = get_faction_disc(uid)
        t = f"🏛 *Фракция: {fn.get('name', '?')}*\n\n"
        t += f"🏅 Репутация: {rep}\n"
        t += f"💼 Скидка в магазине: {int(disc*100)}%\n"
        t += f"🎁 Бонус к работе: {int(disc*100)}%\n"
        m = types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("📋 Задания фракции", callback_data="facq"))
        m.add(types.InlineKeyboardButton("◀️", callback_data="facback"))
        bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)
    else:
        t = "🏛 *Выберите фракцию*\n\n"; m = types.InlineKeyboardMarkup()
        for fid, fdata in FACTIONS.items():
            t += f"  {fdata['name']} — {fdata['desc']}\n"
            m.add(types.InlineKeyboardButton(fdata['name'], callback_data=f"facjoin_{fid}"))
        m.add(types.InlineKeyboardButton("◀️", callback_data="facback"))
        bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("facjoin_"))
def faction_join(call):
    uid = call.from_user.id; cid = call.message.chat.id
    fid = call.data[9:]
    if fid not in FACTIONS: bot.answer_callback_query(call.id, "Не найдена!"); return
    update_player(uid, faction=fid, faction_rep=0)
    bot.answer_callback_query(call.id, f"Вступили в {FACTIONS[fid]['name']}!")
    try: bot.edit_message_text(f"✅ Вступили во фракцию: {FACTIONS[fid]['name']}", cid, call.message.message_id)
    except: pass

@bot.callback_query_handler(func=lambda c: c.data == "facq")
def faction_quests(call):
    uid = call.from_user.id; cid = call.message.chat.id
    p = get_player(uid)
    if not p or not p[5]: bot.answer_callback_query(call.id, "Нет фракции!"); return
    rep = _safe_int(p[6])
    t = "📋 *Задания фракции*\n\n"
    t += "Выполняйте работу, бой и подземелья для повышения репутации.\n"
    t += f"Текущая репутация: {rep}\n"
    t += f"Репутация 20 → скидка 5%\nРепутация 50 → скидка 15%\nРепутация 100 → скидка 30%\n"
    bot.answer_callback_query(call.id, "Репутация растёт от работы и боёв!")
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown')
    except: bot.send_message(cid, t, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data == "facback")
def faction_back(call):
    cid = call.message.chat.id
    if call.message.chat.type == "private":
        show_main_menu(cid)
    else:
        show_inline_menu(cid)

# ==================== БРАК ====================
@bot.message_handler(commands=['marry'])
@bot.message_handler(func=lambda m: m.text == "💍 Брак" and m.chat.type == "private")
def menu_marry(message):
    uid = message.from_user.id; cid = message.chat.id
    seals = get_player_seals(uid)
    if not seals: bot.send_message(cid, "Нет тюленей!"); return
    married = get_married_ids()
    t = "💍 *Брак тюленей*\n\nВыберите тюленя для брака:\n\n"
    m = types.InlineKeyboardMarkup()
    for s in seals:
        if s[0] in married:
            t += f"  ❤️ {s[2]} (уже в браке)\n"
        else:
            t += f"  {s[2]} (ур.{s[9]})\n"
            m.add(types.InlineKeyboardButton(f"{s[2]}", callback_data=f"marry_{s[0]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="marryback"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("marry_") and not c.data.startswith("marryback"))
def marry_select(call):
    uid = call.from_user.id; cid = call.message.chat.id
    sid = int(call.data.split("_")[1])
    seals = get_player_seals(uid)
    t = "💍 *Выберите партнёра*\n\n"; m = types.InlineKeyboardMarkup()
    married = get_married_ids()
    for s in seals:
        if s[0] == sid: continue
        if s[0] in married: continue
        m.add(types.InlineKeyboardButton(f"{s[2]}", callback_data=f"marrydo_{sid}_{s[0]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="marryback"))
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except: bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("marrydo_"))
def marry_do(call):
    uid = call.from_user.id; cid = call.message.chat.id
    p = call.data.split("_"); sid1 = int(p[1]); sid2 = int(p[2])
    married = get_married_ids()
    if sid1 in married or sid2 in married:
        bot.answer_callback_query(call.id, "Один из тюленей уже в браке!"); return
    cost = 500
    if get_fishnets(uid) < cost:
        bot.answer_callback_query(call.id, f"Нужно 🐟{cost}!"); return
    add_fishnets(uid, -cost)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO marriages (seal1_id, seal2_id, created_at) VALUES (?, ?, ?)",
              (sid1, sid2, datetime.now().isoformat()))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "💍 Брак заключён!")
    try: bot.edit_message_text(f"💍 *Брак заключён!* Дети появятся через {BABY_GROW_DAYS} дней.", cid, call.message.message_id, parse_mode='Markdown')
    except: bot.send_message(cid, "💍 *Брак заключён!*", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data == "marryback")
def marry_back(call):
    cid = call.message.chat.id
    if call.message.chat.type == "private":
        show_main_menu(cid)
    else:
        show_inline_menu(cid)

# ==================== ДУЭЛИ ====================
@bot.message_handler(commands=['duel'])
@bot.message_handler(func=lambda m: m.text == "🤺 Дуэль" and m.chat.type == "private")
def cmd_duel(message):
    uid = message.from_user.id; cid = message.chat.id
    seals = get_player_seals(uid)
    if not seals: bot.send_message(cid, "Нет тюленей!"); return
    t = "🤺 *Дуэль*\n\nВыберите тюленя:\n\n"; m = types.InlineKeyboardMarkup()
    for s in seals:
        if s[3] <= 0: continue
        m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"duelsel_{s[0]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="duelback"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("duelsel_") and not c.data.startswith("duelback"))
def duel_seal_select(call):
    uid = call.from_user.id; cid = call.message.chat.id
    sid = int(call.data.split("_")[1])
    seal = get_seal(sid)
    if not seal: bot.answer_callback_query(call.id, "Не найден!"); return
    if seal[1] != uid: bot.answer_callback_query(call.id, "Это не ваш тюлень!"); return
    t = "🤺 *Выберите соперника*\n\nВведите ID игрока-соперника:"
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("◀️", callback_data="duelback"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)
    bot.register_next_step_handler_by_chat_id(cid, lambda msg: proc_duel_target(msg, sid) if msg.from_user.id == uid else None)

def proc_duel_target(message, sid):
    uid = message.from_user.id; cid = message.chat.id
    try: oid = int(message.text.strip())
    except ValueError: bot.send_message(cid, "Нужен числовой ID!"); return
    if oid == uid: bot.send_message(cid, "Нельзя дуэль с собой!"); return
    op = get_player(oid)
    if not op: bot.send_message(cid, "Игрок не найден!"); return
    op_seals = get_player_seals(oid)
    if not op_seals: bot.send_message(cid, "У соперника нет тюленей!"); return
    did = create_duel(uid, oid, sid)
    t = f"🤺 *Вызов на дуэль!*\n\nВас вызывают на дуэль!\nВыберите своего тюленя:"
    m = types.InlineKeyboardMarkup()
    for s in op_seals:
        if s[3] <= 0: continue
        m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"duelaccept_{did}_{s[0]}"))
    m.add(types.InlineKeyboardButton("Отказать", callback_data=f"duelreject_{did}"))
    try:
        bot.send_message(oid, t, parse_mode='Markdown', reply_markup=m)
        bot.send_message(cid, f"🤺 Вызов отправлен игроку {oid}!")
    except Exception as e:
        bot.send_message(cid, f"Не удалось отправить вызов: {e}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("duelaccept_"))
def duel_accept(call):
    uid = call.from_user.id; cid = call.message.chat.id
    p = call.data.split("_"); did = int(p[1]); osid = int(p[2])
    duel = get_duel(did)
    if not duel: bot.answer_callback_query(call.id, "Дуэль не найдена!"); return
    if duel[1] == uid: bot.answer_callback_query(call.id, "Нельзя принять свой вызов!"); return
    if duel[2] != uid: bot.answer_callback_query(call.id, "Это не ваш вызов!"); return
    if duel[5] != "pending": bot.answer_callback_query(call.id, "Уже обработано!"); return
    csid = duel[3]; seal1 = get_seal(csid); seal2 = get_seal(osid)
    if not seal1 or not seal2: bot.answer_callback_query(call.id, "Тюлень не найден!"); return
    if seal1[3] <= 0 or seal2[3] <= 0: bot.answer_callback_query(call.id, "Тюлень мёртв!"); return
    es1, ed1, _ = get_effective_stats(csid); es2, ed2, _ = get_effective_stats(osid)
    shp1 = seal1[3]; shp2 = seal2[3]
    mb1 = get_mood_bonus(csid); mb2 = get_mood_bonus(osid)
    sm1 = 1.0 + mb1 / 100.0; sm2 = 1.0 + mb2 / 100.0
    for rnd in range(1, 21):
        d1 = max(1, int(es1 * sm1) - ed2 // 2); shp2 -= d1
        if shp2 <= 0: break
        d2 = max(1, int(es2 * sm2) - ed1 // 2); shp1 -= d2
        if shp1 <= 0: break
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE duels SET status='completed' WHERE duel_id=?", (did,))
    conn.commit(); conn.close()
    challenger_id = duel[1]; opponent_id = duel[2]
    if shp2 <= 0:
        rw = random.randint(50, 100); add_fishnets(challenger_id, rw)
        update_seal(csid, health=max(1, shp1), mood=min(100, seal1[5]+20))
        update_seal(osid, health=max(0, shp2), mood=max(0, seal2[5]-10))
        t = f"🤺 *{seal1[2]}* победил *{seal2[2]}*!\n🐟 +{rw} победителю!"
        bot.answer_callback_query(call.id, "🏆 Вы победили!")
        try: bot.send_message(challenger_id, t, parse_mode='Markdown')
        except: pass
    elif shp1 <= 0:
        rw = random.randint(50, 100); add_fishnets(opponent_id, rw)
        update_seal(osid, health=max(1, shp2), mood=min(100, seal2[5]+20))
        update_seal(csid, health=max(0, shp1), mood=max(0, seal1[5]-10))
        t = f"🤺 *{seal2[2]}* победил *{seal1[2]}*!\n🐟 +{rw} победителю!"
        bot.answer_callback_query(call.id, "🏆 Вы победили!")
        try: bot.send_message(challenger_id, t, parse_mode='Markdown')
        except: pass
    else:
        t = "🤺 Ничья!"
        bot.answer_callback_query(call.id, "Ничья!")
        try: bot.send_message(challenger_id, t, parse_mode='Markdown')
        except: pass
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown')
    except: bot.send_message(cid, t, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("duelreject_"))
def duel_reject(call):
    uid = call.from_user.id; cid = call.message.chat.id
    did = int(call.data.split("_")[1])
    duel = get_duel(did)
    if not duel: bot.answer_callback_query(call.id, "Не найдена!"); return
    if duel[2] != uid: bot.answer_callback_query(call.id, "Не ваш вызов!"); return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE duels SET status='rejected' WHERE duel_id=?", (did,))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "❌ Отклонено")
    try: bot.edit_message_text("❌ Дуэль отклонена.", cid, call.message.message_id)
    except: pass
    try: bot.send_message(duel[1], "❌ Ваш вызов на дуэль отклонён.")
    except: pass

@bot.callback_query_handler(func=lambda c: c.data == "duelback")
def duel_back(call):
    cid = call.message.chat.id
    if call.message.chat.type == "private":
        show_main_menu(cid)
    else:
        show_inline_menu(cid)

# ==================== БИРЖА ====================
@bot.message_handler(commands=['trade'])
@bot.message_handler(func=lambda m: m.text == "📦 Биржа" and m.chat.type == "private")
def menu_trade(message):
    cid = message.chat.id
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("📤 Выставить лот", callback_data="trsell"),
          types.InlineKeyboardButton("🛒 Купить лот", callback_data="trbuy"))
    m.add(types.InlineKeyboardButton("📦 Мои лоты", callback_data="trmine"))
    bot.send_message(cid, "📦 *Биржа*\n\nВыберите действие:", parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data == "trsell")
def trade_sell_menu(call):
    uid = call.from_user.id; cid = call.message.chat.id
    inv = get_inv(uid)
    if not inv:
        bot.answer_callback_query(call.id, "Инвентарь пуст!"); return
    t = "📤 *Выставить на продажу*\n\nВыберите предмет:\n\n"
    m = types.InlineKeyboardMarkup()
    for i in inv:
        m.add(types.InlineKeyboardButton(f"{i[2]} (x{i[4]})", callback_data=f"trselitem_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="trback"))
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except: bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("trselitem_"))
def trade_sell_price(call):
    uid = call.from_user.id; cid = call.message.chat.id
    item_name = call.data[len("trselitem_"):]
    if get_item_qty(uid, item_name) <= 0:
        bot.answer_callback_query(call.id, "Нет предмета!"); return
    t = f"📤 *Выставить: {item_name}*\n\nВведите цену в 🐟:"
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("◀️", callback_data="trsell"))
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except: bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)
    bot.register_next_step_handler_by_chat_id(cid, lambda msg: proc_trade_price(msg, item_name) if msg.from_user.id == uid else None)

def proc_trade_price(message, item_name):
    uid = message.from_user.id; cid = message.chat.id
    try: price = int(message.text.strip())
    except ValueError: bot.send_message(cid, "Нужна цена числом!"); return
    if price <= 0: bot.send_message(cid, "Цена должна быть > 0!"); return
    if get_item_qty(uid, item_name) <= 0: bot.send_message(cid, "Нет предмета!"); return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO trades (seller_id, item_name, price, created_at) VALUES (?, ?, ?, ?)",
              (uid, item_name, price, datetime.now().isoformat()))
    remove_from_inv(uid, item_name, 1)
    conn.commit(); conn.close()
    bot.send_message(cid, f"✅ {item_name} выставлен за 🐟{price}!", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data == "trbuy")
def trade_buy_list(call):
    uid = call.from_user.id; cid = call.message.chat.id
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT trade_id, seller_id, item_name, price FROM trades WHERE seller_id != ?", (uid,))
    rows = c.fetchall(); conn.close()
    if not rows:
        bot.answer_callback_query(call.id, "Нет лотов!"); return
    t = "🛒 *Лоты на бирже*\n\n"; m = types.InlineKeyboardMarkup()
    for tid, sid, name, price in rows:
        seller = get_player(sid)
        sname = seller[1] if seller else "?"
        t += f"  {name} — 🐟{price} (от @{sname})\n"
        m.add(types.InlineKeyboardButton(f"{name} — 🐟{price}", callback_data=f"trbuydo_{tid}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="trback"))
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except: bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("trbuydo_"))
def trade_buy_do(call):
    uid = call.from_user.id; cid = call.message.chat.id
    tid = int(call.data[len("trbuydo_"):])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT seller_id, item_name, price FROM trades WHERE trade_id=?", (tid,))
    r = c.fetchone()
    if not r: bot.answer_callback_query(call.id, "Лот не найден!"); conn.close(); return
    seller_id, item_name, price = r
    if seller_id == uid: bot.answer_callback_query(call.id, "Свой лот!"); conn.close(); return
    if get_fishnets(uid) < price: bot.answer_callback_query(call.id, "Не хватает 🐟!"); conn.close(); return
    add_fishnets(uid, -price); add_fishnets(seller_id, price)
    it_type = ITEM_TYPES.get(item_name, "misc")
    add_to_inv(uid, item_name, it_type, 1)
    c.execute("DELETE FROM trades WHERE trade_id=?", (tid,))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, f"Куплено: {item_name} за 🐟{price}!")

@bot.callback_query_handler(func=lambda c: c.data == "trmine")
def trade_my_lots(call):
    uid = call.from_user.id; cid = call.message.chat.id
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT trade_id, item_name, price FROM trades WHERE seller_id=?", (uid,))
    rows = c.fetchall(); conn.close()
    if not rows:
        bot.answer_callback_query(call.id, "Нет лотов!"); return
    t = "📦 *Мои лоты*\n\n"; m = types.InlineKeyboardMarkup()
    for tid, name, price in rows:
        t += f"  {name} — 🐟{price}\n"
        m.add(types.InlineKeyboardButton(f"Снять {name} — 🐟{price}", callback_data=f"trcancel_{tid}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="trback"))
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except: bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("trcancel_"))
def trade_cancel(call):
    uid = call.from_user.id; cid = call.message.chat.id
    tid = int(call.data[len("trcancel_"):])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT seller_id, item_name FROM trades WHERE trade_id=?", (tid,))
    r = c.fetchone()
    if not r: bot.answer_callback_query(call.id, "Лот не найден!"); conn.close(); return
    seller_id, item_name = r
    if seller_id != uid: bot.answer_callback_query(call.id, "Не ваш лот!"); conn.close(); return
    it_type = ITEM_TYPES.get(item_name, "misc")
    add_to_inv(uid, item_name, it_type, 1)
    c.execute("DELETE FROM trades WHERE trade_id=?", (tid,))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, f"Снят: {item_name}")

@bot.callback_query_handler(func=lambda c: c.data == "trback")
def trade_back(call):
    cid = call.message.chat.id
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("📤 Выставить лот", callback_data="trsell"),
          types.InlineKeyboardButton("🛒 Купить лот", callback_data="trbuy"))
    m.add(types.InlineKeyboardButton("📦 Мои лоты", callback_data="trmine"))
    try: bot.edit_message_text("📦 *Биржа*", cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except:
        if call.message.chat.type == "private": show_main_menu(cid)
        else: show_inline_menu(cid)

# ==================== ЦЕПОЧКИ КВЕСТОВ ====================
@bot.message_handler(commands=['questchain'])
@bot.message_handler(func=lambda m: m.text == "📚 Цепочки" and m.chat.type == "private")
def cmd_questchain(message):
    uid = message.from_user.id; cid = message.chat.id
    chains = get_quest_chains()
    if not chains: bot.send_message(cid, "Нет квестовых цепочек!"); return
    t = "📚 *Квестовые цепочки*\n\n"; m = types.InlineKeyboardMarkup()
    for ch in chains:
        cid_chain = ch[0]; name = ch[1]
        pc = get_player_chain(uid, cid_chain)
        if not pc:
            m.add(types.InlineKeyboardButton(f"📜 {name} (не начато)", callback_data=f"qcstart_{cid_chain}"))
            t += f"  📜 {name} — не начато\n"
        elif pc[4] == 1:
            t += f"  ✅ {name} — завершено\n"
        else:
            try:
                steps = json.loads(ch[3]); cs = pc[2]; sp = pc[3]
                if cs < len(steps):
                    t += f"  🔄 {name} — шаг {cs+1}/{len(steps)} ({sp}/{steps[cs]['target']})\n"
                else:
                    t += f"  ✅ {name} — завершено\n"
            except: t += f"  🔄 {name} — в процессе\n"
    m.add(types.InlineKeyboardButton("◀️", callback_data="qcback"))
    bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("qcstart_"))
def questchain_start(call):
    uid = call.from_user.id; cid = call.message.chat.id
    chain_id = int(call.data[len("qcstart_"):])
    chains = get_quest_chains()
    found = None
    for ch in chains:
        if ch[0] == chain_id: found = ch; break
    if not found: bot.answer_callback_query(call.id, "Не найдена!"); return
    pc = get_player_chain(uid, chain_id)
    if pc: bot.answer_callback_query(call.id, "Уже начато!"); return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO player_quest_chains (user_id, chain_id, current_step, step_progress, completed) VALUES (?, ?, 0, 0, 0)", (uid, chain_id))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, f"Начато: {found[1]}!")

@bot.callback_query_handler(func=lambda c: c.data == "qcback")
def questchain_back(call):
    cid = call.message.chat.id
    if call.message.chat.type == "private":
        show_main_menu(cid)
    else:
        show_inline_menu(cid)

# ==================== КЛАНЫ ====================
@bot.message_handler(commands=['clan'])
@bot.message_handler(func=lambda m: m.text == "🐋 Клан" and m.chat.type == "private")
def menu_clan(message):
    uid = message.from_user.id; cid = message.chat.id
    clan = get_clan_by_user(uid)
    if clan:
        members = get_clan_members(clan[0])
        t = f"🐋 *Клан: {clan[1]}*\n\n"
        t += f"🆔 ID: {clan[0]}\n"
        t += f"👥 Участников: {len(members)}\n"
        t += f"👑 Лидер: @{clan[4] or '?'}\n"
        t += f"💰 Казна: 🐟{clan[6] or 0}\n"
        m = types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("👥 Участники", callback_data=f"clanmembers_{clan[0]}"))
        m.add(types.InlineKeyboardButton("💰 Внести в казну", callback_data=f"clandonate_{clan[0]}"))
        m.add(types.InlineKeyboardButton("◀️", callback_data="clanback"))
        bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)
    else:
        m = types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("🐋 Создать клан", callback_data="clancreate"))
        m.add(types.InlineKeyboardButton("📜 Список кланов", callback_data="clanlist"))
        m.add(types.InlineKeyboardButton("◀️", callback_data="clanback"))
        bot.send_message(cid, "🐋 *Кланы*\n\nВы не состоите в клане.", parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data == "clancreate")
def clan_create_prompt(call):
    uid = call.from_user.id; cid = call.message.chat.id
    cost = 1000
    if get_fishnets(uid) < cost:
        bot.answer_callback_query(call.id, f"Нужно 🐟{cost}!"); return
    bot.send_message(cid, f"Введите название клана (стоимость 🐟{cost}):")
    bot.register_next_step_handler_by_chat_id(cid, lambda msg: proc_clan_create(msg) if msg.from_user.id == uid else None)

def proc_clan_create(message):
    uid = message.from_user.id; cid = message.chat.id
    name = message.text.strip()
    if len(name) > 30: bot.send_message(cid, "Слишком длинное!"); return
    cost = 1000
    if get_fishnets(uid) < cost: bot.send_message(cid, "Не хватает 🐟!"); return
    uname = message.from_user.username or message.from_user.first_name
    add_fishnets(uid, -cost)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO clans (name, emblem, leader_id, leader_name, created_at, treasury) VALUES (?, ?, ?, ?, ?, 0)",
              (name, "🦭", uid, uname, datetime.now().isoformat()))
    clan_id = c.lastrowid
    c.execute("INSERT INTO clan_members (clan_id, user_id, role, joined_at) VALUES (?, ?, 'leader', ?)",
              (clan_id, uid, datetime.now().isoformat()))
    conn.commit(); conn.close()
    bot.send_message(cid, f"🐋 Клан *{name}* создан!", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data == "clanlist")
def clan_list(call):
    uid = call.from_user.id; cid = call.message.chat.id
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT clan_id, name, leader_name FROM clans LIMIT 20")
    rows = c.fetchall(); conn.close()
    if not rows:
        bot.answer_callback_query(call.id, "Нет кланов!"); return
    t = "📜 *Список кланов*\n\n"; m = types.InlineKeyboardMarkup()
    for cid_clan, name, leader in rows:
        members = get_clan_members(cid_clan)
        t += f"  🐋 {name} (👥{len(members)}) — @{leader or '?'}\n"
        m.add(types.InlineKeyboardButton(f"{name}", callback_data=f"clanjoin_{cid_clan}"))
    m.add(types.InlineKeyboardButton("◀️", callback_data="clanback"))
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown', reply_markup=m)
    except: bot.send_message(cid, t, parse_mode='Markdown', reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("clanjoin_"))
def clan_join(call):
    uid = call.from_user.id; cid = call.message.chat.id
    clan_id = int(call.data[len("clanjoin_"):])
    existing = get_clan_by_user(uid)
    if existing: bot.answer_callback_query(call.id, "Уже в клане!"); return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM clan_members WHERE clan_id=?", (clan_id,))
    count = c.fetchone()[0]
    if count >= MAX_CLAN_MEMBERS: bot.answer_callback_query(call.id, "Клан заполнен!"); conn.close(); return
    c.execute("INSERT INTO clan_members (clan_id, user_id, role, joined_at) VALUES (?, ?, 'member', ?)",
              (clan_id, uid, datetime.now().isoformat()))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "✅ Вступили!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("clanmembers_"))
def clan_members_list(call):
    uid = call.from_user.id; cid = call.message.chat.id
    clan_id = int(call.data[len("clanmembers_"):])
    members = get_clan_members(clan_id)
    t = "👥 *Участники клана*\n\n"
    for mid in members:
        p = get_player(mid)
        t += f"  @{p[1] if p else '?'}\n"
    bot.answer_callback_query(call.id, "Список показан")
    try: bot.edit_message_text(t, cid, call.message.message_id, parse_mode='Markdown')
    except: bot.send_message(cid, t, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("clandonate_"))
def clan_donate_prompt(call):
    uid = call.from_user.id; cid = call.message.chat.id
    clan = get_clan_by_user(uid)
    if not clan: bot.answer_callback_query(call.id, "Вы не в клане!"); return
    bot.send_message(cid, "Введите сумму доната в 🐟:")
    bot.register_next_step_handler_by_chat_id(cid, lambda msg: proc_clan_donate(msg) if msg.from_user.id == uid else None)

def proc_clan_donate(message):
    uid = message.from_user.id; cid = message.chat.id
    try: amount = int(message.text.strip())
    except ValueError: bot.send_message(cid, "Нужна сумма числом!"); return
    if amount <= 0: bot.send_message(cid, "Сумма > 0!"); return
    if get_fishnets(uid) < amount: bot.send_message(cid, "Не хватает 🐟!"); return
    clan = get_clan_by_user(uid)
    if not clan: bot.send_message(cid, "Вы не в клане!"); return
    add_fishnets(uid, -amount)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE clans SET treasury = COALESCE(treasury, 0) + ? WHERE clan_id=?", (amount, clan[0]))
    conn.commit(); conn.close()
    bot.send_message(cid, f"✅ Внесено 🐟{amount} в казну клана!", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data == "clanback")
def clan_back(call):
    cid = call.message.chat.id
    if call.message.chat.type == "private":
        show_main_menu(cid)
    else:
        show_inline_menu(cid)

# ==================== ФОНОВЫЕ ПРОЦЕССЫ ====================
def stats_decay():
    while True:
        time.sleep(300)
        try:
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("SELECT seal_id, mood, satiety, health FROM seals WHERE is_baby=0")
            for sid, mood, satiety, health in c.fetchall():
                nm = max(0, mood - 1); ns = max(0, satiety - 1)
                nh = health
                if ns < 10 and nh > 0: nh = max(0, nh - 5)
                c2 = conn.cursor()
                c2.execute("UPDATE seals SET mood=?, satiety=?, health=? WHERE seal_id=?", (nm, ns, nh, sid))
            conn.commit(); conn.close()
        except Exception as e:
            print(f"stats_decay error: {e}")

def daily_reset():
    while True:
        time.sleep(3600)
        try:
            now = datetime.now()
            if now.hour == 0 and now.minute < 5:
                conn = sqlite3.connect(DB_PATH); c = conn.cursor()
                c.execute("DELETE FROM votes WHERE date != ?", (date.today().isoformat(),))
                c.execute("UPDATE active_events SET active=0 WHERE expires_at < ?", (now.isoformat(),))
                conn.commit(); conn.close()
        except Exception as e:
            print(f"daily_reset error: {e}")

def work_cooldown_check():
    while True:
        time.sleep(60)
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.close()
        except Exception as e:
            print(f"work_cooldown error: {e}")

# ==================== ОБРАБОТЧИК ВСЕХ ОСТАЛЬНЫХ ТЕКСТОВЫХ КНОПОК ====================
@bot.message_handler(func=lambda m: m.text in (
    "🦭 Мой тюлень", "👤 Профиль", "🎒 Инвентарь", "🛒 Магазин",
    "⚔️ Бой", "🏰 Подземелье", "💼 Работа", "🔨 Крафт",
    "🧪 Зелья", "✨ Зачарование", "📋 Задания", "💍 Брак",
    "🎣 Рыбалка", "🏆 Лидеры", "📦 Биржа", "🏛 Фракции",
    "🤺 Дуэль", "📚 Цепочки", "🐋 Клан", "💰 Продажа"
) and m.chat.type == "private")
def text_buttons_catch(message):
    pass

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    run_migrations()
    t1 = threading.Thread(target=stats_decay, daemon=True)
    t2 = threading.Thread(target=daily_reset, daemon=True)
    t3 = threading.Thread(target=work_cooldown_check, daemon=True)
    t1.start(); t2.start(); t3.start()
    print("🦭 Бот запущен!")
    bot.polling(none_stop=True)

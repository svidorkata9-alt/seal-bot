import telebot
from telebot import types
import sqlite3
import random
import threading
import time
import os
import shutil
import json
from datetime import datetime, date, timedelta

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

DB_PATH = "seal_life.db"
BACKUP_DIR = "backups"
MAX_SEALS = 5
FISHING_COOLDOWN_MIN = 10

# ==================== СИСТЕМА МИГРАЦИИ ====================

def backup_db():
    if not os.path.exists(DB_PATH):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"seal_life_{timestamp}.db")
    shutil.copy2(DB_PATH, backup_path)
    backups = sorted(
        [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.endswith(".db")],
        key=os.path.getmtime)
    for old in backups[:-10]:
        os.remove(old)
    return backup_path

def get_db_version(conn):
    c = conn.cursor()
    try:
        c.execute("SELECT value FROM _meta WHERE key = 'schema_version'")
        row = c.fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return 0

def set_db_version(conn, version):
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("INSERT OR REPLACE INTO _meta (key, value) VALUES ('schema_version', ?)", (str(version),))
    conn.commit()

def _add_column_if_missing(c, table, column, coldef):
    c.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in c.fetchall()]
    if column not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")

def migration_1(c):
    c.execute('''CREATE TABLE IF NOT EXISTS players (
        user_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT,
        photo_path TEXT, fishnets INTEGER DEFAULT 100,
        faction TEXT, faction_rep INTEGER DEFAULT 0, fish_cooldown TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS seals (
        seal_id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, name TEXT,
        health INTEGER DEFAULT 100, max_health INTEGER DEFAULT 100,
        mood INTEGER DEFAULT 80, satiety INTEGER DEFAULT 80,
        strength INTEGER DEFAULT 10, defense INTEGER DEFAULT 5,
        level INTEGER DEFAULT 1, exp INTEGER DEFAULT 0,
        is_baby INTEGER DEFAULT 0, born_at TEXT,
        equipped_weapon TEXT, equipped_armor TEXT, equipped_helmet TEXT,
        equipped_shield TEXT, equipped_accessory TEXT,
        work_cooldown TEXT, play_cooldown TEXT, photo_path TEXT,
        work_cooldown_min INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS marriages (
        marriage_id INTEGER PRIMARY KEY AUTOINCREMENT,
        seal1_id INTEGER, seal2_id INTEGER,
        player1_id INTEGER, player2_id INTEGER, created_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS inventory (
        inv_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, item_name TEXT, item_type TEXT, quantity INTEGER DEFAULT 1
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_quests (
        quest_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, quest_type TEXT,
        quest_target INTEGER, quest_progress INTEGER DEFAULT 0,
        quest_reward INTEGER, date TEXT, claimed INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS dungeon_runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, seal_id INTEGER,
        current_floor INTEGER DEFAULT 1, active INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS trade_offers (
        offer_id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER,
        item_name TEXT, item_type TEXT, price INTEGER,
        created_at TEXT, active INTEGER DEFAULT 1
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS votes (
        vote_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        event_type TEXT, vote TEXT, date TEXT, UNIQUE(user_id, date)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS active_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT,
        effect TEXT, expires_at TEXT, active INTEGER DEFAULT 1
    )''')

MIGRATIONS = [migration_1]

def run_migrations():
    backup_path = backup_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    current_version = get_db_version(conn)
    total = len(MIGRATIONS)
    if current_version >= total:
        conn.close()
        return f"БД актуальна (версия {current_version})"
    applied = []
    for i in range(current_version, total):
        try:
            MIGRATIONS[i](c)
            applied.append(i + 1)
        except Exception as e:
            conn.close()
            raise RuntimeError(f"Ошибка в миграции {i+1}: {e}")
    set_db_version(conn, total)
    conn.commit()
    conn.close()
    msg = f"Миграции применены: {applied}"
    if backup_path:
        msg += f" | Бэкап: {backup_path}"
    return msg

print(run_migrations())

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
# Индексы seals: 0=seal_id, 1=owner_id, 2=name, 3=health, 4=max_health,
# 5=mood, 6=satiety, 7=strength, 8=defense, 9=level, 10=exp,
# 11=is_baby, 12=born_at, 13=equipped_weapon, 14=equipped_armor,
# 15=equipped_helmet, 16=equipped_shield, 17=equipped_accessory,
# 18=work_cooldown, 19=play_cooldown, 20=photo_path, 21=work_cooldown_min
# Индексы players: 0=user_id, 1=username, 2=display_name, 3=photo_path,
# 4=fishnets, 5=faction, 6=faction_rep, 7=fish_cooldown

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

def get_seal_count(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM seals WHERE owner_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def update_seal(seal_id, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    sets = ", ".join([f"{k} = ?" for k in kwargs])
    vals = list(kwargs.values()) + [seal_id]
    c.execute(f"UPDATE seals SET {sets} WHERE seal_id = ?", vals)
    conn.commit()
    conn.close()

def update_player(user_id, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    sets = ", ".join([f"{k} = ?" for k in kwargs])
    vals = list(kwargs.values()) + [user_id]
    c.execute(f"UPDATE players SET {sets} WHERE user_id = ?", vals)
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

def get_item_quantity(user_id, item_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, item_name))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

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

def get_exp_multiplier():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT effect FROM active_events WHERE active = 1 AND event_type = 'exp_boost' AND expires_at > ?", (datetime.now().isoformat(),))
    row = c.fetchone()
    conn.close()
    return float(row[0]) if row else 1.0

def get_shop_discount():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT effect FROM active_events WHERE active = 1 AND event_type = 'shop_discount' AND expires_at > ?", (datetime.now().isoformat(),))
    row = c.fetchone()
    conn.close()
    return float(row[0]) if row else 0.0

def get_fishing_bonus():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT effect FROM active_events WHERE active = 1 AND event_type = 'fishing_bonus' AND expires_at > ?", (datetime.now().isoformat(),))
    row = c.fetchone()
    conn.close()
    return float(row[0]) if row else 1.0

def check_levelup(seal_id):
    results = []
    while True:
        seal = get_seal(seal_id)
        if not seal:
            break
        level, exp = seal[9], seal[10]
        needed = exp_for_level(level)
        if exp >= needed:
            new_level = level + 1
            new_exp = exp - needed
            str_bonus = random.randint(2, 5)
            def_bonus = random.randint(1, 3)
            hp_bonus = random.randint(10, 20)
            update_seal(seal_id, level=new_level, exp=new_exp,
                        strength=seal[7]+str_bonus, defense=seal[8]+def_bonus,
                        max_health=seal[4]+hp_bonus, health=seal[4]+hp_bonus)
            results.append(new_level)
        else:
            break
    return results[-1] if results else False

# ==================== ПРЕДМЕТЫ И БОНУСЫ ====================

ITEM_BONUSES = {
    "Костяной меч 🗡️": {"str": 5}, "Акулий клык 🦷": {"str": 8},
    "Трезубец 🔱": {"str": 12}, "Китовый клинок 🐋": {"str": 15},
    "Чешуйчатая броня 🐟": {"def": 5, "hp": 10}, "Панцирь краба 🦀": {"def": 8, "hp": 15},
    "Плетёная броня 🧵": {"def": 10, "hp": 25}, "Кракеновый панцирь 🐙": {"def": 15, "hp": 40},
    "Шлем из ракушек 🐚": {"def": 3, "hp": 10}, "Костяной шлем 💀": {"def": 5, "hp": 15},
    "Корона из зубов 👑": {"def": 8, "hp": 20},
    "Щит из чешуи 🐠": {"def": 5}, "Панцирный щит 🛡️": {"def": 8}, "Щит кракена 🦑": {"def": 12},
}

ACCESSORY_BONUSES = {"Бантик 🎀": 10, "Шарф 🧣": 8, "Корона 👑": 20, "Очки 🕶️": 7, "Цветок 🌸": 5}

def get_effective_stats(seal_id):
    seal = get_seal(seal_id)
    if not seal:
        return 0, 0, 0
    base_str, base_def, base_hp = seal[7], seal[8], seal[4]
    str_b = def_b = hp_b = 0
    for slot in [seal[13], seal[14], seal[15], seal[16]]:
        if slot and slot in ITEM_BONUSES:
            b = ITEM_BONUSES[slot]
            str_b += b.get("str", 0); def_b += b.get("def", 0); hp_b += b.get("hp", 0)
    return base_str + str_b, base_def + def_b, base_hp + hp_b

def get_mood_bonus(seal_id):
    seal = get_seal(seal_id)
    if not seal:
        return 0
    return ACCESSORY_BONUSES.get(seal[17], 0)

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
}

# ==================== КРАФТ ====================

CRAFT_RECIPES = [
    {"name": "Костяной меч 🗡️", "type": "weapon", "resources": {"Акулий зуб 🦈": 3}},
    {"name": "Акулий клык 🦷", "type": "weapon", "resources": {"Акулий зуб 🦈": 5, "Чешуя 🐟": 2}},
    {"name": "Трезубец 🔱", "type": "weapon", "resources": {"Щупальце 🐙": 4, "Акулий зуб 🦈": 3}},
    {"name": "Китовый клинок 🐋", "type": "weapon", "resources": {"Китовый ус 🐋": 3, "Жемчуг 🫧": 1}},
    {"name": "Чешуйчатая броня 🐟", "type": "armor", "resources": {"Чешуя 🐟": 4}},
    {"name": "Панцирь краба 🦀", "type": "armor", "resources": {"Панцирь 🦀": 3}},
    {"name": "Плетёная броня 🧵", "type": "armor", "resources": {"Щупальце 🐙": 3, "Чешуя 🐟": 2}},
    {"name": "Кракеновый панцирь 🐙", "type": "armor", "resources": {"Щупальце 🐙": 5, "Жемчуг 🫧": 1}},
    {"name": "Шлем из ракушек 🐚", "type": "helmet", "resources": {"Панцирь 🦀": 3, "Чешуя 🐟": 1}},
    {"name": "Костяной шлем 💀", "type": "helmet", "resources": {"Акулий зуб 🦈": 3}},
    {"name": "Корона из зубов 👑", "type": "helmet", "resources": {"Акулий зуб 🦈": 5, "Жемчуг 🫧": 1}},
    {"name": "Щит из чешуи 🐠", "type": "shield", "resources": {"Чешуя 🐟": 4, "Панцирь 🦀": 1}},
    {"name": "Панцирный щит 🛡️", "type": "shield", "resources": {"Панцирь 🦀": 4}},
    {"name": "Щит кракена 🦑", "type": "shield", "resources": {"Щупальце 🐙": 3, "Панцирь 🦀": 2}},
]

ITEM_TYPES = {}
for _n, _i in SHOP_ITEMS.items():
    ITEM_TYPES[_n] = _i["type"]
for _r in CRAFT_RECIPES:
    ITEM_TYPES[_r["name"]] = _r["type"]
ITEM_TYPES["Меч ⚔️"] = "weapon"; ITEM_TYPES["Щит 🛡️"] = "shield"
ITEM_TYPES["Шлем 🪖"] = "helmet"; ITEM_TYPES["Броня 👕"] = "armor"

def can_craft(user_id, recipe):
    for resource, amount in recipe["resources"].items():
        if get_item_quantity(user_id, resource) < amount:
            return False
    return True

# ==================== ФРАКЦИИ ====================

FACTIONS = {
    "hunters": {"name": "Стая охотников 🎯", "desc": "Бонус к награде за бои"},
    "fashion": {"name": "Клуб модников 💅", "desc": "Бонус к настроению и аксессуарам"},
    "explorers": {"name": "Гильдия исследователей 🧭", "desc": "Бонус к опыту и подземельям"},
}

def get_faction_discount(user_id):
    player = get_player(user_id)
    if not player or not player[5]:
        return 0.0
    rep = player[6]
    if rep >= 100: return 0.30
    elif rep >= 50: return 0.15
    elif rep >= 20: return 0.05
    return 0.0

def add_faction_rep(user_id, amount):
    player = get_player(user_id)
    if not player or not player[5]:
        return
    update_player(user_id, faction_rep=player[6] + amount)

# ==================== МОНСТРЫ ====================

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
    {"name": "Глубинный краб 🦀", "hp": 70, "str": 13, "def": 14, "drops": {"Панцирь 🦀": 0.7, "Жемчуг 🫧": 0.1}},
]

BOSSES = [
    {"name": "Краб-босс 🦀", "drops": {"Панцирь 🦀": 0.8}},
    {"name": "Акула 🦈", "drops": {"Акулий зуб 🦈": 0.8}},
    {"name": "Осьминог 🐙", "drops": {"Щупальце 🐙": 0.8}},
    {"name": "Морской ёжик 🦔", "drops": {"Жало 🐡": 0.8}},
    {"name": "Кашалот 🐋", "drops": {"Китовый ус 🐋": 0.7}},
    {"name": "Морской змей 🐍", "drops": {"Чешуя 🐟": 0.8}},
    {"name": "Гигантский краб 🦀", "drops": {"Панцирь 🦀": 0.8, "Жемчуг 🫧": 0.15}},
    {"name": "Электрический скат ⚡", "drops": {"Чешуя 🐟": 0.7, "Жало 🐡": 0.3}},
    {"name": "Глубинный монстр 🌑", "drops": {"Жемчуг 🫧": 0.4, "Щупальце 🐙": 0.5}},
    {"name": "Король креветок 🦐", "drops": {"Панцирь 🦀": 0.7, "Чешуя 🐟": 0.3}},
]

def get_dungeon_monster(floor):
    idx = (floor - 1) % len(DUNGEON_MONSTERS)
    monster = DUNGEON_MONSTERS[idx].copy()
    monster["hp"] += floor * 15
    monster["str"] += floor * 3
    monster["def"] += floor * 2
    return monster

def process_drops(user_id, drops):
    dropped = []
    for resource, chance in drops.items():
        if random.random() < chance:
            qty = random.randint(1, 2)
            add_to_inventory(user_id, resource, "resource", qty)
            dropped.append(f"{resource} x{qty}")
    return dropped

# ==================== РАБОТЫ ====================

JOBS = [
    {"name": "Рыболов 🎣", "desc": "Ловить рыбу", "reward_min": 20, "reward_max": 50, "cooldown_min": 30, "mood_cost": 5, "satiety_cost": 10},
    {"name": "Почтальон 📬", "desc": "Разносить почту", "reward_min": 30, "reward_max": 60, "cooldown_min": 45, "mood_cost": 8, "satiety_cost": 15},
    {"name": "Укротитель 🦭", "desc": "Укрощать морских зверей", "reward_min": 50, "reward_max": 100, "cooldown_min": 60, "mood_cost": 12, "satiety_cost": 20},
    {"name": "Водолаз 🤿", "desc": "Исследовать глубины", "reward_min": 40, "reward_max": 80, "cooldown_min": 50, "mood_cost": 10, "satiety_cost": 18},
    {"name": "Актёр 🎭", "desc": "Выступать в шоу", "reward_min": 35, "reward_max": 70, "cooldown_min": 40, "mood_cost": 6, "satiety_cost": 12},
]

PLAY_COOLDOWN_MIN = 15

# ==================== ГОЛОСОВАНИЯ ====================

DAILY_EVENTS = [
    {"event_type": "exp_boost", "effect": "1.5", "desc": "Сегодня все получают +50% к опыту!"},
    {"event_type": "shop_discount", "effect": "0.2", "desc": "Сегодня цены в магазине снижены на 20%!"},
    {"event_type": "fishing_bonus", "effect": "2.0", "desc": "Сегодня рыбалка даёт x2 рыбнеток!"},
]

def get_todays_event_proposal():
    today = date.today()
    seed = int(today.strftime("%Y%m%d"))
    rng = random.Random(seed)
    return rng.choice(DAILY_EVENTS)

def check_vote_result():
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT vote, COUNT(*) FROM votes WHERE date = ? GROUP BY vote", (today,))
    rows = c.fetchall()
    conn.close()
    yes_v = no_v = 0
    for v, count in rows:
        if v == "yes": yes_v = count
        elif v == "no": no_v = count
    return (yes_v + no_v) >= 3 and yes_v > no_v

def activate_event(event_type, effect):
    expires = datetime.now() + timedelta(hours=24)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE active_events SET active = 0 WHERE active = 1")
    c.execute("INSERT INTO active_events (event_type, effect, expires_at, active) VALUES (?, ?, ?, 1)", (event_type, effect, expires.isoformat()))
    conn.commit()
    conn.close()

def get_active_event_text():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT event_type FROM active_events WHERE active = 1 AND expires_at > ?", (datetime.now().isoformat(),))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    for ev in DAILY_EVENTS:
        if ev["event_type"] == row[0]:
            return ev["desc"]
    return None

# ==================== СТАТУС ТЮЛЕНЯ ====================

def get_married_seal_ids():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT seal1_id FROM marriages UNION SELECT seal2_id FROM marriages")
    ids = set(row[0] for row in c.fetchall())
    conn.close()
    return ids

def get_seal_status_emoji(seal, marriages_set):
    if seal[11] == 1: return "🍼"
    if seal[3] <= 0: return "💀"
    if seal[5] < 30 or seal[6] < 20: return "😴"
    if seal[0] in marriages_set: return "❤️"
    work_cd = seal[18]
    if work_cd:
        try:
            cd_time = datetime.fromisoformat(work_cd)
            cd_min = seal[21] if seal[21] else 30
            if datetime.now() - cd_time < timedelta(minutes=cd_min):
                return "💼"
        except Exception:
            pass
    if seal[5] >= 50 and seal[6] >= 50: return "🎮"
    if seal[3] > 50: return "⚔️"
    return "🦭"
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
    show_main_menu(user_id)

@bot.message_handler(commands=['help'])
def cmd_help(message):
    user_id = message.from_user.id
    text = ("🦭 *Справка по командам*\n\n"
            "*Основные:*\n  /start — главное меню\n  /help — эта справка\n"
            "  /profile — профиль\n  /gallery — галерея тюленей\n"
            "  /setphoto — фото тюленя\n  /leaderboard — лидеры\n\n"
            "*Магазин и крафт:*\n  /shop — магазин\n  /craft — крафт из ресурсов\n  /trade — биржа\n\n"
            "*Сражения:*\n  /battle — бой с боссом\n  /dungeon — подземелье\n  /work — работа\n\n"
            "*Активности:*\n  /fish — рыбалка\n  /vote — голосование\n"
            "  /faction — фракции\n  /marry — брак (макс. 5)\n  /quests — задания\n\n"
            "*Регенерация:* +25 HP в час")
    bot.send_message(user_id, text, parse_mode='Markdown')
    show_main_menu(user_id)

def show_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🦭 Мой тюлень"), types.KeyboardButton("👤 Профиль"))
    markup.add(types.KeyboardButton("🛒 Магазин"), types.KeyboardButton("⚔️ Бой"))
    markup.add(types.KeyboardButton("🏰 Подземелье"), types.KeyboardButton("💼 Работа"))
    markup.add(types.KeyboardButton("🔨 Крафт"), types.KeyboardButton("📋 Задания"))
    markup.add(types.KeyboardButton("💍 Брак"), types.KeyboardButton("🎣 Рыбалка"))
    markup.add(types.KeyboardButton("🏆 Лидеры"), types.KeyboardButton("🗳 Голосование"))
    markup.add(types.KeyboardButton("📦 Биржа"), types.KeyboardButton("🏛 Фракции"))
    bot.send_message(user_id, "Выберите действие:", reply_markup=markup)

@bot.message_handler(commands=['profile'])
@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def cmd_profile(message):
    user_id = message.from_user.id
    player = get_player(user_id)
    if not player:
        bot.send_message(user_id, "Вы не зарегистрированы. Напишите /start")
        return
    count = get_seal_count(user_id)
    fishnets = player[4]
    faction_name = FACTIONS[player[5]]["name"] if player[5] and player[5] in FACTIONS else "Нет"
    rep = player[6]
    text = f"👤 *Ваш профиль*\n\nТюленей: {count} / {MAX_SEALS}\nРыбнетки: 🐟 {fishnets}\nФракция: {faction_name}"
    if player[5]:
        text += f" (репутация: {rep})"
    ev = get_active_event_text()
    if ev:
        text += f"\n\n🎉 Активное событие: {ev}"
    bot.send_message(user_id, text, parse_mode='Markdown')

@bot.message_handler(commands=['gallery'])
def cmd_gallery(message):
    user_id = message.from_user.id
    seals = get_player_seals(user_id)
    if not seals:
        bot.send_message(user_id, "У вас нет тюленей! Напишите /start")
        return
    married_ids = get_married_seal_ids()
    fishnets = get_fishnets(user_id)
    text = f"🖼 *Галерея тюленей*\n🐟 Рыбнетки: {fishnets}\n\n"
    for s in seals:
        status = get_seal_status_emoji(s, married_ids)
        text += f"{status} *{s[2]}* — ур.{s[9]}\n  💪 Сила: {s[7]} | 🛡️ Защита: {s[8]} | 🍖 Сытость: {s[6]} | ❤️ HP: {s[3]}/{s[4]}\n"
        if s[11] == 1:
            text += "  🍼 Тюленёнок\n"
        text += "\n"
    bot.send_message(user_id, text, parse_mode='Markdown')

@bot.message_handler(commands=['leaderboard'])
@bot.message_handler(func=lambda m: m.text == "🏆 Лидеры")
def cmd_leaderboard(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT seals.name, seals.level, players.username
                 FROM seals JOIN players ON seals.owner_id = players.user_id
                 ORDER BY seals.level DESC, seals.exp DESC LIMIT 20''')
    rows = c.fetchall()
    conn.close()
    if not rows:
        bot.send_message(message.from_user.id, "Таблица лидеров пуста!")
        return
    text = "🏆 *Таблица лидеров*\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, level, username) in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        text += f"{medal} {name} — ур.{level} (@{username})\n"
    bot.send_message(message.from_user.id, text, parse_mode='Markdown')

@bot.message_handler(commands=['setphoto'])
def cmd_setphoto(message):
    user_id = message.from_user.id
    seals = get_player_seals(user_id)
    if not seals:
        bot.send_message(user_id, "У вас нет тюленей! Напишите /start")
        return
    markup = types.InlineKeyboardMarkup()
    for s in seals:
        markup.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"setphoto_sel_{s[0]}"))
    bot.send_message(user_id, "📸 Выберите тюленя для установки фото:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("setphoto_sel_"))
def setphoto_select(call):
    seal_id = int(call.data.split("_")[2])
    bot.send_message(call.from_user.id, "Отправьте фото для тюленя:")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, lambda m: process_seal_photo(m, seal_id))

def process_seal_photo(message, seal_id):
    user_id = message.from_user.id
    if not message.photo:
        bot.send_message(user_id, "Это не фото! Попробуйте через меню тюленя.")
        return
    try:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        downloaded = bot.download_file(file_info.file_path)
        os.makedirs("photos", exist_ok=True)
        path = f"photos/seal_{seal_id}.jpg"
        with open(path, 'wb') as f:
            f.write(downloaded)
        update_seal(seal_id, photo_path=path)
        bot.send_message(user_id, "✅ Фото тюленя обновлено!")
    except Exception as e:
        bot.send_message(user_id, f"❌ Ошибка: {e}")

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
    user_id = call.from_user.id
    fishnets = get_fishnets(user_id)
    eff_str, eff_def, eff_hp = get_effective_stats(seal_id)
    mood_bonus = get_mood_bonus(seal_id)
    text = f"🦭 *{seal[2]}*\n🐟 Рыбнетки: {fishnets}\n\n"
    text += f"Уровень: {seal[9]} (опыт: {seal[10]}/{exp_for_level(seal[9])})\n"
    text += f"❤️ Здоровье: {seal[3]}/{seal[4]}\n"
    text += f"😊 Настроение: {seal[5]}"
    if mood_bonus > 0:
        text += f" (+{mood_bonus} от аксессуара)"
    text += f"\n🍖 Сытость: {seal[6]}\n💪 Сила: {seal[7]} (с экип: {eff_str})\n🛡️ Защита: {seal[8]} (с экип: {eff_def})\n"
    equipped = []
    if seal[13]: equipped.append(f"⚔️ {seal[13]}")
    if seal[14]: equipped.append(f"🛡️ {seal[14]}")
    if seal[15]: equipped.append(f"🪖 {seal[15]}")
    if seal[16]: equipped.append(f"🛡️ {seal[16]}")
    if seal[17]: equipped.append(f"🎀 {seal[17]}")
    text += f"\nЭкипировка: {', '.join(equipped) if equipped else 'нет'}\n"
    if seal[11] == 1:
        text += "\n🍼 Это тюленёнок! Он вырастет через несколько дней.\n"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🍖 Покормить", callback_data=f"feed_{seal_id}"),
               types.InlineKeyboardButton("🎾 Поиграть", callback_data=f"play_{seal_id}"))
    markup.add(types.InlineKeyboardButton("💊 Лечить", callback_data=f"heal_{seal_id}"),
               types.InlineKeyboardButton("👕 Экипировка", callback_data=f"equip_{seal_id}"))
    markup.add(types.InlineKeyboardButton("📸 Фото", callback_data=f"setphoto_sel_{seal_id}"),
               types.InlineKeyboardButton("✏️ Переименовать", callback_data=f"rename_{seal_id}"))
    markup.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back_main"))
    chat_id, message_id = call.message.chat.id, call.message.message_id
    photo_path = seal[20]
    if photo_path and os.path.exists(photo_path):
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
        try:
            with open(photo_path, 'rb') as f:
                bot.send_photo(chat_id, f, caption=text, reply_markup=markup, parse_mode='Markdown')
        except Exception:
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')
    else:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='Markdown')
        except Exception:
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("feed_"))
def seal_feed(call):
    user_id = call.from_user.id
    seal_id = int(call.data.split("_")[1])
    inv = get_inventory(user_id)
    food_items = [i for i in inv if i[3] == "food"]
    if not food_items:
        bot.answer_callback_query(call.id, "У вас нет еды! Купите в магазине.")
        return
    markup = types.InlineKeyboardMarkup()
    for item in food_items:
        info = SHOP_ITEMS.get(item[2], {})
        markup.add(types.InlineKeyboardButton(f"{item[2]} (x{item[4]}) — сытость +{info.get('satiety', 0)}", callback_data=f"do_feed_{seal_id}_{item[2]}"))
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
    update_seal(seal_id, satiety=min(100, seal[6] + info["satiety"]), mood=min(100, seal[5] + info.get("mood", 5)))
    remove_from_inventory(user_id, item_name)
    bot.answer_callback_query(call.id, f"{seal[2]} съел {item_name}!")
    update_quest_progress(user_id, "feed", 1)
    seal_selected(call, seal_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("heal_"))
def seal_heal(call):
    user_id = call.from_user.id
    seal_id = int(call.data.split("_")[1])
    seal = get_seal(seal_id)
    if not seal:
        return
    if seal[3] >= seal[4]:
        bot.answer_callback_query(call.id, "Тюлень уже здоров!")
        return
    if get_item_quantity(user_id, "Аптечка 💊") <= 0:
        bot.answer_callback_query(call.id, "У вас нет аптечек!")
        return
    heal_amount = SHOP_ITEMS["Аптечка 💊"]["heal"]
    new_hp = min(seal[4], seal[3] + heal_amount)
    update_seal(seal_id, health=new_hp)
    remove_from_inventory(user_id, "Аптечка 💊")
    bot.answer_callback_query(call.id, f"💊 {seal[2]} вылечен на {heal_amount} HP!")
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
    play_cd = seal[19]
    if play_cd:
        try:
            remaining = timedelta(minutes=PLAY_COOLDOWN_MIN) - (datetime.now() - datetime.fromisoformat(play_cd))
            if remaining.total_seconds() > 0:
                bot.answer_callback_query(call.id, f"⏳ Подождите {int(remaining.total_seconds()//60)}м {int(remaining.total_seconds()%60)}с")
                return
        except Exception:
            pass
    exp_gain = int(random.randint(5, 15) * get_exp_multiplier())
    update_seal(seal_id, mood=min(100, seal[5] + 25), satiety=max(0, seal[6] - 5),
                exp=seal[10] + exp_gain, play_cooldown=datetime.now().isoformat())
    leveled = check_levelup(seal_id)
    update_quest_progress(user_id, "play", 1)
    player = get_player(user_id)
    if player and player[5] == "fashion":
        add_faction_rep(user_id, 1)
    msg = f"🎾 Поиграли с {seal[2]}! Настроение +25, опыт +{exp_gain}"
    if leveled:
        msg += f"\n🎉 Уровень {leveled}!"
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
    bot.send_message(message.from_user.id, f"✅ Переименован в {new_name}!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("equip_"))
def seal_equip_menu(call):
    user_id = call.from_user.id
    seal_id = int(call.data.split("_")[1])
    inv = get_inventory(user_id)
    gear_types = ("weapon", "armor", "helmet", "shield", "accessory")
    gear_items = [i for i in inv if ITEM_TYPES.get(i[3]) in gear_types or i[3] in gear_types]
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
    item_type = ITEM_TYPES.get(item_name)
    if not item_type:
        bot.answer_callback_query(call.id, "Предмет не найден!")
        return
    seal = get_seal(seal_id)
    if not seal:
        return
    slot_map = {"weapon": "equipped_weapon", "armor": "equipped_armor", "helmet": "equipped_helmet", "shield": "equipped_shield", "accessory": "equipped_accessory"}
    slot = slot_map.get(item_type)
    if not slot:
        bot.answer_callback_query(call.id, "Неизвестный тип!")
        return
    col_idx = {"equipped_weapon": 13, "equipped_armor": 14, "equipped_helmet": 15, "equipped_shield": 16, "equipped_accessory": 17}.get(slot)
    current_val = seal[col_idx] if col_idx is not None else None
    if current_val:
        add_to_inventory(user_id, current_val, ITEM_TYPES.get(current_val, "armor"), 1)
    update_seal(seal_id, **{slot: item_name})
    remove_from_inventory(user_id, item_name)
    player = get_player(user_id)
    if player and player[5] == "fashion" and item_type == "accessory":
        add_faction_rep(user_id, 2)
    bot.answer_callback_query(call.id, f"Надето: {item_name}")
    seal_selected(call, seal_id)

@bot.callback_query_handler(func=lambda c: c.data == "back_main")
def back_to_main(call):
    show_main_menu(call.from_user.id)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass

# ==================== МАГАЗИН ====================

@bot.message_handler(commands=['shop'])
@bot.message_handler(func=lambda m: m.text == "🛒 Магазин")
def menu_shop(message):
    user_id = message.from_user.id
    fishnets = get_fishnets(user_id)
    total_disc = max(get_shop_discount(), get_faction_discount(user_id))
    text = f"🛒 *Магазин*\nУ вас: 🐟 {fishnets}\n"
    if total_disc > 0:
        text += f"🎁 Скидка: {int(total_disc * 100)}%\n"
    text += "\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for name, info in SHOP_ITEMS.items():
        price = int(info["price"] * (1 - total_disc))
        if info["type"] == "food":
            text += f"  {name} — 🐟{price} (сытость +{info['satiety']}, настроение +{info.get('mood', 0)})\n"
        elif info["type"] == "medkit":
            text += f"  {name} — 🐟{price} (лечит +{info['heal']} HP)\n"
        elif info["type"] == "accessory":
            text += f"  {name} — 🐟{price} (настроение +{ACCESSORY_BONUSES.get(name, 0)})\n"
        markup.add(types.InlineKeyboardButton(f"Купить {name} — 🐟{price}", callback_data=f"buy_{name}"))
    bot.send_message(user_id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_"))
def shop_buy(call):
    user_id = call.from_user.id
    item_name = call.data[4:]
    info = SHOP_ITEMS.get(item_name)
    if not info:
        bot.answer_callback_query(call.id, "Предмет не найден!")
        return
    total_disc = max(get_shop_discount(), get_faction_discount(user_id))
    price = int(info["price"] * (1 - total_disc))
    if get_fishnets(user_id) < price:
        bot.answer_callback_query(call.id, "Недостаточно рыбнеток!")
        return
    add_fishnets(user_id, -price)
    add_to_inventory(user_id, item_name, info["type"])
    update_quest_progress(user_id, "shop", 1)
    bot.answer_callback_query(call.id, f"Куплено: {item_name} за 🐟{price}!")

# ==================== КРАФТ ====================

@bot.message_handler(commands=['craft'])
@bot.message_handler(func=lambda m: m.text == "🔨 Крафт")
def menu_craft(message):
    user_id = message.from_user.id
    text = "🔨 *Крафт*\n\n"
    for recipe in CRAFT_RECIPES:
        res_text = ", ".join([f"{r} x{a}" for r, a in recipe["resources"].items()])
        bonus = ITEM_BONUSES.get(recipe["name"], {})
        bt = ""
        if "str" in bonus: bt += f"💪+{bonus['str']} "
        if "def" in bonus: bt += f"🛡️+{bonus['def']} "
        if "hp" in bonus: bt += f"❤️+{bonus['hp']}"
        text += f"{recipe['name']} ({bt.strip()})\n  Нужно: {res_text}\n\n"
    markup = types.InlineKeyboardMarkup()
    for recipe in CRAFT_RECIPES:
        can = "✅" if can_craft(user_id, recipe) else "❌"
        markup.add(types.InlineKeyboardButton(f"{can} {recipe['name']}", callback_data=f"craft_{recipe['name']}"))
    bot.send_message(user_id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("craft_"))
def craft_do(call):
    user_id = call.from_user.id
    item_name = call.data[6:]
    recipe = next((r for r in CRAFT_RECIPES if r["name"] == item_name), None)
    if not recipe:
        bot.answer_callback_query(call.id, "Рецепт не найден!")
        return
    if not can_craft(user_id, recipe):
        bot.answer_callback_query(call.id, "Недостаточно ресурсов!")
        return
    for resource, amount in recipe["resources"].items():
        remove_from_inventory(user_id, resource, amount)
    add_to_inventory(user_id, item_name, recipe["type"])
    update_quest_progress(user_id, "craft", 1)
    player = get_player(user_id)
    if player and player[5] == "hunters":
        add_faction_rep(user_id, 1)
    bot.answer_callback_query(call.id, f"Скрафчено: {item_name}!")

# ==================== РАБОТА ====================

@bot.message_handler(commands=['work'])
@bot.message_handler(func=lambda m: m.text == "💼 Работа")
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
        bot.send_message(user_id, "Все ваши тюлени — малыши!")
        return
    bot.send_message(user_id, "💼 Выберите тюленя для работы:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("worksel_"))
def work_select_job(call):
    seal_id = int(call.data.split("_")[1])
    seal = get_seal(seal_id)
    if not seal:
        return
    if seal[6] < 20:
        bot.answer_callback_query(call.id, "Сытость < 20, покормите тюленя!")
        return
    work_cd = seal[18]
    if work_cd:
        try:
            cd_min = seal[21] if seal[21] else 30
            remaining = timedelta(minutes=cd_min) - (datetime.now() - datetime.fromisoformat(work_cd))
            if remaining.total_seconds() > 0:
                bot.answer_callback_query(call.id, f"⏳ Подождите {int(remaining.total_seconds()//60)}м {int(remaining.total_seconds()%60)}с")
                return
        except Exception:
            pass
    text = f"💼 Выберите работу для {seal[2]}:\n\n"
    for i, job in enumerate(JOBS):
        text += f"{i+1}. {job['name']} — 🐟{job['reward_min']}-{job['reward_max']}, кд {job['cooldown_min']}мин\n"
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
    if not seal or seal[6] < 20 or seal[5] < 10:
        bot.answer_callback_query(call.id, "Тюлень не может работать!")
        return
    work_cd = seal[18]
    if work_cd:
        try:
            remaining = timedelta(minutes=job["cooldown_min"]) - (datetime.now() - datetime.fromisoformat(work_cd))
            if remaining.total_seconds() > 0:
                bot.answer_callback_query(call.id, f"⏳ Подождите {int(remaining.total_seconds()//60)}м {int(remaining.total_seconds()%60)}с")
                return
        except Exception:
            pass
    reward = random.randint(job["reward_min"], job["reward_max"]) + seal[9] * 3
    exp_gain = int(random.randint(10, 25) * get_exp_multiplier())
    update_seal(seal_id, mood=max(0, seal[5] - job["mood_cost"]), satiety=max(0, seal[6] - job["satiety_cost"]),
                exp=seal[10] + exp_gain, work_cooldown=datetime.now().isoformat(), work_cooldown_min=job["cooldown_min"])
    add_fishnets(user_id, reward)
    leveled = check_levelup(seal_id)
    log = f"💼 {seal[2]} поработал: {job['name']}\n💰 🐟{reward}\n📈 Опыт +{exp_gain}\n⏳ КД {job['cooldown_min']}мин"
    if leveled:
        log += f"\n🎉 Уровень {leveled}!"
    update_quest_progress(user_id, "work", 1)
    bot.edit_message_text(log, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

# ==================== БОИ ====================

@bot.message_handler(commands=['battle'])
@bot.message_handler(func=lambda m: m.text == "⚔️ Бой")
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
        bot.send_message(user_id, "Все ваши тюлени — малыши!")
        return
    bot.send_message(user_id, "Выберите тюленя для боя:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("battle_"))
def do_battle(call):
    user_id = call.from_user.id
    seal_id = int(call.data.split("_")[1])
    seal = get_seal(seal_id)
    if not seal or seal[3] <= 0:
        bot.answer_callback_query(call.id, "Тюлень не может драться!")
        return
    eff_str, eff_def, eff_hp = get_effective_stats(seal_id)
    boss = random.choice(BOSSES)
    boss_name = boss["name"]
    boss_hp = random.randint(60, 100) + seal[9] * 10
    boss_str = random.randint(8, 15) + seal[9] * 2
    boss_def = random.randint(3, 8) + seal[9]
    log = [f"⚔️ *Бой: {seal[2]} vs {boss_name}*\n", f"{seal[2]}: ❤️{eff_hp} 💪{eff_str} 🛡️{eff_def}", f"{boss_name}: ❤️{boss_hp} 💪{boss_str} 🛡️{boss_def}\n"]
    seal_hp = seal[3]
    for rnd in range(1, 21):
        if seal_hp <= 0 or boss_hp <= 0:
            break
        dmg = max(1, eff_str - boss_def + random.randint(-3, 5))
        boss_hp -= dmg
        log.append(f"Р{rnd}: {seal[2]} бьёт на {dmg}! (босс {max(0,boss_hp)}❤️)")
        if boss_hp <= 0:
            break
        dmg_m = max(1, boss_str - eff_def + random.randint(-2, 4))
        seal_hp -= dmg_m
        log.append(f"{boss_name} бьёт на {dmg_m}! ({seal[2]} {max(0,seal_hp)}❤️)")
    if boss_hp <= 0:
        reward = random.randint(20, 50) + seal[9] * 5
        exp_gain = int(random.randint(20, 40) * get_exp_multiplier())
        add_fishnets(user_id, reward)
        update_seal(seal_id, exp=seal[10] + exp_gain, mood=min(100, seal[5] + 15))
        leveled = check_levelup(seal_id)
        log.append(f"\n🎉 *Победа!* 🐟{reward}, опыт +{exp_gain}")
        if leveled:
            log.append(f"📈 Уровень {leveled}!")
        dropped = process_drops(user_id, boss["drops"])
        if dropped:
            log.append(f"📦 Добыча: {', '.join(dropped)}")
        update_quest_progress(user_id, "battle", 1)
        player = get_player(user_id)
        if player and player[5] == "hunters":
            add_faction_rep(user_id, 2)
    elif seal_hp <= 0:
        update_seal(seal_id, health=max(1, seal[3] // 4), mood=max(0, seal[5] - 20))
        log.append(f"\n💀 *Поражение...*")
    else:
        log.append("\n🤝 Ничья!")
    bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown')

# ==================== ПОДЗЕМЕЛЬЕ ====================

@bot.message_handler(commands=['dungeon'])
@bot.message_handler(func=lambda m: m.text == "🏰 Подземелье")
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
    bot.send_message(user_id, "🏰 Выберите тюленя для подземелья (5 этажей):", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dngstart_"))
def dungeon_start(call):
    user_id = call.from_user.id
    seal_id = int(call.data.split("_")[1])
    seal = get_seal(seal_id)
    if not seal:
        return
    if seal[3] <= 20:
        bot.answer_callback_query(call.id, "HP < 20, лечите тюленя!")
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
    monster = get_dungeon_monster(floor)
    eff_str, eff_def, _ = get_effective_stats(seal_id)
    text = f"🏰 *Этаж {floor}/5*\n\n🦭 {seal[2]}: ❤️{seal[3]} 💪{eff_str} 🛡️{eff_def}\n{monster['name']}: ❤️{monster['hp']} 💪{monster['str']} 🛡️{monster['def']}\n"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⚔️ Атаковать", callback_data=f"dng_atk_{seal_id}_{floor}"))
    markup.add(types.InlineKeyboardButton("🏃 Сбежать", callback_data=f"dng_flee_{seal_id}_{floor}"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dng_atk_"))
def dungeon_attack(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    seal_id, floor = int(parts[2]), int(parts[3])
    seal = get_seal(seal_id)
    if not seal:
        return
    monster = get_dungeon_monster(floor)
    eff_str, eff_def, _ = get_effective_stats(seal_id)
    seal_hp = seal[3]
    log = [f"⚔️ Этаж {floor}: {seal[2]} vs {monster['name']}"]
    while seal_hp > 0 and monster["hp"] > 0:
        dmg = max(1, eff_str - monster["def"] + random.randint(-2, 5))
        monster["hp"] -= dmg
        log.append(f"{seal[2]} бьёт на {dmg}! (монстр {max(0,monster['hp'])}❤️)")
        if monster["hp"] <= 0:
            break
        dmg_m = max(1, monster["str"] - eff_def + random.randint(-1, 4))
        seal_hp -= dmg_m
        log.append(f"{monster['name']} бьёт на {dmg_m}! ({seal[2]} {max(0,seal_hp)}❤️)")
    if monster["hp"] <= 0:
        update_seal(seal_id, health=max(1, seal_hp))
        log.append("\n✅ Монстр повержен!")
        dropped = process_drops(user_id, monster["drops"])
        if dropped:
            log.append(f"📦 Добыча: {', '.join(dropped)}")
        if floor >= 5:
            reward = 100 + floor * 30
            exp_gain = int((50 + floor * 20) * get_exp_multiplier())
            add_fishnets(user_id, reward)
            s = get_seal(seal_id)
            update_seal(seal_id, exp=s[10] + exp_gain)
            leveled = check_levelup(seal_id)
            log.append(f"🏆 *Пройдено!* 🐟{reward}, опыт +{exp_gain}")
            if leveled:
                log.append(f"📈 Уровень {leveled}!")
            update_quest_progress(user_id, "dungeon", 1)
            player = get_player(user_id)
            if player and player[5] == "explorers":
                add_faction_rep(user_id, 3)
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE dungeon_runs SET active = 0 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        else:
            nf = floor + 1
            log.append(f"Открыт этаж {nf}!")
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("➡️ Дальше", callback_data=f"dng_next_{seal_id}_{nf}"))
            markup.add(types.InlineKeyboardButton("🏃 Выйти", callback_data=f"dng_flee_{seal_id}_{floor}"))
            bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)
    elif seal_hp <= 0:
        update_seal(seal_id, health=1, mood=max(0, seal[5] - 30))
        log.append(f"\n💀 {seal[2]} повержен...")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE dungeon_runs SET active = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        bot.edit_message_text("\n".join(log), call.message.chat.id, call.message.message_id, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("dng_next_"))
def dungeon_next(call):
    parts = call.data.split("_")
    dungeon_floor(call, int(parts[2]), int(parts[3]))

@bot.callback_query_handler(func=lambda c: c.data.startswith("dng_flee_"))
def dungeon_flee(call):
    user_id = call.from_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE dungeon_runs SET active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    bot.edit_message_text("🏃 Вы сбежали.", call.message.chat.id, call.message.message_id)

# ==================== РЫБАЛКА ====================

FISH_TYPES = [
    {"name": "Малёк 🐤", "reward": (3, 8), "correct": "Подсечь!"},
    {"name": "Окунь 🐟", "reward": (8, 15), "correct": "Подсечь!"},
    {"name": "Сёмга 🐠", "reward": (15, 25), "correct": "Ждать"},
    {"name": "Золотая рыбка ✨", "reward": (30, 50), "correct": "Ждать"},
    {"name": "Краб 🦀", "reward": (10, 20), "correct": "Отпустить"},
]

@bot.message_handler(commands=['fish'])
@bot.message_handler(func=lambda m: m.text == "🎣 Рыбалка")
def cmd_fish(message):
    user_id = message.from_user.id
    player = get_player(user_id)
    if not player:
        bot.send_message(user_id, "Напишите /start")
        return
    fish_cd = player[7]
    if fish_cd:
        try:
            remaining = timedelta(minutes=FISHING_COOLDOWN_MIN) - (datetime.now() - datetime.fromisoformat(fish_cd))
            if remaining.total_seconds() > 0:
                bot.send_message(user_id, f"⏳ Подождите {int(remaining.total_seconds()//60)}м {int(remaining.total_seconds()%60)}с")
                return
        except Exception:
            pass
    fish = random.choice(FISH_TYPES)
    opts = ["Подсечь!", "Ждать", "Отпустить"]
    opts.remove(fish["correct"])
    opts.append(fish["correct"])
    random.shuffle(opts)
    text = f"🎣 *Рыбалка!*\n\nПоклёвка! Кажется, это {fish['name']}.\nЧто делать? У вас 5 секунд!\n"
    markup = types.InlineKeyboardMarkup(row_width=3)
    for opt in opts:
        markup.add(types.InlineKeyboardButton(opt, callback_data=f"fish_{opt}_{fish['name']}"))
    msg = bot.send_message(user_id, text, parse_mode='Markdown', reply_markup=markup)
    def timeout():
        time.sleep(5)
        try:
            bot.edit_message_text(f"⏰ Время вышло! {fish['name']} уплыл.", msg.chat.id, msg.message_id)
        except Exception:
            pass
        update_player(user_id, fish_cooldown=datetime.now().isoformat())
    threading.Thread(target=timeout, daemon=True).start()

@bot.callback_query_handler(func=lambda c: c.data.startswith("fish_"))
def fish_callback(call):
    user_id = call.from_user.id
    parts = call.data.split("_", 2)
    action, fish_name = parts[1], parts[2]
    fish = next((f for f in FISH_TYPES if f["name"] == fish_name), None)
    if not fish:
        bot.answer_callback_query(call.id, "Рыбалка истекла!")
        return
    bonus = get_fishing_bonus()
    r_min, r_max = int(fish["reward"][0] * bonus), int(fish["reward"][1] * bonus)
    if action == fish["correct"]:
        reward = random.randint(r_min, r_max)
        add_fishnets(user_id, reward)
        bot.edit_message_text(call.message.chat.id, call.message.message_id, f"🎣 *Поймано!*\n\n{fish_name}!\nНаграда: 🐟{reward}", parse_mode='Markdown')
    else:
        bot.edit_message_text(call.message.chat.id, call.message.message_id, f"💨 {fish_name} сорвался!\nНужно было: {fish['correct']}", parse_mode='Markdown')
    update_player(user_id, fish_cooldown=datetime.now().isoformat())

# ==================== БИРЖА ====================

@bot.message_handler(commands=['trade'])
@bot.message_handler(func=lambda m: m.text == "📦 Биржа")
def menu_trade(message):
    user_id = message.from_user.id
    text = "📦 *Биржа предметов*\n\n"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📤 Создать оффер", callback_data="trade_create"))
    markup.add(types.InlineKeyboardButton("📋 Активные офферы", callback_data="trade_list_0"))
    markup.add(types.InlineKeyboardButton("📦 Мои офферы", callback_data="trade_mine"))
    bot.send_message(user_id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "trade_create")
def trade_create(call):
    user_id = call.from_user.id
    inv = get_inventory(user_id)
    if not inv:
        bot.answer_callback_query(call.id, "У вас нет предметов!")
        return
    markup = types.InlineKeyboardMarkup()
    for item in inv:
        if item[3] == "resource":
            continue
        markup.add(types.InlineKeyboardButton(f"{item[2]} (x{item[4]})", callback_data=f"tradesel_{item[2]}"))
    markup.add(types.InlineKeyboardButton("◀️ Назад", callback_data="trade_back"))
    bot.edit_message_text("Что выставить на продажу?", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tradesel_"))
def trade_select_price(call):
    item_name = call.data[9:]
    bot.send_message(call.from_user.id, f"Введите цену для {item_name} (в рыбнетках):")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, lambda m: trade_set_price(m, item_name))

def trade_set_price(message, item_name):
    user_id = message.from_user.id
    try:
        price = int(message.text.strip())
    except ValueError:
        bot.send_message(user_id, "Неверная цена!")
        return
    if price < 1:
        bot.send_message(user_id, "Цена должна быть больше 0!")
        return
    item_type = ITEM_TYPES.get(item_name, "misc")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO trade_offers (seller_id, item_name, item_type, price, created_at, active) VALUES (?, ?, ?, ?, ?, 1)", (user_id, item_name, item_type, price, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    remove_from_inventory(user_id, item_name)
    bot.send_message(user_id, f"✅ Оффер: {item_name} за 🐟{price}!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("trade_list_"))
def trade_list(call):
    user_id = call.from_user.id
    page = int(call.data.split("_")[2]) if "_" in call.data[11:] else 0
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT offer_id, item_name, price FROM trade_offers WHERE active = 1 AND seller_id != ? ORDER BY created_at DESC LIMIT 10 OFFSET ?", (user_id, page * 10))
    offers = c.fetchall()
    conn.close()
    if not offers:
        bot.edit_message_text("Нет активных офферов.", call.message.chat.id, call.message.message_id)
        return
    text = "📋 *Активные офферы*\n\n"
    markup = types.InlineKeyboardMarkup()
    for offer_id, item_name, price in offers:
        text += f"  {item_name} — 🐟{price}\n"
        markup.add(types.InlineKeyboardButton(f"Купить {item_name} — 🐟{price}", callback_data=f"tradebuy_{offer_id}"))
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("◀️ Назад", callback_data=f"trade_list_{page-1}"))
    nav.append(types.InlineKeyboardButton("➡️ Далее", callback_data=f"trade_list_{page+1}"))
    markup.add(*nav)
    markup.add(types.InlineKeyboardButton("◀️ В меню биржи", callback_data="trade_back"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tradebuy_"))
def trade_buy(call):
    user_id = call.from_user.id
    offer_id = int(call.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT seller_id, item_name, item_type, price, active FROM trade_offers WHERE offer_id = ?", (offer_id,))
    row = c.fetchone()
    if not row or not row[4]:
        bot.answer_callback_query(call.id, "Оффер не найден!")
        conn.close()
        return
    seller_id, item_name, item_type, price, _ = row
    if seller_id == user_id:
        bot.answer_callback_query(call.id, "Нельзя купить свой оффер!")
        conn.close()
        return
    if get_fishnets(user_id) < price:
        bot.answer_callback_query(call.id, "Недостаточно рыбнеток!")
        conn.close()
        return
    add_fishnets(user_id, -price)
    add_fishnets(seller_id, price)
    add_to_inventory(user_id, item_name, item_type)
    c.execute("UPDATE trade_offers SET active = 0 WHERE offer_id = ?", (offer_id,))
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, f"Куплено: {item_name} за 🐟{price}!")
    try:
        bot.send_message(seller_id, f"💰 Ваш оффер куплен!\n{item_name} продан за 🐟{price}.")
    except Exception:
        pass

@bot.callback_query_handler(func=lambda c: c.data == "trade_mine")
def trade_mine(call):
    user_id = call.from_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT offer_id, item_name, price, active FROM trade_offers WHERE seller_id = ? ORDER BY created_at DESC", (user_id,))
    offers = c.fetchall()
    conn.close()
    if not offers:
        bot.answer_callback_query(call.id, "У вас нет офферов!")
        return
    text = "📦 *Мои офферы*\n\n"
    markup = types.InlineKeyboardMarkup()
    for offer_id, item_name, price, active in offers:
        text += f"  {'✅' if active else '❌'} {item_name} — 🐟{price}\n"
        if active:
            markup.add(types.InlineKeyboardButton(f"Снять {item_name}", callback_data=f"tradecancel_{offer_id}"))
    markup.add(types.InlineKeyboardButton("◀️ В меню биржи", callback_data="trade_back"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tradecancel_"))
def trade_cancel(call):
    user_id = call.from_user.id
    offer_id = int(call.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT item_name, item_type, active FROM trade_offers WHERE offer_id = ? AND seller_id = ?", (offer_id, user_id))
    row = c.fetchone()
    if not row or not row[2]:
        bot.answer_callback_query(call.id, "Оффер не найден!")
        conn.close()
        return
    c.execute("UPDATE trade_offers SET active = 0 WHERE offer_id = ?", (offer_id,))
    conn.commit()
    conn.close()
    add_to_inventory(user_id, row[0], row[1])
    bot.answer_callback_query(call.id, f"Снято: {row[0]}!")

@bot.callback_query_handler(func=lambda c: c.data == "trade_back")
def trade_back(call):
    text = "📦 *Биржа*\n\n"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📤 Создать оффер", callback_data="trade_create"))
    markup.add(types.InlineKeyboardButton("📋 Активные офферы", callback_data="trade_list_0"))
    markup.add(types.InlineKeyboardButton("📦 Мои офферы", callback_data="trade_mine"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

# ==================== ФРАКЦИИ ====================

@bot.message_handler(commands=['faction'])
@bot.message_handler(func=lambda m: m.text == "🏛 Фракции")
def menu_faction(message):
    user_id = message.from_user.id
    player = get_player(user_id)
    if not player:
        bot.send_message(user_id, "Напишите /start")
        return
    text = "🏛 *Фракции*\n\n"
    for fid, fdata in FACTIONS.items():
        marker = " ✅" if player[5] == fid else ""
        text += f"*{fdata['name']}*{marker}\n  {fdata['desc']}\n"
        if player[5] == fid:
            text += f"  Репутация: {player[6]}\n"
        text += "\n"
    markup = types.InlineKeyboardMarkup()
    for fid, fdata in FACTIONS.items():
        if player[5] == fid:
            markup.add(types.InlineKeyboardButton(f"🔄 Сменить на {fdata['name']}", callback_data=f"factionjoin_{fid}"))
        else:
            markup.add(types.InlineKeyboardButton(f"Присоединиться: {fdata['name']}", callback_data=f"factionjoin_{fid}"))
    bot.send_message(user_id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("factionjoin_"))
def faction_join(call):
    faction_id = call.data.split("_")[1]
    if faction_id not in FACTIONS:
        bot.answer_callback_query(call.id, "Фракция не найдена!")
        return
    update_player(call.from_user.id, faction=faction_id, faction_rep=0)
    bot.answer_callback_query(call.id, f"Вступили: {FACTIONS[faction_id]['name']}!")

# ==================== ГОЛОСОВАНИЕ ====================

@bot.message_handler(commands=['vote'])
@bot.message_handler(func=lambda m: m.text == "🗳 Голосование")
def cmd_vote(message):
    user_id = message.from_user.id
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT vote FROM votes WHERE user_id = ? AND date = ?", (user_id, today))
    existing = c.fetchone()
    conn.close()
    event = get_todays_event_proposal()
    text = f"🗳 *Голосование*\n\n📅 {event['desc']}\n\n"
    active = get_active_event_text()
    if active:
        text += f"✅ Активно: {active}\n\n"
    if existing:
        text += f"Вы проголосовали: {existing[0].upper()}"
        bot.send_message(user_id, text, parse_mode='Markdown')
        return
    text += "Голосуем?"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ За", callback_data="vote_yes"))
    markup.add(types.InlineKeyboardButton("❌ Против", callback_data="vote_no"))
    bot.send_message(user_id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("vote_"))
def vote_callback(call):
    user_id = call.from_user.id
    vote = call.data.split("_")[1]
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO votes (user_id, event_type, vote, date) VALUES (?, ?, ?, ?)", (user_id, "daily", vote, today))
        conn.commit()
    except sqlite3.IntegrityError:
        bot.answer_callback_query(call.id, "Уже голосовали!")
        conn.close()
        return
    conn.close()
    if check_vote_result():
        event = get_todays_event_proposal()
        activate_event(event["event_type"], event["effect"])
        bot.answer_callback_query(call.id, f"Событие активировано: {event['desc']}")
        bot.edit_message_text(f"✅ *Активировано!*\n{event['desc']}", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    else:
        bot.answer_callback_query(call.id, "Голос принят!")
        bot.edit_message_text(f"🗳 Голос: {vote.upper()}\nНужно 3+ голоса.", call.message.chat.id, call.message.message_id, parse_mode='Markdown')

# ==================== БРАКИ ====================

@bot.message_handler(commands=['marry'])
@bot.message_handler(func=lambda m: m.text == "💍 Брак")
def menu_marry(message):
    user_id = message.from_user.id
    seals = get_player_seals(user_id)
    if not seals:
        bot.send_message(user_id, "У вас нет тюленей!")
        return
    if get_seal_count(user_id) >= MAX_SEALS:
        bot.send_message(user_id, f"Максимум {MAX_SEALS} тюленей!")
        return
    markup = types.InlineKeyboardMarkup()
    for s in seals:
        markup.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"marrysel_{s[0]}"))
    bot.send_message(user_id, "Выберите тюленя для брака:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("marrysel_"))
def marry_select(call):
    seal_id = int(call.data.split("_")[1])
    bot.send_message(call.from_user.id, "Введите ID или @username партнёра:")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, lambda m: marry_get_partner(m, seal_id))

def marry_get_partner(message, seal1_id):
    user_id = message.from_user.id
    text = message.text.strip()
    if text.startswith("@"):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id FROM players WHERE username = ?", (text[1:],))
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
            bot.send_message(user_id, "Неверный формат!")
            return
    if partner_id == user_id:
        bot.send_message(user_id, "Нельзя с самим собой!")
        return
    partner_seals = get_player_seals(partner_id)
    if not partner_seals:
        bot.send_message(user_id, "У игрока нет тюленей!")
        return
    markup = types.InlineKeyboardMarkup()
    for s in partner_seals:
        markup.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})", callback_data=f"marrydo_{seal1_id}_{s[0]}_{partner_id}"))
    bot.send_message(user_id, "Выберите тюленя партнёра:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("marrydo_"))
def marry_do(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    seal1_id, seal2_id, partner_id = int(parts[1]), int(parts[2]), int(parts[3])
    seal1, seal2 = get_seal(seal1_id), get_seal(seal2_id)
    if not seal1 or not seal2:
        bot.answer_callback_query(call.id, "Тюлень не найден!")
        return
    if get_seal_count(user_id) >= MAX_SEALS:
        bot.answer_callback_query(call.id, f"Максимум {MAX_SEALS} тюленей!")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM marriages WHERE (seal1_id=? AND seal2_id=?) OR (seal1_id=? AND seal2_id=?)", (seal1_id, seal2_id, seal2_id, seal1_id))
    if c.fetchone():
        bot.answer_callback_query(call.id, "Уже в браке!")
        conn.close()
        return
    c.execute("INSERT INTO marriages (seal1_id, seal2_id, player1_id, player2_id, created_at) VALUES (?,?,?,?,?)", (seal1_id, seal2_id, user_id, partner_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    msg = f"💍 Брак! {seal1[2]} ❤️ {seal2[2]}\n"
    if random.random() < 0.5:
        baby_name = random.choice(["Малыш", "Кроха", "Пузырь", "Лапик", "Шлёпик", "Ням"])
        baby_str = (seal1[7] + seal2[7]) // 4 + random.randint(1, 3)
        baby_def = (seal1[8] + seal2[8]) // 4 + random.randint(0, 2)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO seals (owner_id, name, health, max_health, mood, satiety, strength, defense, level, exp, is_baby, born_at) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)", (user_id, baby_name, 60, 60, 70, 70, baby_str, baby_def, 1, 0, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        msg += f"🍼 Тюленёнок — {baby_name}! Сила: {baby_str}, Защита: {baby_def}"
    else:
        msg += "Тюленёнок не появился..."
    bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

# ==================== ЕЖЕДНЕВНЫЕ ЗАДАНИЯ ====================

QUEST_TEMPLATES = [
    {"type": "play", "target": 3, "reward": 30, "desc": "Поиграть 3 раза"},
    {"type": "feed", "target": 3, "reward": 30, "desc": "Покормить 3 раза"},
    {"type": "battle", "target": 1, "reward": 40, "desc": "Победить 1 босса"},
    {"type": "dungeon", "target": 1, "reward": 50, "desc": "Пройти 1 подземелье"},
    {"type": "shop", "target": 1, "reward": 20, "desc": "Купить 1 предмет"},
    {"type": "work", "target": 1, "reward": 35, "desc": "Отправить на работу"},
    {"type": "craft", "target": 1, "reward": 25, "desc": "Скрафтить 1 предмет"},
    {"type": "fish", "target": 1, "reward": 25, "desc": "Поймать 1 рыбу"},
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
    for q in random.sample(QUEST_TEMPLATES, 3):
        c.execute("INSERT INTO daily_quests (user_id, quest_type, quest_target, quest_progress, quest_reward, date, claimed) VALUES (?,?,?,?,0,?,?,0)", (user_id, q["type"], q["target"], q["reward"], today))
    conn.commit()
    conn.close()

def update_quest_progress(user_id, quest_type, amount):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT quest_id, quest_progress, quest_target FROM daily_quests WHERE user_id = ? AND quest_type = ? AND date = ? AND claimed = 0", (user_id, quest_type, today))
    for quest_id, progress, target in c.fetchall():
        if progress < target:
            c.execute("UPDATE daily_quests SET quest_progress = ? WHERE quest_id = ?", (min(target, progress + amount), quest_id))
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

@bot.message_handler(commands=['quests'])
@bot.message_handler(func=lambda m: m.text == "📋 Задания")
def menu_quests(message):
    user_id = message.from_user.id
    generate_daily_quests(user_id)
    quests = get_daily_quests(user_id)
    if not quests:
        bot.send_message(user_id, "Задания не сгенерированы.")
        return
    text = "📋 *Ежедневные задания*\n\n"
    markup = types.InlineKeyboardMarkup()
    quest_descs = {q["type"]: q["desc"] for q in QUEST_TEMPLATES}
    for q in quests:
        qid, _, qtype, qtarget, qprogress, qreward, _, claimed = q
        desc = quest_descs.get(qtype, qtype)
        status = f"{qprogress}/{qtarget}"
        if claimed:
            text += f"  ✅ {desc} — {status} (🐟{qreward}) — получено\n"
        elif qprogress >= qtarget:
            text += f"  🎁 {desc} — {status} (🐟{qreward}) — готово!\n"
            markup.add(types.InlineKeyboardButton(f"Забрать 🐟{qreward}", callback_data=f"qclaim_{qid}"))
        else:
            text += f"  ⬜ {desc} — {status} (🐟{qreward})\n"
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
        bot.answer_callback_query(call.id, "Уже получено!")
        conn.close()
        return
    if row[4] < row[3]:
        bot.answer_callback_query(call.id, "Не выполнено!")
        conn.close()
        return
    c.execute("UPDATE daily_quests SET claimed = 1 WHERE quest_id = ?", (quest_id,))
    conn.commit()
    conn.close()
    add_fishnets(user_id, row[5])
    bot.answer_callback_query(call.id, f"Получено 🐟{row[5]}!")

# ==================== ФОНОВЫЕ ПОТОКИ ====================

def stats_decay():
    while True:
        time.sleep(3600)
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            c = conn.cursor()
            c.execute("SELECT seal_id, health, mood, satiety FROM seals")
            for seal_id, hp, mood, satiety in c.fetchall():
                new_mood = max(0, mood - random.randint(3, 8))
                new_satiety = max(0, satiety - random.randint(5, 10))
                new_hp = max(1, hp - random.randint(3, 8)) if new_satiety < 20 else hp
                c.execute("UPDATE seals SET mood=?, satiety=?, health=? WHERE seal_id=?", (new_mood, new_satiety, new_hp, seal_id))
            conn.commit()
            conn.close()
        except Exception:
            pass

def health_regen():
    while True:
        time.sleep(3600)
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            c = conn.cursor()
            c.execute("SELECT seal_id, health, max_health FROM seals WHERE health < max_health")
            for seal_id, hp, max_hp in c.fetchall():
                c.execute("UPDATE seals SET health = ? WHERE seal_id = ?", (min(max_hp, hp + 25), seal_id))
            conn.commit()
            conn.close()
        except Exception:
            pass

threading.Thread(target=stats_decay, daemon=True).start()
threading.Thread(target=health_regen, daemon=True).start()

# ==================== КОМАНДЫ В МЕНЮ ====================

bot.set_my_commands([
    types.BotCommand("start", "Регистрация / Главное меню"),
    types.BotCommand("help", "Справка по всем командам"),
    types.BotCommand("profile", "Профиль игрока"),
    types.BotCommand("gallery", "Галерея тюленей"),
    types.BotCommand("setphoto", "Установить фото тюленя"),
    types.BotCommand("shop", "Магазин"),
    types.BotCommand("craft", "Крафт оружия и брони"),
    types.BotCommand("trade", "Биржа предметов"),
    types.BotCommand("battle", "Бой с боссом"),
    types.BotCommand("dungeon", "Подземелье (5 этажей)"),
    types.BotCommand("work", "Отправить тюленя на работу"),
    types.BotCommand("fish", "Мини-игра Рыбалка"),
    types.BotCommand("vote", "Голосование за событие"),
    types.BotCommand("faction", "Фракции и репутация"),
    types.BotCommand("marry", "Брак тюленей (макс. 5)"),
    types.BotCommand("quests", "Ежедневные задания"),
    types.BotCommand("leaderboard", "Таблица лидеров"),
])

# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    print("Бот запущен! 🦭")
    bot.polling(none_stop=True)

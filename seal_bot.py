import telebot
from telebot import types
import sqlite3, random, threading, time, os, shutil, json
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
    c.execute("CREATE TABLE IF NOT EXISTS players (user_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, photo_path TEXT, fishnets INTEGER DEFAULT 100, faction TEXT, faction_rep INTEGER DEFAULT 0, fish_cooldown TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS seals (seal_id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, name TEXT, health INTEGER DEFAULT 100, max_health INTEGER DEFAULT 100, mood INTEGER DEFAULT 80, satiety INTEGER DEFAULT 80, strength INTEGER DEFAULT 10, defense INTEGER DEFAULT 5, level INTEGER DEFAULT 1, exp INTEGER DEFAULT 0, is_baby INTEGER DEFAULT 0, born_at TEXT, equipped_weapon TEXT, equipped_armor TEXT, equipped_helmet TEXT, equipped_shield TEXT, equipped_accessory TEXT, work_cooldown TEXT, play_cooldown TEXT, photo_path TEXT, work_cooldown_min INTEGER DEFAULT 0)")
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
         json.dumps({"item":"Компас мудреца","type":"accessory"}),200),
        (2,"Тайна глубин","Древняя табличка говорит о сокровище на дне океана.",
         json.dumps([{"type":"dungeon_complete","target":1,"desc":"Пройдите 1 подземелье полностью"},{"type":"reach_level","target":10,"desc":"Достигните 10 уровня"}]),
         json.dumps({"item":"Амулет глубин","type":"accessory"}),500),
        (3,"Король арены","Станьте легендой среди тюленей!",
         json.dumps([{"type":"duel_win","target":3,"desc":"Победите 3 игроков в дуэлях"},{"type":"battle_count","target":5,"desc":"Победите 5 боссов"}]),
         json.dumps({"item":"Корона чемпиона","type":"accessory"}),1000),
    ]
    c.executemany("INSERT OR REPLACE INTO quest_chains VALUES (?,?,?,?,?,?)", chains)

MIGRATIONS = [migration_1, migration_2]

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
SHOP_ITEMS = {
    "Апельсин 🍊":{"price":15,"type":"food","satiety":25,"mood":10},
    "Рыба 🐟":{"price":10,"type":"food","satiety":20,"mood":5},
    "Кальмар 🦑":{"price":25,"type":"food","satiety":35,"mood":15},
    "Мороженое 🍦":{"price":20,"type":"food","satiety":15,"mood":30},
    "Креветка 🦐":{"price":18,"type":"food","satiety":22,"mood":8},
    "Устрица 🦪":{"price":30,"type":"food","satiety":40,"mood":20},
    "Водоросли 🌿":{"price":8,"type":"food","satiety":15,"mood":3},
    "Аптечка 💊":{"price":100,"type":"medkit","heal":50},
    "Бантик 🎀":{"price":40,"type":"accessory"},"Шарф 🧣":{"price":35,"type":"accessory"},
    "Корона 👑":{"price":200,"type":"accessory"},"Очки 🕶️":{"price":50,"type":"accessory"},
    "Цветок 🌸":{"price":25,"type":"accessory"},"Морская звезда ⭐":{"price":60,"type":"accessory"},
    "Жемчужное ожерелье 🫧":{"price":120,"type":"accessory"},"Перо чайки 🪶":{"price":30,"type":"accessory"},
    "Радужный пояс 🌈":{"price":80,"type":"accessory"},
}
ITEM_BONUSES = {
    "Костяной меч 🗡️":{"str":5},"Акулий клык 🦷":{"str":8},"Трезубец 🔱":{"str":12},"Китовый клинок 🐋":{"str":15},
    "Чешуйчатая броня 🐟":{"def":5,"hp":10},"Панцирь краба 🦀":{"def":8,"hp":15},
    "Плетёная броня 🧵":{"def":10,"hp":25},"Кракеновый панцирь 🐙":{"def":15,"hp":40},
    "Шлем из ракушек 🐚":{"def":3,"hp":10},"Костяной шлем 💀":{"def":5,"hp":15},"Корона из зубов 👑":{"def":8,"hp":20},
    "Щит из чешуи 🐠":{"def":5},"Панцирный щит 🛡️":{"def":8},"Щит кракена 🦑":{"def":12},
}
ACCESSORY_BONUSES = {
    "Бантик 🎀":10,"Шарф 🧣":8,"Корона 👑":20,"Очки 🕶️":7,"Цветок 🌸":5,
    "Компас мудреца 🧭":25,"Амулет глубин 🌊":22,"Корона чемпиона 👑":30,
    "Морская звезда ⭐":12,"Жемчужное ожерелье 🫧":18,"Перо чайки 🪶":6,"Радужный пояс 🌈":14,
}
CRAFT_RECIPES = [
    {"name":"Костяной меч 🗡️","type":"weapon","resources":{"Акулий зуб 🦈":3}},
    {"name":"Акулий клык 🦷","type":"weapon","resources":{"Акулий зуб 🦈":5,"Чешуя 🐟":2}},
    {"name":"Трезубец 🔱","type":"weapon","resources":{"Щупальце 🐙":4,"Акулий зуб 🦈":3}},
    {"name":"Китовый клинок 🐋","type":"weapon","resources":{"Китовый ус 🐋":3,"Жемчуг 🫧":1}},
    {"name":"Чешуйчатая броня 🐟","type":"armor","resources":{"Чешуя 🐟":4}},
    {"name":"Панцирь краба 🦀","type":"armor","resources":{"Панцирь 🦀":3}},
    {"name":"Плетёная броня 🧵","type":"armor","resources":{"Щупальце 🐙":3,"Чешуя 🐟":2}},
    {"name":"Кракеновый панцирь 🐙","type":"armor","resources":{"Щупальце 🐙":5,"Жемчуг 🫧":1}},
    {"name":"Шлем из ракушек 🐚","type":"helmet","resources":{"Панцирь 🦀":3,"Чешуя 🐟":1}},
    {"name":"Костяной шлем 💀","type":"helmet","resources":{"Акулий зуб 🦈":3}},
    {"name":"Корона из зубов 👑","type":"helmet","resources":{"Акулий зуб 🦈":5,"Жемчуг 🫧":1}},
    {"name":"Щит из чешуи 🐠","type":"shield","resources":{"Чешуя 🐟":4,"Панцирь 🦀":1}},
    {"name":"Панцирный щит 🛡️","type":"shield","resources":{"Панцирь 🦀":4}},
    {"name":"Щит кракена 🦑","type":"shield","resources":{"Щупальце 🐙":3,"Панцирь 🦀":2}},
]
ITEM_TYPES = {}
for _n,_i in SHOP_ITEMS.items(): ITEM_TYPES[_n]=_i["type"]
for _r in CRAFT_RECIPES: ITEM_TYPES[_r["name"]]=_r["type"]
ITEM_TYPES.update({"Компас мудреца 🧭":"accessory","Амулет глубин 🌊":"accessory","Корона чемпиона 👑":"accessory"})
SEAL_SKILLS_POOL = [
    {"name":"Критический удар ⚡","effect":"crit_15","desc":"15% шанс двойного урона"},
    {"name":"Толстая кожа 🛡️","effect":"dmg_reduce_10","desc":"-10% получаемого урона"},
    {"name":"Вампиризм 🩸","effect":"lifesteal_5","desc":"Восстанавливает 5% урона"},
    {"name":"Уклонение 💨","effect":"dodge_10","desc":"10% шанс увернуться"},
    {"name":"Берсерк 😤","effect":"berserk","desc":"+50% урона при HP<30%"},
    {"name":"Регенерация 💚","effect":"regen","desc":"+5 HP/час"},
    {"name":"Шипы 🌵","effect":"thorns","desc":"Отражает 20% урона"},
    {"name":"Двойной удар ⚔️","effect":"double_strike","desc":"10% шанс 2 атаки"},
]
DUNGEON_MONSTERS = [
    {"name":"Фугу 🐡","hp":30,"str":8,"def":3,"drops":{"Жало 🐡":0.7}},
    {"name":"Креветка-ниндзя 🦐","hp":35,"str":9,"def":8,"drops":{"Панцирь 🦀":0.5,"Чешуя 🐟":0.3}},
    {"name":"Акула 🦈","hp":50,"str":12,"def":5,"drops":{"Акулий зуб 🦈":0.7}},
    {"name":"Морской змей 🐍","hp":60,"str":15,"def":6,"drops":{"Чешуя 🐟":0.7}},
    {"name":"Кракен 🐙","hp":80,"str":18,"def":8,"drops":{"Щупальце 🐙":0.7,"Жемчуг 🫧":0.1}},
    {"name":"Лобстер 🦞","hp":40,"str":10,"def":10,"drops":{"Панцирь 🦀":0.7}},
    {"name":"Кашалот 🐋","hp":120,"str":20,"def":12,"drops":{"Китовый ус 🐋":0.6}},
    {"name":"Электрический скат ⚡","hp":55,"str":14,"def":4,"drops":{"Чешуя 🐟":0.5,"Жало 🐡":0.3}},
    {"name":"Гигантская медуза 🪼","hp":45,"str":11,"def":3,"drops":{"Жало 🐡":0.6}},
    {"name":"Морской дьявол 😈","hp":90,"str":16,"def":9,"drops":{"Жемчуг 🫧":0.3,"Чешуя 🐟":0.4}},
]
BOSSES = [
    {"name":"Краб-босс 🦀","drops":{"Панцирь 🦀":0.8}},{"name":"Акула 🦈","drops":{"Акулий зуб 🦈":0.8}},
    {"name":"Осьминог 🐙","drops":{"Щупальце 🐙":0.8}},{"name":"Морской ёжик 🦔","drops":{"Жало 🐡":0.8}},
    {"name":"Кашалот 🐋","drops":{"Китовый ус 🐋":0.7}},{"name":"Морской змей 🐍","drops":{"Чешуя 🐟":0.8}},
    {"name":"Гигантский краб 🦀","drops":{"Панцирь 🦀":0.8,"Жемчуг 🫧":0.15}},
    {"name":"Электрический скат ⚡","drops":{"Чешуя 🐟":0.7,"Жало 🐡":0.3}},
    {"name":"Глубинный монстр 🌑","drops":{"Жемчуг 🫧":0.4,"Щупальце 🐙":0.5}},
    {"name":"Король креветок 🦐","drops":{"Панцирь 🦀":0.7,"Чешуя 🐟":0.3}},
]
CLAN_DUNGEON_MONSTERS = [
    {"name":"Страж глубин 🌊","hp":200,"str":25,"def":15},{"name":"Древний краб 🦀","hp":250,"str":30,"def":20},
    {"name":"Призрачная акула 👻","hp":300,"str":35,"def":18},{"name":"Ледяной кальмар 🧊","hp":350,"str":40,"def":25},
    {"name":"Гигантский спрут 🐙","hp":400,"str":45,"def":22},{"name":"Морской дракон 🐉","hp":500,"str":55,"def":30},
    {"name":"Бездонный левиафан 🐋","hp":600,"str":60,"def":35},{"name":"Крашеный кракен 🦑","hp":700,"str":70,"def":40},
    {"name":"Древний бог морей 🔱","hp":800,"str":80,"def":45},{"name":"Повелитель бездны 🌑","hp":1000,"str":100,"def":60},
]
JOBS = [
    {"name":"Рыболов 🎣","desc":"Ловить рыбу","reward_min":20,"reward_max":50,"cooldown_min":30,"mood_cost":5,"satiety_cost":10},
    {"name":"Почтальон 📬","desc":"Разносить почту","reward_min":30,"reward_max":60,"cooldown_min":45,"mood_cost":8,"satiety_cost":15},
    {"name":"Укротитель 🦭","desc":"Укрощать морских зверей","reward_min":50,"reward_max":100,"cooldown_min":60,"mood_cost":12,"satiety_cost":20},
    {"name":"Водолаз 🤿","desc":"Исследовать глубины","reward_min":40,"reward_max":80,"cooldown_min":50,"mood_cost":10,"satiety_cost":18},
    {"name":"Актёр 🎭","desc":"Выступать в шоу","reward_min":35,"reward_max":70,"cooldown_min":40,"mood_cost":6,"satiety_cost":12},
]
FISH_TYPES = [
    {"name":"Малёк 🐤","reward":(3,8),"correct":"Подсечь!"},{"name":"Окунь 🐟","reward":(8,15),"correct":"Подсечь!"},
    {"name":"Сёмга 🐠","reward":(15,25),"correct":"Ждать"},{"name":"Золотая рыбка ✨","reward":(30,50),"correct":"Ждать"},
    {"name":"Краб 🦀","reward":(10,20),"correct":"Отпустить"},
]
DAILY_EVENTS = [
    {"event_type":"exp_boost","effect":"1.5","desc":"+50% к опыту!"},
    {"event_type":"shop_discount","effect":"0.2","desc":"Скидки 20% в магазине!"},
    {"event_type":"fishing_bonus","effect":"2.0","desc":"x2 рыбнеток за рыбалку!"},
]
FACTIONS = {
    "hunters":{"name":"Стая охотников 🎯","desc":"Бонус за бои"},
    "fashion":{"name":"Клуб модников 💅","desc":"Бонус к настроению"},
    "explorers":{"name":"Гильдия исследователей 🧭","desc":"Бонус к опыту"},
}
RANDOM_ENCOUNTERS = [
    {"name":"Сундук на берегу! 📦","type":"item","chance":0.12,"items":["Чешуя 🐟","Панцирь 🦀","Акулий зуб 🦈","Жемчуг 🫧"]},
    {"name":"Злой краб! 🦀","type":"battle","chance":0.10,"mood_cost":10,"satiety_cost":10,"drop":{"Панцирь 🦀":0.5}},
    {"name":"Дружелюбный дельфин 🐬","type":"hint","chance":0.08,"fishnet_reward":(10,30)},
    {"name":"Затонувший корабль 🚢","type":"fishnets","chance":0.06,"fishnet_reward":(30,80)},
]
QUEST_TEMPLATES = [
    {"type":"play","target":3,"reward":30,"desc":"Поиграть 3 раза"},{"type":"feed","target":3,"reward":30,"desc":"Покормить 3 раза"},
    {"type":"battle","target":1,"reward":40,"desc":"Победить 1 босса"},{"type":"dungeon","target":1,"reward":50,"desc":"Пройти 1 подземелье"},
    {"type":"shop","target":1,"reward":20,"desc":"Купить 1 предмет"},{"type":"work","target":1,"reward":35,"desc":"Отправить на работу"},
    {"type":"craft","target":1,"reward":25,"desc":"Скрафтить 1 предмет"},{"type":"fish","target":1,"reward":25,"desc":"Поймать 1 рыбу"},
]
CLAN_EMOJIS = ["🦭","🐋","🦈","🐙","🦀","🦐","🦑","🐬","🐳","🐢"]

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
# seals: 0=id,1=owner,2=name,3=hp,4=max_hp,5=mood,6=satiety,7=str,8=def,9=lvl,10=exp,
#   11=baby,12=born,13=wep,14=arm,15=helm,16=shield,17=acc,18=work_cd,19=play_cd,20=photo,21=work_cd_min
# players: 0=uid,1=username,2=display,3=photo,4=fishnets,5=faction,6=rep,7=fish_cd

def get_player(uid):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT * FROM players WHERE user_id=?",(uid,));r=c.fetchone();conn.close();return r

def get_seal(sid):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT * FROM seals WHERE seal_id=?",(sid,));r=c.fetchone();conn.close();return r

def get_player_seals(uid):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT * FROM seals WHERE owner_id=?",(uid,));r=c.fetchall();conn.close();return r

def get_seal_count(uid):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT COUNT(*) FROM seals WHERE owner_id=?",(uid,));r=c.fetchone();conn.close();return r[0] if r else 0

def update_seal(sid, **kw):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    s=", ".join([f"{k}=?" for k in kw]);v=list(kw.values())+[sid]
    c.execute(f"UPDATE seals SET {s} WHERE seal_id=?",v);conn.commit();conn.close()

def update_player(uid, **kw):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    s=", ".join([f"{k}=?" for k in kw]);v=list(kw.values())+[uid]
    c.execute(f"UPDATE players SET {s} WHERE user_id=?",v);conn.commit();conn.close()

def add_fishnets(uid,amt):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("UPDATE players SET fishnets=fishnets+? WHERE user_id=?",(amt,uid));conn.commit();conn.close()

def get_fishnets(uid):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT fishnets FROM players WHERE user_id=?",(uid,));r=c.fetchone();conn.close();return r[0] if r else 0

def add_to_inv(uid,name,t,q=1):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT * FROM inventory WHERE user_id=? AND item_name=?",(uid,name));r=c.fetchone()
    if r: c.execute("UPDATE inventory SET quantity=quantity+? WHERE user_id=? AND item_name=?",(q,uid,name))
    else: c.execute("INSERT INTO inventory (user_id,item_name,item_type,quantity) VALUES (?,?,?,?)",(uid,name,t,q))
    conn.commit();conn.close()

def get_inv(uid):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT * FROM inventory WHERE user_id=? AND quantity>0",(uid,));r=c.fetchall();conn.close();return r

def get_item_qty(uid,name):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT quantity FROM inventory WHERE user_id=? AND item_name=?",(uid,name));r=c.fetchone();conn.close();return r[0] if r else 0

def remove_from_inv(uid,name,q=1):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT quantity FROM inventory WHERE user_id=? AND item_name=?",(uid,name));r=c.fetchone()
    if r:
        nq=r[0]-q
        if nq<=0: c.execute("DELETE FROM inventory WHERE user_id=? AND item_name=?",(uid,name))
        else: c.execute("UPDATE inventory SET quantity=? WHERE user_id=? AND item_name=?",(nq,uid,name))
        conn.commit()
    conn.close()

def exp_for_level(lvl): return lvl*100+(lvl-1)*50

def get_exp_mult():
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT effect FROM active_events WHERE active=1 AND event_type='exp_boost' AND expires_at>?",(datetime.now().isoformat(),))
    r=c.fetchone();conn.close();return float(r[0]) if r else 1.0

def get_shop_disc():
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT effect FROM active_events WHERE active=1 AND event_type='shop_discount' AND expires_at>?",(datetime.now().isoformat(),))
    r=c.fetchone();conn.close();return float(r[0]) if r else 0.0

def get_fish_bonus():
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT effect FROM active_events WHERE active=1 AND event_type='fishing_bonus' AND expires_at>?",(datetime.now().isoformat(),))
    r=c.fetchone();conn.close();return float(r[0]) if r else 1.0

def get_seal_skills(sid):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT skill_name,skill_effect FROM seal_skills WHERE seal_id=?",(sid,));r=c.fetchall();conn.close()
    return [{"name":row[0],"effect":row[1]} for row in r]

def uid_owner(sid):
    seal=get_seal(sid);return seal[1] if seal else 0

def check_levelup(sid):
    results=[]
    while True:
        seal=get_seal(sid)
        if not seal: break
        lvl,exp=seal[9],seal[10];needed=exp_for_level(lvl)
        if exp>=needed:
            nl=lvl+1;ne=exp-needed
            update_seal(sid,level=nl,exp=ne,strength=seal[7]+random.randint(2,5),
                       defense=seal[8]+random.randint(1,3),
                       max_health=seal[4]+random.randint(10,20),
                       health=seal[4]+random.randint(10,20))
            results.append(nl)
            if nl%5==0:
                skill=random.choice(SEAL_SKILLS_POOL)
                conn=sqlite3.connect(DB_PATH);c=conn.cursor()
                c.execute("INSERT INTO seal_skills (seal_id,skill_name,skill_effect,acquired_at) VALUES (?,?,?,?)",
                          (sid,skill["name"],skill["effect"],datetime.now().isoformat()))
                conn.commit();conn.close()
            uid=uid_owner(sid);update_quest_chain(uid,"reach_level",nl)
        else: break
    return results[-1] if results else False

def get_effective_stats(sid):
    seal=get_seal(sid)
    if not seal: return 0,0,0
    bs,bd,bh=seal[7],seal[8],seal[4];sb=db=hb=0
    for slot in [seal[13],seal[14],seal[15],seal[16]]:
        if slot and slot in ITEM_BONUSES:
            b=ITEM_BONUSES[slot];sb+=b.get("str",0);db+=b.get("def",0);hb+=b.get("hp",0)
    return bs+sb,bd+db,bh+hb

def get_mood_bonus(sid):
    seal=get_seal(sid);return ACCESSORY_BONUSES.get(seal[17],0) if seal else 0

def can_craft(uid,recipe):
    return all(get_item_qty(uid,r)>=a for r,a in recipe["resources"].items())

def get_faction_disc(uid):
    p=get_player(uid)
    if not p or not p[5]: return 0.0
    rep=p[6]
    if rep>=100: return 0.30
    elif rep>=50: return 0.15
    elif rep>=20: return 0.05
    return 0.0

def add_faction_rep(uid,amt):
    p=get_player(uid)
    if not p or not p[5]: return
    update_player(uid,faction_rep=p[6]+amt)

def get_dungeon_monster(floor):
    idx=(floor-1)%len(DUNGEON_MONSTERS);m=DUNGEON_MONSTERS[idx].copy()
    m["hp"]+=floor*15;m["str"]+=floor*3;m["def"]+=floor*2;return m

def process_drops(uid,drops):
    d=[]
    for res,ch in drops.items():
        if random.random()<ch:
            q=random.randint(1,2);add_to_inv(uid,res,"resource",q);d.append(f"{res} x{q}")
    return d

def get_married_ids():
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT seal1_id FROM marriages UNION SELECT seal2_id FROM marriages")
    ids=set(r[0] for r in c.fetchall());conn.close();return ids

def get_seal_status(seal,married):
    if seal[11]==1: return "🍼"
    if seal[3]<=0: return "💀"
    if seal[5]<30 or seal[6]<20: return "😴"
    if seal[0] in married: return "❤️"
    wc=seal[18]
    if wc:
        try:
            cm=seal[21] if seal[21] else 30
            if datetime.now()-datetime.fromisoformat(wc)<timedelta(minutes=cm): return "💼"
        except: pass
    if seal[5]>=50 and seal[6]>=50: return "🎮"
    return "🦭"

def get_active_event_text():
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT event_type FROM active_events WHERE active=1 AND expires_at>?",(datetime.now().isoformat(),))
    r=c.fetchone();conn.close()
    if not r: return None
    for ev in DAILY_EVENTS:
        if ev["event_type"]==r[0]: return ev["desc"]
    return None

def get_todays_event():
    seed=int(date.today().strftime("%Y%m%d"));return random.Random(seed).choice(DAILY_EVENTS)

def check_vote_result():
    today=date.today().isoformat();conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT vote,COUNT(*) FROM votes WHERE date=? GROUP BY vote",(today,));rows=c.fetchall();conn.close()
    y=n=0
    for v,cnt in rows:
        if v=="yes": y=cnt
        elif v=="no": n=cnt
    return (y+n)>=3 and y>n

def activate_event(et,eff):
    exp=datetime.now()+timedelta(hours=24);conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("UPDATE active_events SET active=0 WHERE active=1")
    c.execute("INSERT INTO active_events (event_type,effect,expires_at,active) VALUES (?,?,?,1)",(et,eff,exp.isoformat()))
    conn.commit();conn.close()

def get_quest_chains():
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT * FROM quest_chains");r=c.fetchall();conn.close();return r

def get_player_chain(uid,chain_id):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT * FROM player_quest_chains WHERE user_id=? AND chain_id=?",(uid,chain_id));r=c.fetchone();conn.close();return r

def update_quest_chain(uid,step_type,amount=1):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT id,chain_id,current_step,step_progress,completed FROM player_quest_chains WHERE user_id=? AND completed=0",(uid,))
    for pc_id,cid,cs,sp,comp in c.fetchall():
        c2=conn.cursor()
        c2.execute("SELECT steps_json FROM quest_chains WHERE chain_id=?",(cid,))
        chain=c2.fetchone()
        if not chain: continue
        steps=json.loads(chain[0])
        if cs<len(steps) and steps[cs]["type"]==step_type:
            ns=sp+1
            if ns>=steps[cs]["target"]:
                ns=0;cs2=cs+1
                if cs2>=len(steps):
                    c2.execute("UPDATE player_quest_chains SET completed=1 WHERE id=?",(pc_id,))
                else:
                    c2.execute("UPDATE player_quest_chains SET current_step=?,step_progress=0 WHERE id=?",(cs2,pc_id))
            else:
                c2.execute("UPDATE player_quest_chains SET step_progress=? WHERE id=?",(ns,pc_id))
    conn.commit();conn.close()

def get_clan_by_user(uid):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT clans.* FROM clans JOIN clan_members ON clans.clan_id=clan_members.clan_id WHERE clan_members.user_id=?",(uid,))
    r=c.fetchone();conn.close();return r

def get_clan_members(cid):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT user_id FROM clan_members WHERE clan_id=?",(cid,));r=c.fetchall();conn.close();return [row[0] for row in r]

def trigger_encounter(uid):
    enc=random.choice(RANDOM_ENCOUNTERS)
    if random.random()>enc["chance"]: return None
    msg=f"✨ Случайное событие!\n{enc['name']}\n"
    if enc["type"]=="item":
        item=random.choice(enc["items"]);add_to_inv(uid,item,"resource",1);msg+=f"Получен предмет: {item}!"
    elif enc["type"]=="fishnets":
        r=random.randint(*enc["fishnet_reward"]);add_fishnets(uid,r);msg+=f"Найдено 🐟{r}!"
    elif enc["type"]=="battle":
        seals=get_player_seals(uid)
        if seals:
            s=seals[0];update_seal(s[0],mood=max(0,s[5]-enc["mood_cost"]),satiety=max(0,s[6]-enc["satiety_cost"]))
            msg+=f"Тюлень потерял настроение и сытость!"
            if "drop" in enc:
                d=process_drops(uid,enc["drop"])
                if d: msg+=f"\nНо добыча: {', '.join(d)}"
    elif enc["type"]=="hint":
        r=random.randint(*enc["fishnet_reward"]);add_fishnets(uid,r);msg+=f"Дельфин подсказал секрет! 🐟{r}"
    return msg

def create_duel(cid,oid,csid):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("INSERT INTO duels (challenger_id,opponent_id,challenger_seal_id,status,created_at) VALUES (?,?,?,'pending',?)",
              (cid,oid,csid,datetime.now().isoformat()));conn.commit()
    did=c.lastrowid;conn.close();return did

def get_duel(did):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT * FROM duels WHERE duel_id=?",(did,));r=c.fetchone();conn.close();return r

# ==================== ЕЖЕДНЕВНЫЕ ЗАДАНИЯ (ОТДЕЛЬНО ОТ ЦЕПОЧЕК) ====================
def generate_daily_quests(uid):
    today=date.today().isoformat();conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT * FROM daily_quests WHERE user_id=? AND date=?",(uid,today))
    if c.fetchall(): conn.close();return
    c.execute("DELETE FROM daily_quests WHERE user_id=? AND date!=?",(uid,today))
    for q in random.sample(QUEST_TEMPLATES,3):
        c.execute("INSERT INTO daily_quests (user_id,quest_type,quest_target,quest_progress,quest_reward,date,claimed) VALUES (?,?,?,?,0,?,0)",
                  (uid,q["type"],q["target"],q["reward"],today))
    conn.commit();conn.close()

def update_quest_progress(uid,qt,amt=1):
    today=date.today().isoformat();conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT quest_id,quest_progress,quest_target FROM daily_quests WHERE user_id=? AND quest_type=? AND date=? AND claimed=0",(uid,qt,today))
    for qid,prog,targ in c.fetchall():
        if prog<targ: c.execute("UPDATE daily_quests SET quest_progress=? WHERE quest_id=?",(min(targ,prog+amt),qid))
    conn.commit();conn.close()

def get_daily_quests(uid):
    today=date.today().isoformat();conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT * FROM daily_quests WHERE user_id=? AND date=?",(uid,today));r=c.fetchall();conn.close();return r
# ==================== ОБРАБОТЧИКИ ====================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid=message.from_user.id;uname=message.from_user.username or message.from_user.first_name
    p=get_player(uid)
    if not p:
        conn=sqlite3.connect(DB_PATH);c=conn.cursor()
        c.execute("INSERT INTO players (user_id,username,display_name,fishnets) VALUES (?,?,?,100)",(uid,uname,uname))
        conn.commit();conn.close()
        sn=random.choice(["Никифор","Плюха","Шлёпа","Бубль","Тюня","Фрэнк","Сэм"])
        conn=sqlite3.connect(DB_PATH);c=conn.cursor()
        c.execute("INSERT INTO seals (owner_id,name,health,max_health,mood,satiety,strength,defense,level,exp) VALUES (?,?,100,100,80,80,10,5,1,0)",(uid,sn))
        conn.commit();conn.close()
        bot.send_message(uid,f"Добро пожаловать в Мир Тюленей! 🦭\n\nТюлень {sn} и 100 рыбнеток 🐟 ваши!")
    else:
        bot.send_message(uid,"С возвращением! 🦭")
    show_main_menu(uid)

@bot.message_handler(commands=['help'])
def cmd_help(message):
    uid=message.from_user.id
    t=("🦭 *Справка*\n\n*Основные:*\n/start /help /profile /gallery /setphoto /leaderboard\n"
       "/inventory — инвентарь и ресурсы\n\n"
       "*Тюлень:*\n🦭 Мой тюлень — карточка (навыки, кормить, играть, лечить)\n\n"
       "*Экономика:*\n/shop /craft /trade — биржа\n\n"
       "*Сражения:*\n/battle /dungeon /work /duel — PvP-дуэли\n\n"
       "*Активности:*\n/fish /vote /faction /marry /quests\n"
       "/questchain — квестовые цепочки\n"
       "/clan — кланы и клановое подземелье\n\n"
       "*Регенерация:* +25 HP/час | Навык каждые 5 уровней")
    bot.send_message(uid,t,parse_mode='Markdown');show_main_menu(uid)

def show_main_menu(uid):
    m=types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add(types.KeyboardButton("🦭 Мой тюлень"),types.KeyboardButton("👤 Профиль"))
    m.add(types.KeyboardButton("🎒 Инвентарь"),types.KeyboardButton("🛒 Магазин"))
    m.add(types.KeyboardButton("⚔️ Бой"),types.KeyboardButton("🏰 Подземелье"))
    m.add(types.KeyboardButton("💼 Работа"),types.KeyboardButton("🔨 Крафт"))
    m.add(types.KeyboardButton("📋 Задания"),types.KeyboardButton("💍 Брак"))
    m.add(types.KeyboardButton("🎣 Рыбалка"),types.KeyboardButton("🏆 Лидеры"))
    m.add(types.KeyboardButton("📦 Биржа"),types.KeyboardButton("🏛 Фракции"))
    m.add(types.KeyboardButton("🤺 Дуэль"),types.KeyboardButton("📚 Цепочки"))
    m.add(types.KeyboardButton("🐋 Клан"))
    bot.send_message(uid,"Выберите действие:",reply_markup=m)

# ==================== ПРОФИЛЬ ====================
@bot.message_handler(commands=['profile'])
@bot.message_handler(func=lambda m:m.text=="👤 Профиль")
def cmd_profile(message):
    uid=message.from_user.id;p=get_player(uid)
    if not p: bot.send_message(uid,"Напишите /start");return
    cnt=get_seal_count(uid);fn=p[4]
    fn2=FACTIONS[p[5]]["name"] if p[5] and p[5] in FACTIONS else "Нет"
    t=f"👤 *Ваш профиль*\n\n"
    t+=f"Тюленей: {cnt}/{MAX_SEALS}\n"
    t+=f"Рыбнетки: 🐟 {fn}\n"
    t+=f"Фракция: {fn2}"
    if p[5]: t+=f" (репутация: {p[6]})"
    t+="\n"
    clan=get_clan_by_user(uid)
    if clan: t+=f"Клан: {clan[2]} {clan[3]}\n"
    ev=get_active_event_text()
    if ev: t+=f"\n🎉 Активное событие: {ev}\n"
    seals=get_player_seals(uid)
    if seals:
        t+="\n*Ваши тюлени:*\n"
        for s in seals:
            es,ed,eh=get_effective_stats(s[0])
            skills=get_seal_skills(s[0])
            t+=f"\n🦭 *{s[2]}* (ур.{s[9]})\n"
            t+=f"  ❤️ Здоровье: {s[3]}/{s[4]} (с экип: {eh})\n"
            t+=f"  💪 Сила: {s[7]} (с экип: {es})\n"
            t+=f"  🛡️ Защита: {s[8]} (с экип: {ed})\n"
            t+=f"  😊 Настроение: {s[5]}\n"
            t+=f"  🍖 Сытость: {s[6]}\n"
            if skills: t+=f"  ✨ Навыки: {', '.join(sk['name'] for sk in skills)}\n"
    bot.send_message(uid,t,parse_mode='Markdown')

# ==================== ГАЛЕРЕЯ ====================
@bot.message_handler(commands=['gallery'])
def cmd_gallery(message):
    uid=message.from_user.id;seals=get_player_seals(uid)
    if not seals: bot.send_message(uid,"Нет тюленей! /start");return
    married=get_married_ids();fn=get_fishnets(uid)
    t=f"🖼 *Галерея*\n🐟 {fn}\n\n"
    for s in seals:
        st=get_seal_status(s,married);skills=get_seal_skills(s[0])
        t+=f"{st} *{s[2]}* — ур.{s[9]}\n  💪{s[7]} 🛡️{s[8]} 🍖{s[6]} ❤️{s[3]}/{s[4]}\n"
        if skills: t+=f"  Навыки: {', '.join(sk['name'] for sk in skills)}\n"
        t+="\n"
    bot.send_message(uid,t,parse_mode='Markdown')

# ==================== ЛИДЕРЫ ====================
@bot.message_handler(commands=['leaderboard'])
@bot.message_handler(func=lambda m:m.text=="🏆 Лидеры")
def cmd_leaderboard(message):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT seals.name,seals.level,players.username FROM seals JOIN players ON seals.owner_id=players.user_id ORDER BY seals.level DESC,seals.exp DESC LIMIT 20")
    rows=c.fetchall();conn.close()
    if not rows: bot.send_message(message.from_user.id,"Пусто!");return
    t="🏆 *Лидеры*\n\n";medals=["🥇","🥈","🥉"]
    for i,(n,l,u) in enumerate(rows):
        t+=f"{medals[i] if i<3 else str(i+1)+'.'} {n} — ур.{l} (@{u})\n"
    bot.send_message(message.from_user.id,t,parse_mode='Markdown')

# ==================== ИНВЕНТАРЬ ====================
@bot.message_handler(commands=['inventory'])
@bot.message_handler(func=lambda m:m.text=="🎒 Инвентарь")
def cmd_inventory(message):
    uid=message.from_user.id;inv=get_inv(uid)
    if not inv: bot.send_message(uid,"Инвентарь пуст!");return
    t="🎒 *Инвентарь*\n\n"
    cats={"food":"🍴 Еда","medkit":"💊 Медицина","weapon":"⚔️ Оружие","armor":"🛡️ Броня","helmet":"🪖 Шлемы","shield":"🛡️ Щиты","accessory":"🎀 Аксессуары","resource":"📦 Ресурсы"}
    grouped={}
    for item in inv: grouped.setdefault(item[3],[]).append(item)
    for cat,label in cats.items():
        items=grouped.get(cat,[])
        if items:
            t+=f"*{label}:*\n"
            for i in items: t+=f"  {i[2]} (x{i[4]})\n"
            t+="\n"
    bot.send_message(uid,t,parse_mode='Markdown')

# ==================== ФОТО ====================
@bot.message_handler(commands=['setphoto'])
def cmd_setphoto(message):
    uid=message.from_user.id;seals=get_player_seals(uid)
    if not seals: bot.send_message(uid,"Нет тюленей!");return
    m=types.InlineKeyboardMarkup()
    for s in seals: m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})",callback_data=f"sphoto_{s[0]}"))
    bot.send_message(uid,"📸 Выберите тюленя:",reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("sphoto_"))
def sphoto_sel(call):
    sid=int(call.data.split("_")[1])
    bot.send_message(call.from_user.id,"Отправьте фото:")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id,lambda m:proc_seal_photo(m,sid))

def proc_seal_photo(message,sid):
    uid=message.from_user.id
    if not message.photo: bot.send_message(uid,"Не фото!");return
    try:
        fi=bot.get_file(message.photo[-1].file_id);dl=bot.download_file(fi.file_path)
        os.makedirs("photos",exist_ok=True);p=f"photos/seal_{sid}.jpg"
        with open(p,'wb') as f: f.write(dl)
        update_seal(sid,photo_path=p);bot.send_message(uid,"✅ Фото обновлено!")
    except Exception as e: bot.send_message(uid,f"❌ {e}")

# ==================== ТЮЛЕНЬ ====================
@bot.message_handler(func=lambda m:m.text=="🦭 Мой тюлень")
def menu_seal(message):
    uid=message.from_user.id;seals=get_player_seals(uid)
    if not seals: bot.send_message(uid,"Нет тюленей! /start");return
    m=types.InlineKeyboardMarkup()
    for s in seals: m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]}){' 🍼' if s[11]==1 else ''}",callback_data=f"sinfo_{s[0]}"))
    bot.send_message(uid,"Выберите тюленя:",reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("sinfo_"))
def seal_selected(call,sid=None):
    if sid is None: sid=int(call.data.split("_")[1])
    seal=get_seal(sid)
    if not seal: bot.answer_callback_query(call.id,"Не найден!");return
    uid=call.from_user.id;fn=get_fishnets(uid)
    es,ed,eh=get_effective_stats(sid);mb=get_mood_bonus(sid)
    skills=get_seal_skills(sid)
    t=f"🦭 *{seal[2]}*\n🐟 {fn}\n\nУр:{seal[9]} (оп:{seal[10]}/{exp_for_level(seal[9])})\n"
    t+=f"❤️ {seal[3]}/{seal[4]}\n😊 {seal[5]}"
    if mb>0: t+=f" (+{mb})"
    t+=f"\n🍖 {seal[6]}\n💪 {seal[7]} (э:{es})\n🛡️ {seal[8]} (э:{ed})\n"
    if skills:
        t+=f"\n*Навыки:*\n"
        for sk in skills: t+=f"  {sk['name']}\n"
    eq=[]
    if seal[13]: eq.append(f"⚔️{seal[13]}")
    if seal[14]: eq.append(f"🛡️{seal[14]}")
    if seal[15]: eq.append(f"🪖{seal[15]}")
    if seal[16]: eq.append(f"🛡️{seal[16]}")
    if seal[17]: eq.append(f"🎀{seal[17]}")
    t+=f"\nЭкип: {', '.join(eq) if eq else 'нет'}\n"
    if seal[11]==1: t+="\n🍼 Тюленёнок!\n"
    m=types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🍖 Кормить",callback_data=f"feed_{sid}"),
          types.InlineKeyboardButton("🎾 Играть",callback_data=f"play_{sid}"))
    m.add(types.InlineKeyboardButton("💊 Лечить",callback_data=f"heal_{sid}"),
          types.InlineKeyboardButton("👕 Экип",callback_data=f"equip_{sid}"))
    m.add(types.InlineKeyboardButton("📸 Фото",callback_data=f"sphoto_{sid}"),
          types.InlineKeyboardButton("✏️ Имя",callback_data=f"rename_{sid}"))
    m.add(types.InlineKeyboardButton("◀️ Назад",callback_data="back_main"))
    cid=call.message.chat.id;mid=call.message.message_id;pp=seal[20]
    if pp and os.path.exists(pp):
        try: bot.delete_message(cid,mid)
        except: pass
        try:
            with open(pp,'rb') as f: bot.send_photo(cid,f,caption=t,reply_markup=m,parse_mode='Markdown')
        except: bot.send_message(cid,t,reply_markup=m,parse_mode='Markdown')
    else:
        try: bot.edit_message_text(t,cid,mid,reply_markup=m,parse_mode='Markdown')
        except: bot.send_message(cid,t,reply_markup=m,parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c:c.data.startswith("feed_"))
def seal_feed(call):
    uid=call.from_user.id;sid=int(call.data.split("_")[1]);inv=get_inv(uid)
    food=[i for i in inv if i[3]=="food"]
    if not food: bot.answer_callback_query(call.id,"Нет еды!");return
    m=types.InlineKeyboardMarkup()
    for i in food:
        info=SHOP_ITEMS.get(i[2],{})
        m.add(types.InlineKeyboardButton(f"{i[2]} (x{i[4]}) +{info.get('satiety',0)}",callback_data=f"dfd_{sid}_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️",callback_data=f"sinfo_{sid}"))
    bot.edit_message_text("Чем кормить?",call.message.chat.id,call.message.message_id,reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("dfd_"))
def seal_do_feed(call):
    uid=call.from_user.id;p=call.data.split("_");sid=int(p[2]);name="_".join(p[3:])
    info=SHOP_ITEMS.get(name)
    if not info: bot.answer_callback_query(call.id,"Не найден!");return
    seal=get_seal(sid)
    if not seal: return
    update_seal(sid,satiety=min(100,seal[6]+info["satiety"]),mood=min(100,seal[5]+info.get("mood",5)))
    remove_from_inv(uid,name)
    bot.answer_callback_query(call.id,f"{seal[2]} съел {name}!")
    update_quest_progress(uid,"feed",1);seal_selected(call,sid)

@bot.callback_query_handler(func=lambda c:c.data.startswith("heal_"))
def seal_heal(call):
    uid=call.from_user.id;sid=int(call.data.split("_")[1]);seal=get_seal(sid)
    if not seal: return
    if seal[3]>=seal[4]: bot.answer_callback_query(call.id,"Здоров!");return
    if get_item_qty(uid,"Аптечка 💊")<=0: bot.answer_callback_query(call.id,"Нет аптечек!");return
    h=SHOP_ITEMS["Аптечка 💊"]["heal"];update_seal(sid,health=min(seal[4],seal[3]+h))
    remove_from_inv(uid,"Аптечка 💊")
    bot.answer_callback_query(call.id,f"💊 +{h} HP!");seal_selected(call,sid)

@bot.callback_query_handler(func=lambda c:c.data.startswith("play_"))
def seal_play(call):
    uid=call.from_user.id;sid=int(call.data.split("_")[1]);seal=get_seal(sid)
    if not seal: return
    if seal[6]<10: bot.answer_callback_query(call.id,"Голоден!");return
    wc=seal[19]
    if wc:
        try:
            rem=timedelta(minutes=PLAY_COOLDOWN_MIN)-(datetime.now()-datetime.fromisoformat(wc))
            if rem.total_seconds()>0:
                bot.answer_callback_query(call.id,f"⏳ {int(rem.total_seconds()//60)}м {int(rem.total_seconds()%60)}с");return
        except: pass
    eg=int(random.randint(5,15)*get_exp_mult())
    update_seal(sid,mood=min(100,seal[5]+25),satiety=max(0,seal[6]-5),exp=seal[10]+eg,play_cooldown=datetime.now().isoformat())
    lv=check_levelup(sid);update_quest_progress(uid,"play",1)
    p=get_player(uid)
    if p and p[5]=="fashion": add_faction_rep(uid,1)
    msg=f"🎾 Поиграли! +25😊 +{eg}оп"
    if lv: msg+=f"\n🎉 Ур.{lv}!"
    enc=trigger_encounter(uid)
    if enc: msg+=f"\n\n{enc}"
    bot.answer_callback_query(call.id,msg);seal_selected(call,sid)

@bot.callback_query_handler(func=lambda c:c.data.startswith("rename_"))
def seal_rename(call):
    sid=int(call.data.split("_")[1])
    bot.send_message(call.from_user.id,"Новое имя:")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id,lambda m:proc_rename(m,sid))

def proc_rename(message,sid):
    nn=message.text.strip()
    if len(nn)>20: bot.send_message(message.from_user.id,"Слишком длинное!");return
    update_seal(sid,name=nn);bot.send_message(message.from_user.id,f"✅ {nn}!")

@bot.callback_query_handler(func=lambda c:c.data.startswith("equip_"))
def seal_equip_menu(call):
    uid=call.from_user.id;sid=int(call.data.split("_")[1]);inv=get_inv(uid)
    gt=("weapon","armor","helmet","shield","accessory")
    gi=[i for i in inv if ITEM_TYPES.get(i[3]) in gt or i[3] in gt]
    if not gi: bot.answer_callback_query(call.id,"Нет экипировки!");return
    m=types.InlineKeyboardMarkup()
    for i in gi: m.add(types.InlineKeyboardButton(f"{i[2]} (x{i[4]})",callback_data=f"deq_{sid}_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️",callback_data=f"sinfo_{sid}"))
    bot.edit_message_text("Что надеть?",call.message.chat.id,call.message.message_id,reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("deq_"))
def seal_do_equip(call):
    uid=call.from_user.id;p=call.data.split("_");sid=int(p[2]);name="_".join(p[3:])
    it=ITEM_TYPES.get(name)
    if not it: bot.answer_callback_query(call.id,"Не найден!");return
    seal=get_seal(sid)
    if not seal: return
    sm={"weapon":"equipped_weapon","armor":"equipped_armor","helmet":"equipped_helmet","shield":"equipped_shield","accessory":"equipped_accessory"}
    slot=sm.get(it)
    if not slot: bot.answer_callback_query(call.id,"Неизвестный тип!");return
    ci={"equipped_weapon":13,"equipped_armor":14,"equipped_helmet":15,"equipped_shield":16,"equipped_accessory":17}.get(slot)
    cv=seal[ci] if ci is not None else None
    if cv: add_to_inv(uid,cv,ITEM_TYPES.get(cv,"armor"),1)
    update_seal(sid,**{slot:name});remove_from_inv(uid,name)
    pl=get_player(uid)
    if pl and pl[5]=="fashion" and it=="accessory": add_faction_rep(uid,2)
    bot.answer_callback_query(call.id,f"Надето: {name}");seal_selected(call,sid)

@bot.callback_query_handler(func=lambda c:c.data=="back_main")
def back_to_main(call):
    show_main_menu(call.from_user.id)
    try: bot.edit_message_reply_markup(call.message.chat.id,call.message.message_id,reply_markup=None)
    except: pass

# ==================== МАГАЗИН ====================
@bot.message_handler(commands=['shop'])
@bot.message_handler(func=lambda m:m.text=="🛒 Магазин")
def menu_shop(message):
    uid=message.from_user.id;fn=get_fishnets(uid)
    td=max(get_shop_disc(),get_faction_disc(uid))
    t=f"🛒 *Магазин*\n🐟 {fn}\n"
    if td>0: t+=f"Скидка: {int(td*100)}%\n"
    t+="\n";m=types.InlineKeyboardMarkup(row_width=1)
    for n,i in SHOP_ITEMS.items():
        pr=int(i["price"]*(1-td))
        if i["type"]=="food": t+=f"  {n} — 🐟{pr} (+{i['satiety']})\n"
        elif i["type"]=="medkit": t+=f"  {n} — 🐟{pr} (+{i['heal']}HP)\n"
        elif i["type"]=="accessory": t+=f"  {n} — 🐟{pr} (+{ACCESSORY_BONUSES.get(n,0)}😊)\n"
        m.add(types.InlineKeyboardButton(f"{n} — 🐟{pr}",callback_data=f"buy_{n}"))
    bot.send_message(uid,t,parse_mode='Markdown',reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("buy_"))
def shop_buy(call):
    uid=call.from_user.id;name=call.data[4:];info=SHOP_ITEMS.get(name)
    if not info: bot.answer_callback_query(call.id,"Не найден!");return
    td=max(get_shop_disc(),get_faction_disc(uid));pr=int(info["price"]*(1-td))
    if get_fishnets(uid)<pr: bot.answer_callback_query(call.id,"Не хватает 🐟!");return
    add_fishnets(uid,-pr);add_to_inv(uid,name,info["type"])
    update_quest_progress(uid,"shop",1)
    bot.answer_callback_query(call.id,f"Куплено: {name} за 🐟{pr}!")

# ==================== КРАФТ ====================
@bot.message_handler(commands=['craft'])
@bot.message_handler(func=lambda m:m.text=="🔨 Крафт")
def menu_craft(message):
    uid=message.from_user.id;t="🔨 *Крафт*\n\n"
    for r in CRAFT_RECIPES:
        rt=", ".join([f"{r2} x{a}" for r2,a in r["resources"].items()])
        b=ITEM_BONUSES.get(r["name"],{});bt=""
        if "str" in b: bt+=f"💪+{b['str']} "
        if "def" in b: bt+=f"🛡️+{b['def']} "
        if "hp" in b: bt+=f"❤️+{b['hp']}"
        t+=f"{r['name']} ({bt.strip()})\n  {rt}\n\n"
    m=types.InlineKeyboardMarkup()
    for r in CRAFT_RECIPES:
        m.add(types.InlineKeyboardButton(f"{'✅' if can_craft(uid,r) else '❌'} {r['name']}",callback_data=f"cft_{r['name']}"))
    bot.send_message(uid,t,parse_mode='Markdown',reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("cft_"))
def craft_do(call):
    uid=call.from_user.id;name=call.data[4:]
    r=next((x for x in CRAFT_RECIPES if x["name"]==name),None)
    if not r: bot.answer_callback_query(call.id,"Не найден!");return
    if not can_craft(uid,r): bot.answer_callback_query(call.id,"Не хватает ресурсов!");return
    for res,amt in r["resources"].items(): remove_from_inv(uid,res,amt)
    add_to_inv(uid,name,r["type"]);update_quest_progress(uid,"craft",1)
    update_quest_chain(uid,"craft_item",1)
    pl=get_player(uid)
    if pl and pl[5]=="hunters": add_faction_rep(uid,1)
    bot.answer_callback_query(call.id,f"Скрафчено: {name}!")

# ==================== РАБОТА ====================
@bot.message_handler(commands=['work'])
@bot.message_handler(func=lambda m:m.text=="💼 Работа")
def menu_work(message):
    uid=message.from_user.id;seals=get_player_seals(uid)
    if not seals: bot.send_message(uid,"Нет тюленей!");return
    m=types.InlineKeyboardMarkup()
    for s in seals:
        if s[11]==1: continue
        m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})",callback_data=f"wsel_{s[0]}"))
    if not m.keyboard: bot.send_message(uid,"Все малыши!");return
    bot.send_message(uid,"💼 Выберите тюленя:",reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("wsel_"))
def work_sel(call):
    sid=int(call.data.split("_")[1]);seal=get_seal(sid)
    if not seal: return
    if seal[6]<20: bot.answer_callback_query(call.id,"Сытость<20!");return
    wc=seal[18]
    if wc:
        try:
            cm=seal[21] if seal[21] else 30
            rem=timedelta(minutes=cm)-(datetime.now()-datetime.fromisoformat(wc))
            if rem.total_seconds()>0:
                bot.answer_callback_query(call.id,f"⏳ {int(rem.total_seconds()//60)}м {int(rem.total_seconds()%60)}с");return
        except: pass
    t=f"💼 Работа для {seal[2]}:\n\n"
    for i,j in enumerate(JOBS): t+=f"{i+1}. {j['name']} — 🐟{j['reward_min']}-{j['reward_max']}, кд{j['cooldown_min']}м\n"
    m=types.InlineKeyboardMarkup()
    for i,j in enumerate(JOBS): m.add(types.InlineKeyboardButton(f"{j['name']} — 🐟{j['reward_min']}-{j['reward_max']}",callback_data=f"wdo_{sid}_{i}"))
    m.add(types.InlineKeyboardButton("◀️",callback_data="back_main"))
    bot.edit_message_text(t,call.message.chat.id,call.message.message_id,parse_mode='Markdown',reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("wdo_"))
def work_do(call):
    uid=call.from_user.id;p=call.data.split("_");sid=int(p[1]);ji=int(p[2])
    if ji<0 or ji>=len(JOBS): bot.answer_callback_query(call.id,"Не найдена!");return
    job=JOBS[ji];seal=get_seal(sid)
    if not seal or seal[6]<20 or seal[5]<10: bot.answer_callback_query(call.id,"Не может!");return
    wc=seal[18]
    if wc:
        try:
            rem=timedelta(minutes=job["cooldown_min"])-(datetime.now()-datetime.fromisoformat(wc))
            if rem.total_seconds()>0:
                bot.answer_callback_query(call.id,f"⏳ {int(rem.total_seconds()//60)}м {int(rem.total_seconds()%60)}с");return
        except: pass
    rw=random.randint(job["reward_min"],job["reward_max"])+seal[9]*3
    eg=int(random.randint(10,25)*get_exp_mult())
    update_seal(sid,mood=max(0,seal[5]-job["mood_cost"]),satiety=max(0,seal[6]-job["satiety_cost"]),exp=seal[10]+eg,work_cooldown=datetime.now().isoformat(),work_cooldown_min=job["cooldown_min"])
    add_fishnets(uid,rw);lv=check_levelup(sid)
    log=f"💼 {seal[2]}: {job['name']}\n💰 🐟{rw}\n📈 +{eg}оп\n⏳ кд{job['cooldown_min']}м"
    if lv: log+=f"\n🎉 Ур.{lv}!"
    enc=trigger_encounter(uid)
    if enc: log+=f"\n\n{enc}"
    update_quest_progress(uid,"work",1)
    bot.edit_message_text(log,call.message.chat.id,call.message.message_id,parse_mode='Markdown')

# ==================== БОИ ====================
@bot.message_handler(commands=['battle'])
@bot.message_handler(func=lambda m:m.text=="⚔️ Бой")
def menu_battle(message):
    uid=message.from_user.id;seals=get_player_seals(uid)
    if not seals: bot.send_message(uid,"Нет тюленей!");return
    m=types.InlineKeyboardMarkup()
    for s in seals:
        if s[11]==1: continue
        m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})",callback_data=f"bat_{s[0]}"))
    if not m.keyboard: bot.send_message(uid,"Все малыши!");return
    bot.send_message(uid,"Выберите тюленя:",reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("bat_"))
def do_battle(call):
    uid=call.from_user.id;sid=int(call.data.split("_")[1]);seal=get_seal(sid)
    if not seal or seal[3]<=0: bot.answer_callback_query(call.id,"Не может!");return
    es,ed,eh=get_effective_stats(sid);skills=get_seal_skills(sid)
    boss=random.choice(BOSSES);bn=boss["name"]
    bhp=random.randint(60,100)+seal[9]*10;bstr=random.randint(8,15)+seal[9]*2;bdef=random.randint(3,8)+seal[9]
    log=[f"⚔️ *{seal[2]} vs {bn}*\n",f"{seal[2]}: ❤️{eh} 💪{es} 🛡️{ed}",f"{bn}: ❤️{bhp} 💪{bstr} 🛡️{bdef}\n"]
    shp=seal[3]
    for rnd in range(1,21):
        if shp<=0 or bhp<=0: break
        dmg=es
        if any(s["effect"]=="berserk" for s in skills) and shp<eh*0.3: dmg=int(dmg*1.5)
        if random.random()<sum(0.15 for s in skills if s["effect"]=="crit_15"): dmg*=2;log.append("⚡ Крит!")
        dmg=max(1,dmg-bdef+random.randint(-3,5));bhp-=dmg
        log.append(f"Р{rnd}: {seal[2]} →{dmg} (босс {max(0,bhp)}❤️)")
        if bhp<=0: break
        if random.random()<sum(0.10 for s in skills if s["effect"]=="double_strike") and bhp>0:
            d2=max(1,es-bdef+random.randint(-3,5));bhp-=d2;log.append(f"⚔️ Двойной! →{d2}")
        if bhp<=0: break
        if random.random()<sum(0.10 for s in skills if s["effect"]=="dodge_10"):
            log.append("💨 Уклонение!");continue
        dm=max(1,bstr-ed+random.randint(-2,4))
        if any(s["effect"]=="dmg_reduce_10" for s in skills): dm=int(dm*0.9)
        shp-=dm;log.append(f"{bn} →{dm} ({seal[2]} {max(0,shp)}❤️)")
        ls=sum(1 for s in skills if s["effect"]=="lifesteal_5")
        if ls: heal=int(dm*0.05*ls);shp=min(eh,shp+heal)
        if any(s["effect"]=="thorns" for s in skills): bhp-=int(dm*0.2)
    if bhp<=0:
        rw=random.randint(20,50)+seal[9]*5;eg=int(random.randint(20,40)*get_exp_mult())
        add_fishnets(uid,rw);update_seal(sid,exp=seal[10]+eg,mood=min(100,seal[5]+15))
        lv=check_levelup(sid)
        log.append(f"\n🎉 *Победа!* 🐟{rw} +{eg}оп")
        if lv: log.append(f"📈 Ур.{lv}!")
        d=process_drops(uid,boss["drops"])
        if d: log.append(f"📦 {', '.join(d)}")
        update_quest_progress(uid,"battle",1);update_quest_chain(uid,"battle_count",1)
        pl=get_player(uid)
        if pl and pl[5]=="hunters": add_faction_rep(uid,2)
    elif shp<=0:
        update_seal(sid,health=max(1,seal[3]//4),mood=max(0,seal[5]-20))
        log.append("\n💀 *Поражение...*")
    else: log.append("\n🤝 Ничья!")
    bot.edit_message_text("\n".join(log),call.message.chat.id,call.message.message_id,parse_mode='Markdown')

# ==================== ПОДЗЕМЕЛЬЕ ====================
@bot.message_handler(commands=['dungeon'])
@bot.message_handler(func=lambda m:m.text=="🏰 Подземелье")
def menu_dungeon(message):
    uid=message.from_user.id;seals=get_player_seals(uid)
    if not seals: bot.send_message(uid,"Нет тюленей!");return
    m=types.InlineKeyboardMarkup()
    for s in seals:
        if s[11]==1: continue
        m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})",callback_data=f"ds_{s[0]}"))
    if not m.keyboard: bot.send_message(uid,"Все малыши!");return
    bot.send_message(uid,"🏰 Выберите тюленя (5 этажей):",reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("ds_"))
def dng_start(call):
    uid=call.from_user.id;sid=int(call.data.split("_")[1]);seal=get_seal(sid)
    if not seal: return
    if seal[3]<=20: bot.answer_callback_query(call.id,"HP<20!");return
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("DELETE FROM dungeon_runs WHERE user_id=?",(uid,))
    c.execute("INSERT INTO dungeon_runs (user_id,seal_id,current_floor,active) VALUES (?,?,1,1)",(uid,sid))
    conn.commit();conn.close();dng_floor(call,sid,1)

def dng_floor(call,sid,fl):
    seal=get_seal(sid);mon=get_dungeon_monster(fl);es,ed,_=get_effective_stats(sid)
    t=f"🏰 *Этаж {fl}/5*\n\n🦭 {seal[2]}: ❤️{seal[3]} 💪{es} 🛡️{ed}\n{mon['name']}: ❤️{mon['hp']} 💪{mon['str']} 🛡️{mon['def']}\n"
    m=types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("⚔️ Атаковать",callback_data=f"da_{sid}_{fl}"))
    m.add(types.InlineKeyboardButton("🏃 Сбежать",callback_data=f"df_{sid}_{fl}"))
    bot.edit_message_text(t,call.message.chat.id,call.message.message_id,parse_mode='Markdown',reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("da_"))
def dng_atk(call):
    uid=call.from_user.id;p=call.data.split("_");sid=int(p[2]);fl=int(p[3])
    seal=get_seal(sid)
    if not seal: return
    mon=get_dungeon_monster(fl);es,ed,_=get_effective_stats(sid);shp=seal[3]
    log=[f"⚔️ Этаж {fl}: {seal[2]} vs {mon['name']}"]
    while shp>0 and mon["hp"]>0:
        d=max(1,es-mon["def"]+random.randint(-2,5));mon["hp"]-=d
        log.append(f"{seal[2]} →{d} (монстр {max(0,mon['hp'])}❤️)")
        if mon["hp"]<=0: break
        dm=max(1,mon["str"]-ed+random.randint(-1,4));shp-=dm
        log.append(f"{mon['name']} →{dm} ({seal[2]} {max(0,shp)}❤️)")
    if mon["hp"]<=0:
        update_seal(sid,health=max(1,shp));log.append("\n✅ Повержен!")
        d=process_drops(uid,mon["drops"])
        if d: log.append(f"📦 {', '.join(d)}")
        if fl>=5:
            rw=100+fl*30;eg=int((50+fl*20)*get_exp_mult());add_fishnets(uid,rw)
            s=get_seal(sid);update_seal(sid,exp=s[10]+eg);lv=check_levelup(sid)
            log.append(f"🏆 *Пройдено!* 🐟{rw} +{eg}оп")
            if lv: log.append(f"📈 Ур.{lv}!")
            update_quest_progress(uid,"dungeon",1);update_quest_chain(uid,"dungeon_complete",1)
            update_quest_chain(uid,"dungeon_floor",fl)
            pl=get_player(uid)
            if pl and pl[5]=="explorers": add_faction_rep(uid,3)
            conn=sqlite3.connect(DB_PATH);c=conn.cursor()
            c.execute("UPDATE dungeon_runs SET active=0 WHERE user_id=?",(uid,));conn.commit();conn.close()
            bot.edit_message_text("\n".join(log),call.message.chat.id,call.message.message_id,parse_mode='Markdown')
        else:
            nf=fl+1;log.append(f"Открыт этаж {nf}!")
            m=types.InlineKeyboardMarkup()
            m.add(types.InlineKeyboardButton("➡️ Дальше",callback_data=f"dn_{sid}_{nf}"))
            m.add(types.InlineKeyboardButton("🏃 Выйти",callback_data=f"df_{sid}_{fl}"))
            bot.edit_message_text("\n".join(log),call.message.chat.id,call.message.message_id,parse_mode='Markdown',reply_markup=m)
    elif shp<=0:
        update_seal(sid,health=1,mood=max(0,seal[5]-30));log.append(f"\n💀 {seal[2]} пал...")
        conn=sqlite3.connect(DB_PATH);c=conn.cursor()
        c.execute("UPDATE dungeon_runs SET active=0 WHERE user_id=?",(uid,));conn.commit();conn.close()
        bot.edit_message_text("\n".join(log),call.message.chat.id,call.message.message_id,parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c:c.data.startswith("dn_"))
def dng_next(call):
    p=call.data.split("_");dng_floor(call,int(p[2]),int(p[3]))

@bot.callback_query_handler(func=lambda c:c.data.startswith("df_"))
def dng_flee(call):
    uid=call.from_user.id;conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("UPDATE dungeon_runs SET active=0 WHERE user_id=?",(uid,));conn.commit();conn.close()
    bot.edit_message_text("🏃 Сбежали.",call.message.chat.id,call.message.message_id)
# ==================== РЫБАЛКА ====================
@bot.message_handler(commands=['fish'])
@bot.message_handler(func=lambda m:m.text=="🎣 Рыбалка")
def cmd_fish(message):
    uid=message.from_user.id;p=get_player(uid)
    if not p: bot.send_message(uid,"/start");return
    fc=p[7]
    if fc:
        try:
            rem=timedelta(minutes=FISHING_COOLDOWN_MIN)-(datetime.now()-datetime.fromisoformat(fc))
            if rem.total_seconds()>0:
                bot.send_message(uid,f"⏳ {int(rem.total_seconds()//60)}м {int(rem.total_seconds()%60)}с");return
        except: pass
    fish=random.choice(FISH_TYPES);opts=["Подсечь!","Ждать","Отпустить"]
    opts.remove(fish["correct"]);opts.append(fish["correct"]);random.shuffle(opts)
    t=f"🎣 *Рыбалка!*\n\nПоклёвка: {fish['name']}\nУ вас 5 секунд!\n"
    m=types.InlineKeyboardMarkup(row_width=3)
    for o in opts: m.add(types.InlineKeyboardButton(o,callback_data=f"fh_{o}_{fish['name']}"))
    msg=bot.send_message(uid,t,parse_mode='Markdown',reply_markup=m)
    def timeout():
        time.sleep(5)
        try: bot.edit_message_text(f"⏰ Время! {fish['name']} уплыл.",msg.chat.id,msg.message_id)
        except: pass
        update_player(uid,fish_cooldown=datetime.now().isoformat())
    threading.Thread(target=timeout,daemon=True).start()

@bot.callback_query_handler(func=lambda c:c.data.startswith("fh_"))
def fish_cb(call):
    uid=call.from_user.id;p=call.data.split("_",2);act,fn=p[1],p[2]
    fish=next((f for f in FISH_TYPES if f["name"]==fn),None)
    if not fish: bot.answer_callback_query(call.id,"Истекла!");return
    bonus=get_fish_bonus();rm,rx=int(fish["reward"][0]*bonus),int(fish["reward"][1]*bonus)
    if act==fish["correct"]:
        rw=random.randint(rm,rx);add_fishnets(uid,rw)
        bot.edit_message_text(f"🎣 *Поймано!*\n\n{fn}!\n🐟{rw}",call.message.chat.id,call.message.message_id,parse_mode='Markdown')
        update_quest_progress(uid,"fish",1)
    else:
        bot.edit_message_text(f"💨 {fn} сорвался!\nНужно: {fish['correct']}",call.message.chat.id,call.message.message_id,parse_mode='Markdown')
    update_player(uid,fish_cooldown=datetime.now().isoformat())

# ==================== ДУЭЛИ ====================
@bot.message_handler(commands=['duel'])
@bot.message_handler(func=lambda m:m.text=="🤺 Дуэль")
def cmd_duel(message):
    uid=message.from_user.id;seals=get_player_seals(uid)
    if not seals: bot.send_message(uid,"Нет тюленей!");return
    m=types.InlineKeyboardMarkup()
    for s in seals:
        if s[11]==1: continue
        m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})",callback_data=f"dusel_{s[0]}"))
    if not m.keyboard: bot.send_message(uid,"Все малыши!");return
    bot.send_message(uid,"🤺 Выберите тюленя:",reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("dusel_"))
def duel_sel(call):
    sid=int(call.data.split("_")[1])
    bot.send_message(call.from_user.id,"Введите @username или ID соперника:")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id,lambda m:duel_target(m,sid))

def duel_target(message,sid):
    uid=message.from_user.id;txt=message.text.strip()
    if txt.startswith("@"):
        conn=sqlite3.connect(DB_PATH);c=conn.cursor()
        c.execute("SELECT user_id FROM players WHERE username=?",(txt[1:],));r=c.fetchone();conn.close()
        if not r: bot.send_message(uid,"Не найден!");return
        oid=r[0]
    else:
        try: oid=int(txt)
        except: bot.send_message(uid,"Неверный формат!");return
    if oid==uid: bot.send_message(uid,"Нельзя с собой!");return
    seal=get_seal(sid);did=create_duel(uid,oid,sid)
    bot.send_message(uid,"🤺 Вызов отправлен! Ожидайте ответа.")
    try:
        m2=types.InlineKeyboardMarkup()
        m2.add(types.InlineKeyboardButton("⚔️ Принять",callback_data=f"duac_{did}"),
               types.InlineKeyboardButton("❌ Отказать",callback_data=f"durj_{did}"))
        bot.send_message(oid,f"🤺 Вас вызвал на дуэль @{message.from_user.username}!\nТюлень: {seal[2]} (ур.{seal[9]})",reply_markup=m2)
    except: pass

@bot.callback_query_handler(func=lambda c:c.data.startswith("duac_"))
def duel_accept(call):
    uid=call.from_user.id;did=int(call.data.split("_")[1]);duel=get_duel(did)
    if not duel or duel[5]!='pending': bot.answer_callback_query(call.id,"Недоступна!");return
    if duel[2]!=uid: bot.answer_callback_query(call.id,"Не вам!");return
    seals=get_player_seals(uid)
    if not seals: bot.answer_callback_query(call.id,"Нет тюленей!");return
    m=types.InlineKeyboardMarkup()
    for s in seals:
        if s[11]==1: continue
        m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})",callback_data=f"duseal_{did}_{s[0]}"))
    bot.edit_message_text("Выберите тюленя:",call.message.chat.id,call.message.message_id,reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("duseal_"))
def duel_seal(call):
    uid=call.from_user.id;p=call.data.split("_");did=int(p[2]);osid=int(p[3])
    duel=get_duel(did)
    if not duel or duel[5]!='pending': bot.answer_callback_query(call.id,"Недоступна!");return
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("UPDATE duels SET status='active',opponent_seal_id=? WHERE duel_id=?",(osid,did))
    conn.commit();conn.close()
    csid=duel[3];cseal=get_seal(csid);oseal=get_seal(osid)
    if not cseal or not oseal: bot.answer_callback_query(call.id,"Тюлень не найден!");return
    ces,ced,ceh=get_effective_stats(csid);oes,oed,oeh=get_effective_stats(osid)
    csk=get_seal_skills(csid);osk=get_seal_skills(osid)
    chp=cseal[3];ohp=oseal[3]
    log=[f"🤺 *Дуэль: {cseal[2]} vs {oseal[2]}*\n",
         f"{cseal[2]}: ❤️{ceh} 💪{ces} 🛡️{ced}",f"{oseal[2]}: ❤️{oeh} 💪{oes} 🛡️{oed}\n"]
    rnd=0;rw=0
    while chp>0 and ohp>0:
        rnd+=1
        if rnd>15: break
        cd=ces
        if any(s["effect"]=="berserk" for s in csk) and chp<ceh*0.3: cd=int(cd*1.5)
        if random.random()<sum(0.15 for s in csk if s["effect"]=="crit_15"): cd*=2;log.append("⚡ Крит!")
        cd=max(1,cd-oed+random.randint(-3,5));ohp-=cd
        log.append(f"Р{rnd}: {cseal[2]} →{cd} ({oseal[2]} {max(0,ohp)}❤️)")
        if ohp<=0: break
        od=oes
        if any(s["effect"]=="berserk" for s in osk) and ohp<oeh*0.3: od=int(od*1.5)
        if random.random()<sum(0.15 for s in osk if s["effect"]=="crit_15"): od*=2;log.append("⚡ Крит в ответ!")
        od=max(1,od-ced+random.randint(-3,5));chp-=od
        log.append(f"{oseal[2]} →{od} ({cseal[2]} {max(0,chp)}❤️)")
    winner_id=0
    if ohp<=0:
        winner_id=duel[1];log.append(f"\n🎉 *{cseal[2]} победил!*")
        rw=min(get_fishnets(duel[2])//10,100);add_fishnets(duel[1],rw);add_fishnets(duel[2],-rw)
        log.append(f"💰 Награда: 🐟{rw}")
        update_quest_chain(duel[1],"duel_win",1)
    elif chp<=0:
        winner_id=duel[2];log.append(f"\n🎉 *{oseal[2]} победил!*")
        rw=min(get_fishnets(duel[1])//10,100);add_fishnets(duel[2],rw);add_fishnets(duel[1],-rw)
        log.append(f"💰 Награда: 🐟{rw}")
        update_quest_chain(duel[2],"duel_win",1)
    else: log.append("\n🤝 Ничья!")
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("UPDATE duels SET status='completed',winner_id=?,reward=? WHERE duel_id=?",(winner_id,rw,did))
    conn.commit();conn.close()
    bot.edit_message_text("\n".join(log),call.message.chat.id,call.message.message_id,parse_mode='Markdown')
    try: bot.send_message(duel[1] if duel[1]!=uid else duel[2],"\n".join(log),parse_mode='Markdown')
    except: pass

@bot.callback_query_handler(func=lambda c:c.data.startswith("durj_"))
def duel_reject(call):
    did=int(call.data.split("_")[1]);duel=get_duel(did)
    if not duel: bot.answer_callback_query(call.id,"Не найдена!");return
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("UPDATE duels SET status='rejected' WHERE duel_id=?",(did,));conn.commit();conn.close()
    bot.edit_message_text("❌ Дуэль отклонена.",call.message.chat.id,call.message.message_id)
    try: bot.send_message(duel[1],"❌ Ваш вызов отклонён.")
    except: pass

# ==================== КВЕСТОВЫЕ ЦЕПОЧКИ ====================
@bot.message_handler(commands=['questchain'])
@bot.message_handler(func=lambda m:m.text=="📚 Цепочки")
def cmd_questchain(message):
    uid=message.from_user.id;chains=get_quest_chains()
    t="📚 *Квестовые цепочки*\n\n";m=types.InlineKeyboardMarkup()
    for ch in chains:
        cid,name,story=ch[0],ch[1],ch[2]
        pc=get_player_chain(uid,cid)
        if pc and pc[5]==1: t+=f"✅ *{name}* — завершена\n"
        elif pc:
            steps=json.loads(ch[3]);step=steps[pc[3]]
            t+=f"🔄 *{name}* — шаг {pc[3]+1}/{len(steps)}\n  {step['desc']} ({pc[4]}/{step['target']})\n"
        else:
            t+=f"⬜ *{name}*\n  {story}\n"
            m.add(types.InlineKeyboardButton(f"Начать: {name}",callback_data=f"qcs_{cid}"))
        t+="\n"
    bot.send_message(uid,t,parse_mode='Markdown',reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("qcs_"))
def qc_start(call):
    uid=call.from_user.id;cid=int(call.data.split("_")[1])
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("INSERT OR IGNORE INTO player_quest_chains (user_id,chain_id,current_step,step_progress,completed) VALUES (?,?,0,0,0)",(uid,cid))
    conn.commit();conn.close()
    bot.answer_callback_query(call.id,"Цепочка начата!")
    cmd_questchain(call.message)

# ==================== БИРЖА ====================
@bot.message_handler(commands=['trade'])
@bot.message_handler(func=lambda m:m.text=="📦 Биржа")
def menu_trade(message):
    uid=message.from_user.id;m=types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("📤 Создать",callback_data="trc"))
    m.add(types.InlineKeyboardButton("📋 Активные",callback_data="trl_0"))
    m.add(types.InlineKeyboardButton("📦 Мои",callback_data="trm"))
    bot.send_message(uid,"📦 *Биржа*",parse_mode='Markdown',reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data=="trc")
def trade_create(call):
    uid=call.from_user.id;inv=get_inv(uid)
    if not inv: bot.answer_callback_query(call.id,"Пусто!");return
    m=types.InlineKeyboardMarkup()
    for i in inv:
        if i[3]=="resource": continue
        m.add(types.InlineKeyboardButton(f"{i[2]} (x{i[4]})",callback_data=f"trs_{i[2]}"))
    m.add(types.InlineKeyboardButton("◀️",callback_data="trb"))
    bot.edit_message_text("Что продать?",call.message.chat.id,call.message.message_id,reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("trs_"))
def trade_price(call):
    name=call.data[4:]
    bot.send_message(call.from_user.id,f"Цена для {name}?")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id,lambda m:tr_set(m,name))

def tr_set(message,name):
    uid=message.from_user.id
    try: pr=int(message.text.strip())
    except: bot.send_message(uid,"Число!");return
    if pr<1: bot.send_message(uid,">0!");return
    it=ITEM_TYPES.get(name,"misc")
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("INSERT INTO trade_offers (seller_id,item_name,item_type,price,created_at,active) VALUES (?,?,?,?,?,1)",(uid,name,it,pr,datetime.now().isoformat()))
    conn.commit();conn.close();remove_from_inv(uid,name)
    bot.send_message(uid,f"✅ {name} за 🐟{pr}!")

@bot.callback_query_handler(func=lambda c:c.data.startswith("trl_"))
def trade_list(call):
    uid=call.from_user.id;pg=int(call.data.split("_")[1])
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT offer_id,item_name,price FROM trade_offers WHERE active=1 AND seller_id!=? ORDER BY created_at DESC LIMIT 10 OFFSET ?",(uid,pg*10))
    offers=c.fetchall();conn.close()
    if not offers: bot.edit_message_text("Пусто.",call.message.chat.id,call.message.message_id);return
    t="📋 *Офферы*\n\n";m=types.InlineKeyboardMarkup()
    for oid,nm,pr in offers:
        t+=f"  {nm} — 🐟{pr}\n"
        m.add(types.InlineKeyboardButton(f"Купить {nm} — 🐟{pr}",callback_data=f"trbuy_{oid}"))
    nav=[]
    if pg>0: nav.append(types.InlineKeyboardButton("◀️",callback_data=f"trl_{pg-1}"))
    nav.append(types.InlineKeyboardButton("➡️",callback_data=f"trl_{pg+1}"))
    m.add(*nav);m.add(types.InlineKeyboardButton("◀️ В меню",callback_data="trb"))
    bot.edit_message_text(t,call.message.chat.id,call.message.message_id,parse_mode='Markdown',reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("trbuy_"))
def trade_buy(call):
    uid=call.from_user.id;oid=int(call.data.split("_")[1])
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT seller_id,item_name,item_type,price,active FROM trade_offers WHERE offer_id=?",(oid,));r=c.fetchone()
    if not r or not r[4]: bot.answer_callback_query(call.id,"Не найден!");conn.close();return
    sid,nm,it,pr,_=r
    if sid==uid: bot.answer_callback_query(call.id,"Своё!");conn.close();return
    if get_fishnets(uid)<pr: bot.answer_callback_query(call.id,"Не хватает 🐟!");conn.close();return
    add_fishnets(uid,-pr);add_fishnets(sid,pr);add_to_inv(uid,nm,it)
    c.execute("UPDATE trade_offers SET active=0 WHERE offer_id=?",(oid,));conn.commit();conn.close()
    bot.answer_callback_query(call.id,f"Куплено: {nm}!")
    try: bot.send_message(sid,f"💰 {nm} продан за 🐟{pr}!")
    except: pass

@bot.callback_query_handler(func=lambda c:c.data=="trm")
def trade_mine(call):
    uid=call.from_user.id;conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT offer_id,item_name,price,active FROM trade_offers WHERE seller_id=? ORDER BY created_at DESC",(uid,))
    offers=c.fetchall();conn.close()
    if not offers: bot.answer_callback_query(call.id,"Пусто!");return
    t="📦 *Мои офферы*\n\n";m=types.InlineKeyboardMarkup()
    for oid,nm,pr,act in offers:
        t+=f"  {'✅' if act else '❌'} {nm} — 🐟{pr}\n"
        if act: m.add(types.InlineKeyboardButton(f"Снять {nm}",callback_data=f"trcan_{oid}"))
    m.add(types.InlineKeyboardButton("◀️ В меню",callback_data="trb"))
    bot.edit_message_text(t,call.message.chat.id,call.message.message_id,parse_mode='Markdown',reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("trcan_"))
def trade_cancel(call):
    uid=call.from_user.id;oid=int(call.data.split("_")[1])
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT item_name,item_type,active FROM trade_offers WHERE offer_id=? AND seller_id=?",(oid,uid));r=c.fetchone()
    if not r or not r[2]: bot.answer_callback_query(call.id,"Не найден!");conn.close();return
    c.execute("UPDATE trade_offers SET active=0 WHERE offer_id=?",(oid,));conn.commit();conn.close()
    add_to_inv(uid,r[0],r[1]);bot.answer_callback_query(call.id,f"Снято: {r[0]}!")

@bot.callback_query_handler(func=lambda c:c.data=="trb")
def trade_back(call):
    m=types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("📤 Создать",callback_data="trc"))
    m.add(types.InlineKeyboardButton("📋 Активные",callback_data="trl_0"))
    m.add(types.InlineKeyboardButton("📦 Мои",callback_data="trm"))
    bot.edit_message_text("📦 *Биржа*",call.message.chat.id,call.message.message_id,parse_mode='Markdown',reply_markup=m)

# ==================== КЛАНЫ ====================
@bot.message_handler(commands=['clan'])
@bot.message_handler(func=lambda m:m.text=="🐋 Клан")
def menu_clan(message):
    uid=message.from_user.id;clan=get_clan_by_user(uid)
    if clan:
        cid=clan[0];members=get_clan_members(cid);mc=len(members)
        t=f"🐋 *Клан: {clan[2]} {clan[3]}*\n\nЛидер: @{clan[1]}\nУчастников: {mc}/{MAX_CLAN_MEMBERS}\n\n"
        m=types.InlineKeyboardMarkup()
        if clan[1]==uid:
            m.add(types.InlineKeyboardButton("🏰 Клановое подземелье",callback_data=f"cds_{cid}"))
            m.add(types.InlineKeyboardButton("📋 Участники",callback_data=f"cmem_{cid}"))
        m.add(types.InlineKeyboardButton("🚪 Покинуть",callback_data=f"cleave_{cid}"))
        bot.send_message(uid,t,parse_mode='Markdown',reply_markup=m)
    else:
        t="🐋 Вы не состоите в клане.\n\nСоздайте свой или попросите пригласить!"
        m=types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("➕ Создать клан",callback_data="ccreate"))
        bot.send_message(uid,t,parse_mode='Markdown',reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data=="ccreate")
def clan_create(call):
    bot.send_message(call.from_user.id,"Введите название клана:")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id,clan_create_name)

def clan_create_name(message):
    uid=message.from_user.id;name=message.text.strip()
    if len(name)>30: bot.send_message(uid,"Слишком длинное!");return
    bot.send_message(uid,f"Выберите эмблему: {' '.join(CLAN_EMOJIS)}\nОтправьте номер (1-{len(CLAN_EMOJIS)}):")
    bot.register_next_step_handler_by_chat_id(message.chat.id,lambda m:clan_create_emblem(m,name))

def clan_create_emblem(message,name):
    uid=message.from_user.id
    try: idx=int(message.text.strip())-1
    except: bot.send_message(uid,"Число!");return
    if idx<0 or idx>=len(CLAN_EMOJIS): bot.send_message(uid,"Неверный номер!");return
    emblem=CLAN_EMOJIS[idx]
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("INSERT INTO clans (name,emblem,leader_id,created_at) VALUES (?,?,?,?)",(name,emblem,uid,datetime.now().isoformat()))
    cid=c.lastrowid
    c.execute("INSERT INTO clan_members (clan_id,user_id,joined_at) VALUES (?,?,?)",(cid,uid,datetime.now().isoformat()))
    conn.commit();conn.close()
    bot.send_message(uid,f"✅ Клан {name} {emblem} создан!")

@bot.callback_query_handler(func=lambda c:c.data.startswith("cleave_"))
def clan_leave(call):
    uid=call.from_user.id;cid=int(call.data.split("_")[1])
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("DELETE FROM clan_members WHERE user_id=? AND clan_id=?",(uid,cid))
    c.execute("SELECT leader_id FROM clans WHERE clan_id=?",(cid,))
    r=c.fetchone()
    if r and r[0]==uid:
        c.execute("DELETE FROM clan_members WHERE clan_id=?",(cid,))
        c.execute("DELETE FROM clans WHERE clan_id=?",(cid,))
        c.execute("DELETE FROM clan_dungeons WHERE clan_id=?",(cid,))
    conn.commit();conn.close()
    bot.answer_callback_query(call.id,"Вы покинули клан!")

@bot.callback_query_handler(func=lambda c:c.data.startswith("cmem_"))
def clan_members(call):
    cid=int(call.data.split("_")[1]);members=get_clan_members(cid)
    t="📋 *Участники клана*\n\n"
    for mid in members:
        p=get_player(mid)
        if p: t+=f"  @{p[1]} ({get_seal_count(mid)} тюленей)\n"
    bot.edit_message_text(t,call.message.chat.id,call.message.message_id,parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c:c.data.startswith("cds_"))
def clan_dng_start(call):
    uid=call.from_user.id;cid=int(call.data.split("_")[1]);clan=get_clan_by_user(uid)
    if not clan or clan[1]!=uid: bot.answer_callback_query(call.id,"Только лидер!");return
    members=get_clan_members(cid);all_seals=[]
    for mid in members:
        for s in get_player_seals(mid):
            if s[11]==0 and s[9]>=CLAN_DUNGEON_MIN_LEVEL: all_seals.append(s)
    if not all_seals: bot.answer_callback_query(call.id,"Нет тюленей 4+ уровня!");return
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("DELETE FROM clan_dungeons WHERE clan_id=?",(cid,))
    c.execute("INSERT INTO clan_dungeons (clan_id,current_floor,active,started_by) VALUES (?,1,1,?)",(cid,uid))
    conn.commit();conn.close()
    clan_dng_floor(call,cid,1)

def clan_dng_floor(call,cid,fl):
    members=get_clan_members(cid);all_seals=[]
    for mid in members:
        for s in get_player_seals(mid):
            if s[11]==0 and s[9]>=CLAN_DUNGEON_MIN_LEVEL: all_seals.append(s)
    if not all_seals:
        bot.edit_message_text("Нет доступных тюленей!",call.message.chat.id,call.message.message_id);return
    mon=CLAN_DUNGEON_MONSTERS[fl-1].copy()
    total_str=sum(get_effective_stats(s[0])[0] for s in all_seals)
    total_def=sum(get_effective_stats(s[0])[1] for s in all_seals)
    total_hp=sum(s[3] for s in all_seals)
    t=f"🏰 *Клановое подземелье — Этаж {fl}/{CLAN_DUNGEON_FLOORS}*\n\n"
    t+=f"🦭 Тюленей: {len(all_seals)}\n💪 Сум. сила: {total_str}\n🛡️ Сум. защита: {total_def}\n❤️ Сум. HP: {total_hp}\n\n"
    t+=f"{mon['name']}: ❤️{mon['hp']} 💪{mon['str']} 🛡️{mon['def']}\n"
    m=types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("⚔️ Атаковать",callback_data=f"cda_{cid}_{fl}"))
    m.add(types.InlineKeyboardButton("🏃 Отступить",callback_data=f"cdf_{cid}_{fl}"))
    bot.edit_message_text(t,call.message.chat.id,call.message.message_id,parse_mode='Markdown',reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("cda_"))
def clan_dng_atk(call):
    uid=call.from_user.id;p=call.data.split("_");cid=int(p[2]);fl=int(p[3])
    members=get_clan_members(cid);all_seals=[]
    for mid in members:
        for s in get_player_seals(mid):
            if s[11]==0 and s[9]>=CLAN_DUNGEON_MIN_LEVEL: all_seals.append(s)
    if not all_seals: bot.answer_callback_query(call.id,"Нет тюленей!");return
    mon=CLAN_DUNGEON_MONSTERS[fl-1].copy()
    ts=sum(get_effective_stats(s[0])[0] for s in all_seals)
    td=sum(get_effective_stats(s[0])[1] for s in all_seals)
    thp=sum(s[3] for s in all_seals)
    log=[f"🏰 Этаж {fl}: {len(all_seals)} тюленей vs {mon['name']}"]
    while thp>0 and mon["hp"]>0:
        d=max(1,ts-mon["def"]+random.randint(-5,10));mon["hp"]-=d
        log.append(f"Тюлени →{d} (монстр {max(0,mon['hp'])}❤️)")
        if mon["hp"]<=0: break
        dm=max(1,mon["str"]-td+random.randint(-2,6))
        target=random.choice(all_seals);update_seal(target[0],health=max(1,target[3]-dm))
        thp-=dm;log.append(f"{mon['name']} →{target[2]} на {dm} (осталось {max(0,thp)}❤️)")
    if mon["hp"]<=0:
        log.append("\n✅ Монстр повержен!")
        rw=200+fl*50;eg=100+fl*30
        for mid in members:
            add_fishnets(mid,rw)
            for s in get_player_seals(mid):
                if s[11]==0: update_seal(s[0],exp=s[10]+eg)
        log.append(f"🏆 Все получили 🐟{rw} и +{eg}оп!")
        update_quest_chain(uid,"clan_dungeon_floor",fl)
        if fl>=CLAN_DUNGEON_FLOORS:
            log.append(f"👑 *Клановое подземелье пройдено!*")
            conn=sqlite3.connect(DB_PATH);c=conn.cursor()
            c.execute("UPDATE clan_dungeons SET active=0 WHERE clan_id=?",(cid,));conn.commit();conn.close()
            bot.edit_message_text("\n".join(log),call.message.chat.id,call.message.message_id,parse_mode='Markdown')
        else:
            nf=fl+1;log.append(f"Открыт этаж {nf}!")
            m=types.InlineKeyboardMarkup()
            m.add(types.InlineKeyboardButton("➡️ Дальше",callback_data=f"cdn_{cid}_{nf}"))
            m.add(types.InlineKeyboardButton("🏃 Выйти",callback_data=f"cdf_{cid}_{fl}"))
            bot.edit_message_text("\n".join(log),call.message.chat.id,call.message.message_id,parse_mode='Markdown',reply_markup=m)
    elif thp<=0:
        log.append("\n💀 Все тюлени пали...")
        for s in all_seals: update_seal(s[0],health=1,mood=max(0,s[5]-20))
        conn=sqlite3.connect(DB_PATH);c=conn.cursor()
        c.execute("UPDATE clan_dungeons SET active=0 WHERE clan_id=?",(cid,));conn.commit();conn.close()
        bot.edit_message_text("\n".join(log),call.message.chat.id,call.message.message_id,parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c:c.data.startswith("cdn_"))
def clan_dng_next(call):
    p=call.data.split("_");clan_dng_floor(call,int(p[2]),int(p[3]))

@bot.callback_query_handler(func=lambda c:c.data.startswith("cdf_"))
def clan_dng_flee(call):
    cid=int(call.data.split("_")[2]);conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("UPDATE clan_dungeons SET active=0 WHERE clan_id=?",(cid,));conn.commit();conn.close()
    bot.edit_message_text("🏃 Отступление.",call.message.chat.id,call.message.message_id)

# ==================== ФРАКЦИИ ====================
@bot.message_handler(commands=['faction'])
@bot.message_handler(func=lambda m:m.text=="🏛 Фракции")
def menu_faction(message):
    uid=message.from_user.id;p=get_player(uid)
    if not p: bot.send_message(uid,"/start");return
    t="🏛 *Фракции*\n\n"
    for fid,fd in FACTIONS.items():
        mk=" ✅" if p[5]==fid else ""
        t+=f"*{fd['name']}*{mk}\n  {fd['desc']}\n"
        if p[5]==fid: t+=f"  Репутация: {p[6]}\n"
        t+="\n"
    m=types.InlineKeyboardMarkup()
    for fid,fd in FACTIONS.items():
        if p[5]==fid: m.add(types.InlineKeyboardButton(f"🔄 Сменить: {fd['name']}",callback_data=f"fj_{fid}"))
        else: m.add(types.InlineKeyboardButton(f"Вступить: {fd['name']}",callback_data=f"fj_{fid}"))
    bot.send_message(uid,t,parse_mode='Markdown',reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("fj_"))
def faction_join(call):
    fid=call.data.split("_")[1]
    if fid not in FACTIONS: bot.answer_callback_query(call.id,"Не найдена!");return
    update_player(call.from_user.id,faction=fid,faction_rep=0)
    bot.answer_callback_query(call.id,f"Вступили: {FACTIONS[fid]['name']}!")

# ==================== ГОЛОСОВАНИЕ ====================
@bot.message_handler(commands=['vote'])
def cmd_vote(message):
    uid=message.from_user.id;today=date.today().isoformat()
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT vote FROM votes WHERE user_id=? AND date=?",(uid,today));ex=c.fetchone();conn.close()
    ev=get_todays_event();t=f"🗳 *Голосование*\n\n{ev['desc']}\n\n"
    act=get_active_event_text()
    if act: t+=f"✅ Активно: {act}\n\n"
    if ex: t+=f"Вы голосовали: {ex[0].upper()}";bot.send_message(uid,t,parse_mode='Markdown');return
    t+="Голосуем?"
    m=types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("✅ За",callback_data="vy"),types.InlineKeyboardButton("❌ Против",callback_data="vn"))
    bot.send_message(uid,t,parse_mode='Markdown',reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data in("vy","vn"))
def vote_cb(call):
    uid=call.from_user.id;vote="yes" if call.data=="vy" else "no";today=date.today().isoformat()
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    try:
        c.execute("INSERT INTO votes (user_id,event_type,vote,date) VALUES (?,?,?,?)",(uid,"daily",vote,today));conn.commit()
    except sqlite3.IntegrityError:
        bot.answer_callback_query(call.id,"Уже голосовали!");conn.close();return
    conn.close()
    if check_vote_result():
        ev=get_todays_event();activate_event(ev["event_type"],ev["effect"])
        bot.answer_callback_query(call.id,f"Активировано: {ev['desc']}")
        bot.edit_message_text(f"✅ *Активировано!*\n{ev['desc']}",call.message.chat.id,call.message.message_id,parse_mode='Markdown')
    else:
        bot.answer_callback_query(call.id,"Голос принят!")
        bot.edit_message_text(f"🗳 Голос: {vote.upper()}\nНужно 3+ голоса.",call.message.chat.id,call.message.message_id,parse_mode='Markdown')

# ==================== БРАКИ ====================
@bot.message_handler(commands=['marry'])
@bot.message_handler(func=lambda m:m.text=="💍 Брак")
def menu_marry(message):
    uid=message.from_user.id;seals=get_player_seals(uid)
    if not seals: bot.send_message(uid,"Нет тюленей!");return
    if get_seal_count(uid)>=MAX_SEALS: bot.send_message(uid,f"Макс {MAX_SEALS}!");return
    m=types.InlineKeyboardMarkup()
    for s in seals: m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})",callback_data=f"msel_{s[0]}"))
    bot.send_message(uid,"Выберите тюленя:",reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("msel_"))
def marry_sel(call):
    sid=int(call.data.split("_")[1])
    bot.send_message(call.from_user.id,"ID или @username партнёра:")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id,lambda m:marry_partner(m,sid))

def marry_partner(message,sid1):
    uid=message.from_user.id;txt=message.text.strip()
    if txt.startswith("@"):
        conn=sqlite3.connect(DB_PATH);c=conn.cursor()
        c.execute("SELECT user_id FROM players WHERE username=?",(txt[1:],));r=c.fetchone();conn.close()
        if not r: bot.send_message(uid,"Не найден!");return
        pid=r[0]
    else:
        try: pid=int(txt)
        except: bot.send_message(uid,"Формат!");return
    if pid==uid: bot.send_message(uid,"С собой нельзя!");return
    ps=get_player_seals(pid)
    if not ps: bot.send_message(uid,"Нет тюленей у игрока!");return
    m=types.InlineKeyboardMarkup()
    for s in ps: m.add(types.InlineKeyboardButton(f"{s[2]} (ур.{s[9]})",callback_data=f"mdo_{sid1}_{s[0]}_{pid}"))
    bot.send_message(uid,"Выберите тюленя партнёра:",reply_markup=m)

@bot.callback_query_handler(func=lambda c:c.data.startswith("mdo_"))
def marry_do(call):
    uid=call.from_user.id;p=call.data.split("_");s1,s2,pid=int(p[1]),int(p[2]),int(p[3])
    se1,se2=get_seal(s1),get_seal(s2)
    if not se1 or not se2: bot.answer_callback_query(call.id,"Не найден!");return
    if get_seal_count(uid)>=MAX_SEALS: bot.answer_callback_query(call.id,f"Макс {MAX_SEALS}!");return
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT * FROM marriages WHERE (seal1_id=? AND seal2_id=?) OR (seal1_id=? AND seal2_id=?)",(s1,s2,s2,s1))
    if c.fetchone(): bot.answer_callback_query(call.id,"Уже в браке!");conn.close();return
    c.execute("INSERT INTO marriages (seal1_id,seal2_id,player1_id,player2_id,created_at) VALUES (?,?,?,?,?)",(s1,s2,uid,pid,datetime.now().isoformat()))
    conn.commit();conn.close()
    msg=f"💍 Брак! {se1[2]} ❤️ {se2[2]}\n"
    if random.random()<0.5:
        bn=random.choice(["Малыш","Кроха","Пузырь","Лапик","Шлёпик","Ням"])
        bs=(se1[7]+se2[7])//4+random.randint(1,3);bd=(se1[8]+se2[8])//4+random.randint(0,2)
        conn=sqlite3.connect(DB_PATH);c=conn.cursor()
        c.execute("INSERT INTO seals (owner_id,name,health,max_health,mood,satiety,strength,defense,level,exp,is_baby,born_at) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
                  (uid,bn,60,60,70,70,bs,bd,1,0,datetime.now().isoformat()))
        conn.commit();conn.close()
        msg+=f"🍼 Тюленёнок — {bn}! С:{bs} З:{bd}"
    else: msg+="Нет тюленёнка..."
    bot.edit_message_text(msg,call.message.chat.id,call.message.message_id,parse_mode='Markdown')

# ==================== ЕЖЕДНЕВНЫЕ ЗАДАНИЯ (ОТДЕЛЬНО ОТ ЦЕПОЧЕК) ====================
@bot.message_handler(commands=['quests'])
@bot.message_handler(func=lambda m:m.text=="📋 Задания")
def menu_quests(message):
    uid=message.from_user.id
    try:
        generate_daily_quests(uid)
        quests=get_daily_quests(uid)
    except Exception as e:
        bot.send_message(uid,f"⚠️ Ошибка БД: {e}");return
    if not quests: bot.send_message(uid,"Задания не сгенерированы.");return
    t="📋 *Ежедневные задания*\n\n";m=types.InlineKeyboardMarkup()
    qd={q["type"]:q["desc"] for q in QUEST_TEMPLATES}
    for q in quests:
        qid=q[0];qt=q[2];qtgt=q[3];qprog=q[4];qrew=q[5];cl=q[7]
        d=qd.get(qt,qt);s=f"{qprog}/{qtgt}"
        if cl: t+=f"  ✅ {d} — {s} (🐟{qrew}) — получено\n"
        elif qprog>=qtgt:
            t+=f"  🎁 {d} — {s} (🐟{qrew}) — готово!\n"
            m.add(types.InlineKeyboardButton(f"Забрать 🐟{qrew}",callback_data=f"qclaim_{qid}"))
        else: t+=f"  ⬜ {d} — {s} (🐟{qrew})\n"
    if m.keyboard: bot.send_message(uid,t,parse_mode='Markdown',reply_markup=m)
    else: bot.send_message(uid,t,parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c:c.data.startswith("qclaim_"))
def quest_claim(call):
    uid=call.from_user.id;qid=int(call.data.split("_")[1])
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    c.execute("SELECT quest_id,quest_target,quest_progress,quest_reward,claimed FROM daily_quests WHERE quest_id=? AND claimed=0",(qid,));r=c.fetchone()
    if not r: bot.answer_callback_query(call.id,"Уже получено!");conn.close();return
    qid_db,qtgt,qprog,qrew,cl=r
    if qprog<qtgt: bot.answer_callback_query(call.id,"Не выполнено!");conn.close();return
    c.execute("UPDATE daily_quests SET claimed=1 WHERE quest_id=?",(qid,));conn.commit();conn.close()
    add_fishnets(uid,qrew);bot.answer_callback_query(call.id,f"Получено 🐟{qrew}!")
    menu_quests(call.message)

# ==================== ФОНОВЫЕ ПОТОКИ ====================
def stats_decay():
    while True:
        time.sleep(3600)
        try:
            conn=sqlite3.connect(DB_PATH,timeout=10);c=conn.cursor()
            c.execute("SELECT seal_id,health,mood,satiety FROM seals")
            for sid,hp,mood,sat in c.fetchall():
                nm=max(0,mood-random.randint(3,8));ns=max(0,sat-random.randint(5,10))
                nh=max(1,hp-random.randint(3,8)) if ns<20 else hp
                c.execute("UPDATE seals SET mood=?,satiety=?,health=? WHERE seal_id=?",(nm,ns,nh,sid))
            conn.commit();conn.close()
        except: pass

def health_regen():
    while True:
        time.sleep(3600)
        try:
            conn=sqlite3.connect(DB_PATH,timeout=10);c=conn.cursor()
            c.execute("SELECT seal_id,health,max_health FROM seals WHERE health<max_health")
            for sid,hp,mhp in c.fetchall():
                bonus=25
                c2=conn.cursor()
                c2.execute("SELECT COUNT(*) FROM seal_skills WHERE seal_id=? AND skill_effect='regen'",(sid,))
                if c2.fetchone()[0]>0: bonus+=5
                c.execute("UPDATE seals SET health=? WHERE seal_id=?",(min(mhp,hp+bonus),sid))
            conn.commit();conn.close()
        except: pass

threading.Thread(target=stats_decay,daemon=True).start()
threading.Thread(target=health_regen,daemon=True).start()

# ==================== КОМАНДЫ В МЕНЮ ====================
bot.set_my_commands([
    types.BotCommand("start","Главное меню"),types.BotCommand("help","Справка"),
    types.BotCommand("profile","Профиль"),types.BotCommand("gallery","Галерея"),
    types.BotCommand("inventory","Инвентарь"),types.BotCommand("setphoto","Фото тюленя"),
    types.BotCommand("shop","Магазин"),types.BotCommand("craft","Крафт"),
    types.BotCommand("trade","Биржа"),types.BotCommand("battle","Бой с боссом"),
    types.BotCommand("dungeon","Подземелье"),types.BotCommand("work","Работа"),
    types.BotCommand("duel","PvP-дуэль"),types.BotCommand("fish","Рыбалка"),
    types.BotCommand("vote","Голосование"),types.BotCommand("faction","Фракции"),
    types.BotCommand("questchain","Квестовые цепочки"),types.BotCommand("clan","Клан"),
    types.BotCommand("marry","Брак"),types.BotCommand("quests","Задания"),
    types.BotCommand("leaderboard","Лидеры"),
])

if __name__=="__main__":
    run_migrations()
    print("Бот запущен! 🦭")
    bot.polling(none_stop=True)

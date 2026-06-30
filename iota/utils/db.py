import sqlite3, threading, time
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "iota.db"
DB_PATH.parent.mkdir(exist_ok=True)
_local = threading.local()

def get_conn():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn

def init_db():
    c = get_conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id         INTEGER PRIMARY KEY,
        username        TEXT    DEFAULT '',
        full_name       TEXT    DEFAULT '',
        balance         INTEGER DEFAULT 0,
        gems            INTEGER DEFAULT 0,
        is_premium      INTEGER DEFAULT 0,
        premium_emoji   TEXT    DEFAULT '',
        last_daily      INTEGER DEFAULT 0,
        kills           INTEGER DEFAULT 0,
        daily_kills     INTEGER DEFAULT 0,
        last_kill_reset INTEGER DEFAULT 0,
        robs            INTEGER DEFAULT 0,
        daily_robs      INTEGER DEFAULT 0,
        last_rob_reset  INTEGER DEFAULT 0,
        xp              INTEGER DEFAULT 0,
        level           INTEGER DEFAULT 1,
        protected_until INTEGER DEFAULT 0,
        dead_until      INTEGER DEFAULT 0,
        wallet          INTEGER DEFAULT 0,
        is_banned       INTEGER DEFAULT 0,
        free_gem_claimed INTEGER DEFAULT 0,
        created_at      INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS group_economy (
        user_id         INTEGER,
        chat_id         INTEGER,
        balance         INTEGER DEFAULT 0,
        kills           INTEGER DEFAULT 0,
        robs            INTEGER DEFAULT 0,
        protected_until INTEGER DEFAULT 0,
        dead_until      INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, chat_id)
    );

    CREATE TABLE IF NOT EXISTS card_rank (
        user_id     INTEGER PRIMARY KEY,
        wins        INTEGER DEFAULT 0,
        losses      INTEGER DEFAULT 0,
        won_amount  INTEGER DEFAULT 0,
        lost_amount INTEGER DEFAULT 0,
        streak      INTEGER DEFAULT 0,
        best_streak INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS items (
        owner_id    INTEGER,
        item_name   TEXT,
        quantity    INTEGER DEFAULT 1,
        PRIMARY KEY (owner_id, item_name)
    );

    CREATE TABLE IF NOT EXISTS warnings (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER,
        chat_id     INTEGER,
        reason      TEXT    DEFAULT '',
        warned_by   INTEGER,
        warned_at   INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS admin_promotions (
        user_id     INTEGER,
        chat_id     INTEGER,
        promoted_by INTEGER,
        PRIMARY KEY (user_id, chat_id)
    );

    CREATE TABLE IF NOT EXISTS valentines (
        user_id     INTEGER PRIMARY KEY,
        gender      TEXT,
        choice1     INTEGER DEFAULT 0,
        choice2     INTEGER DEFAULT 0,
        choice3     INTEGER DEFAULT 0,
        matched_with INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS village (
        user_id             INTEGER PRIMARY KEY,
        wood                INTEGER DEFAULT 0,
        stone               INTEGER DEFAULT 0,
        iron                INTEGER DEFAULT 0,
        citizens            INTEGER DEFAULT 5,
        treasury            INTEGER DEFAULT 0,
        vault               INTEGER DEFAULT 0,
        woodyard_level      INTEGER DEFAULT 1,
        quarry_level        INTEGER DEFAULT 1,
        iron_mine_level     INTEGER DEFAULT 1,
        last_mine           INTEGER DEFAULT 0,
        last_tax            INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS top_groups (
        rank        INTEGER PRIMARY KEY,
        user_id     INTEGER,
        group_name  TEXT,
        group_link  TEXT
    );

    CREATE TABLE IF NOT EXISTS global_used_coupons (
        user_id     INTEGER,
        coupon      TEXT,
        PRIMARY KEY (user_id, coupon)
    );

    CREATE TABLE IF NOT EXISTS group_coupons (
        chat_id     INTEGER PRIMARY KEY,
        code        TEXT,
        amount      INTEGER,
        created_by  INTEGER,
        created_at  INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS group_coupon_used (
        user_id     INTEGER,
        chat_id     INTEGER,
        PRIMARY KEY (user_id, chat_id)
    );

    CREATE TABLE IF NOT EXISTS card_games (
        game_id     TEXT PRIMARY KEY,
        chat_id     INTEGER,
        player1     INTEGER,
        player2     INTEGER DEFAULT 0,
        bet         INTEGER DEFAULT 0,
        cards_p1    TEXT    DEFAULT '',
        cards_p2    TEXT    DEFAULT '',
        round       INTEGER DEFAULT 1,
        score_p1    INTEGER DEFAULT 0,
        score_p2    INTEGER DEFAULT 0,
        status      TEXT    DEFAULT 'waiting',
        created_at  INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS bomb_games (
        game_id     TEXT PRIMARY KEY,
        chat_id     INTEGER,
        players     TEXT    DEFAULT '',
        bet         INTEGER DEFAULT 0,
        holder      INTEGER DEFAULT 0,
        status      TEXT    DEFAULT 'waiting',
        created_at  INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS sticker_packs (
        user_id     INTEGER PRIMARY KEY,
        pack_name   TEXT,
        pack_title  TEXT
    );

    CREATE TABLE IF NOT EXISTS gaming_status (
        chat_id     INTEGER PRIMARY KEY,
        is_open     INTEGER DEFAULT 1
    );
    """)
    c.commit()

# ── helpers ──────────────────────────────────────────────────────────────────

def _now(): return int(time.time())

def ensure_user(user_id, username="", full_name=""):
    c = get_conn()
    c.execute("INSERT OR IGNORE INTO users (user_id,username,full_name,created_at) VALUES(?,?,?,?)",
              (user_id, username, full_name, _now()))
    if username or full_name:
        c.execute("UPDATE users SET username=?,full_name=? WHERE user_id=?",
                  (username, full_name, user_id))
    c.commit()

def get_user(uid):
    ensure_user(uid)
    return dict(get_conn().execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone())

def update_user(uid, **kw):
    if not kw: return
    c = get_conn()
    c.execute(f"UPDATE users SET {','.join(f'{k}=?' for k in kw)} WHERE user_id=?",
              list(kw.values()) + [uid])
    c.commit()

def add_balance(uid, amt):
    get_conn().execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, uid))
    get_conn().commit()

def deduct_balance(uid, amt) -> bool:
    u = get_user(uid)
    if u["balance"] < amt: return False
    get_conn().execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, uid))
    get_conn().commit()
    return True

def get_top_rich(n=10):
    return get_conn().execute(
        "SELECT * FROM users WHERE is_banned=0 ORDER BY balance DESC LIMIT ?", (n,)
    ).fetchall()

def get_top_kill(n=10):
    return get_conn().execute(
        "SELECT * FROM users WHERE is_banned=0 ORDER BY kills DESC LIMIT ?", (n,)
    ).fetchall()

def get_user_rank(uid):
    r = get_conn().execute(
        "SELECT COUNT(*)+1 as r FROM users WHERE balance>(SELECT balance FROM users WHERE user_id=?) AND is_banned=0",
        (uid,)).fetchone()
    return r["r"] if r else 0

def total_users():
    return get_conn().execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]

# ── card rank ─────────────────────────────────────────────────────────────────

def ensure_card_rank(uid):
    get_conn().execute("INSERT OR IGNORE INTO card_rank (user_id) VALUES(?)", (uid,))
    get_conn().commit()

def get_card_rank(uid):
    ensure_card_rank(uid)
    return dict(get_conn().execute("SELECT * FROM card_rank WHERE user_id=?", (uid,)).fetchone())

def update_card_rank(uid, **kw):
    if not kw: return
    c = get_conn()
    c.execute(f"UPDATE card_rank SET {','.join(f'{k}=?' for k in kw)} WHERE user_id=?",
              list(kw.values()) + [uid])
    c.commit()

def get_card_leaders(n=10):
    return get_conn().execute(
        """SELECT cr.*, u.username, u.full_name, u.is_premium, u.premium_emoji
           FROM card_rank cr JOIN users u ON cr.user_id=u.user_id
           ORDER BY cr.won_amount DESC LIMIT ?""", (n,)
    ).fetchall()

def get_card_rank_position(uid):
    r = get_conn().execute(
        "SELECT COUNT(*)+1 as r FROM card_rank WHERE won_amount>(SELECT won_amount FROM card_rank WHERE user_id=?)",
        (uid,)).fetchone()
    total = get_conn().execute("SELECT COUNT(*) as c FROM card_rank").fetchone()["c"]
    return (r["r"] if r else 1), total

# ── group economy ─────────────────────────────────────────────────────────────

def ensure_guser(uid, cid):
    get_conn().execute("INSERT OR IGNORE INTO group_economy(user_id,chat_id) VALUES(?,?)", (uid, cid))
    get_conn().commit()

def get_guser(uid, cid):
    ensure_guser(uid, cid)
    return dict(get_conn().execute("SELECT * FROM group_economy WHERE user_id=? AND chat_id=?", (uid, cid)).fetchone())

def update_guser(uid, cid, **kw):
    if not kw: return
    c = get_conn()
    c.execute(f"UPDATE group_economy SET {','.join(f'{k}=?' for k in kw)} WHERE user_id=? AND chat_id=?",
              list(kw.values()) + [uid, cid])
    c.commit()

def get_granks(cid, n=10):
    return get_conn().execute(
        """SELECT g.*,u.username,u.full_name,u.is_premium,u.premium_emoji
           FROM group_economy g JOIN users u ON g.user_id=u.user_id
           WHERE g.chat_id=? ORDER BY g.balance DESC LIMIT ?""", (cid, n)
    ).fetchall()

# ── warnings ──────────────────────────────────────────────────────────────────

def add_warning(uid, cid, reason, by):
    c = get_conn()
    c.execute("INSERT INTO warnings(user_id,chat_id,reason,warned_by,warned_at) VALUES(?,?,?,?,?)",
              (uid, cid, reason, by, _now()))
    c.commit()

def get_warnings(uid, cid):
    return get_conn().execute(
        "SELECT * FROM warnings WHERE user_id=? AND chat_id=? ORDER BY warned_at DESC", (uid, cid)
    ).fetchall()

def count_warnings(uid, cid):
    return get_conn().execute(
        "SELECT COUNT(*) as c FROM warnings WHERE user_id=? AND chat_id=?", (uid, cid)
    ).fetchone()["c"]

def remove_last_warning(uid, cid):
    c = get_conn()
    row = c.execute("SELECT id FROM warnings WHERE user_id=? AND chat_id=? ORDER BY warned_at DESC LIMIT 1",
                    (uid, cid)).fetchone()
    if row:
        c.execute("DELETE FROM warnings WHERE id=?", (row["id"],))
        c.commit(); return True
    return False

# ── items ─────────────────────────────────────────────────────────────────────

def add_item(uid, name, qty=1):
    c = get_conn()
    c.execute("INSERT INTO items(owner_id,item_name,quantity) VALUES(?,?,?) ON CONFLICT(owner_id,item_name) DO UPDATE SET quantity=quantity+?",
              (uid, name, qty, qty))
    c.commit()

def get_items(uid):
    return get_conn().execute("SELECT item_name,quantity FROM items WHERE owner_id=?", (uid,)).fetchall()

def remove_item(uid, name, qty=1):
    c = get_conn()
    row = c.execute("SELECT quantity FROM items WHERE owner_id=? AND item_name=?", (uid, name)).fetchone()
    if not row or row["quantity"] < qty: return False
    if row["quantity"] == qty:
        c.execute("DELETE FROM items WHERE owner_id=? AND item_name=?", (uid, name))
    else:
        c.execute("UPDATE items SET quantity=quantity-? WHERE owner_id=? AND item_name=?", (qty, uid, name))
    c.commit(); return True

# ── village ───────────────────────────────────────────────────────────────────

def ensure_village(uid):
    get_conn().execute("INSERT OR IGNORE INTO village(user_id,last_mine,last_tax) VALUES(?,?,?)",
                       (uid, _now(), _now()))
    get_conn().commit()

def get_village(uid):
    ensure_village(uid)
    return dict(get_conn().execute("SELECT * FROM village WHERE user_id=?", (uid,)).fetchone())

def update_village(uid, **kw):
    if not kw: return
    c = get_conn()
    c.execute(f"UPDATE village SET {','.join(f'{k}=?' for k in kw)} WHERE user_id=?",
              list(kw.values()) + [uid])
    c.commit()

def get_empire_top(n=10):
    return get_conn().execute(
        """SELECT v.*,u.username,u.full_name,v.vault+v.treasury as total
           FROM village v JOIN users u ON v.user_id=u.user_id
           ORDER BY total DESC LIMIT ?""", (n,)
    ).fetchall()

# ── global coupons ─────────────────────────────────────────────────────────────

def use_global_coupon(uid, code) -> bool:
    c = get_conn()
    try:
        c.execute("INSERT INTO global_used_coupons(user_id,coupon) VALUES(?,?)", (uid, code))
        c.commit(); return True
    except sqlite3.IntegrityError:
        return False

# ── group coupons ──────────────────────────────────────────────────────────────

def get_group_coupon(cid):
    row = get_conn().execute("SELECT * FROM group_coupons WHERE chat_id=?", (cid,)).fetchone()
    return dict(row) if row else None

def set_group_coupon(cid, code, amount, by):
    c = get_conn()
    c.execute("INSERT OR REPLACE INTO group_coupons(chat_id,code,amount,created_by,created_at) VALUES(?,?,?,?,?)",
              (cid, code, amount, by, _now()))
    c.commit()

def delete_group_coupon(cid):
    c = get_conn()
    c.execute("DELETE FROM group_coupons WHERE chat_id=?", (cid,))
    c.execute("DELETE FROM group_coupon_used WHERE chat_id=?", (cid,))
    c.commit()

def use_group_coupon(uid, cid) -> bool:
    c = get_conn()
    try:
        c.execute("INSERT INTO group_coupon_used(user_id,chat_id) VALUES(?,?)", (uid, cid))
        c.commit(); return True
    except sqlite3.IntegrityError:
        return False

# ── gaming status ─────────────────────────────────────────────────────────────

def is_gaming_open(cid) -> bool:
    row = get_conn().execute("SELECT is_open FROM gaming_status WHERE chat_id=?", (cid,)).fetchone()
    return row["is_open"] == 1 if row else True

def set_gaming_status(cid, status: bool):
    c = get_conn()
    c.execute("INSERT OR REPLACE INTO gaming_status(chat_id,is_open) VALUES(?,?)", (cid, 1 if status else 0))
    c.commit()

# ── card games ────────────────────────────────────────────────────────────────

def create_card_game(gid, cid, p1, bet):
    c = get_conn()
    c.execute("INSERT INTO card_games(game_id,chat_id,player1,bet,status,created_at) VALUES(?,?,?,?,'waiting',?)",
              (gid, cid, p1, bet, _now()))
    c.commit()

def get_card_game(gid):
    row = get_conn().execute("SELECT * FROM card_games WHERE game_id=?", (gid,)).fetchone()
    return dict(row) if row else None

def update_card_game(gid, **kw):
    if not kw: return
    c = get_conn()
    c.execute(f"UPDATE card_games SET {','.join(f'{k}=?' for k in kw)} WHERE game_id=?",
              list(kw.values()) + [gid])
    c.commit()

def delete_card_game(gid):
    get_conn().execute("DELETE FROM card_games WHERE game_id=?", (gid,))
    get_conn().commit()

# ── bomb games ────────────────────────────────────────────────────────────────

def create_bomb_game(gid, cid, p1, bet):
    c = get_conn()
    c.execute("INSERT INTO bomb_games(game_id,chat_id,players,bet,holder,status,created_at) VALUES(?,?,?,?,?,'waiting',?)",
              (gid, cid, str(p1), bet, p1, _now()))
    c.commit()

def get_bomb_game(gid):
    row = get_conn().execute("SELECT * FROM bomb_games WHERE game_id=?", (gid,)).fetchone()
    return dict(row) if row else None

def update_bomb_game(gid, **kw):
    if not kw: return
    c = get_conn()
    c.execute(f"UPDATE bomb_games SET {','.join(f'{k}=?' for k in kw)} WHERE game_id=?",
              list(kw.values()) + [gid])
    c.commit()

def delete_bomb_game(gid):
    get_conn().execute("DELETE FROM bomb_games WHERE game_id=?", (gid,))
    get_conn().commit()

# ── valentines ────────────────────────────────────────────────────────────────

def get_valentine(uid):
    row = get_conn().execute("SELECT * FROM valentines WHERE user_id=?", (uid,)).fetchone()
    return dict(row) if row else None

def set_valentine(uid, gender, c1, c2, c3):
    c = get_conn()
    c.execute("INSERT OR REPLACE INTO valentines(user_id,gender,choice1,choice2,choice3) VALUES(?,?,?,?,?)",
              (uid, gender, c1, c2, c3))
    c.commit()

def delete_valentine(uid):
    get_conn().execute("DELETE FROM valentines WHERE user_id=?", (uid,))
    get_conn().commit()

def count_valentines():
    row = get_conn().execute("SELECT COUNT(*) as t,SUM(gender='male') as m,SUM(gender='female') as f FROM valentines").fetchone()
    return row

# ── admin promotions ──────────────────────────────────────────────────────────

def track_promotion(uid, cid, by):
    c = get_conn()
    c.execute("INSERT OR REPLACE INTO admin_promotions VALUES(?,?,?)", (uid, cid, by))
    c.commit()

def get_bot_promotions(cid):
    return get_conn().execute("SELECT user_id FROM admin_promotions WHERE chat_id=?", (cid,)).fetchall()

def remove_promotion(uid, cid):
    get_conn().execute("DELETE FROM admin_promotions WHERE user_id=? AND chat_id=?", (uid, cid))
    get_conn().commit()

# ── sticker packs ─────────────────────────────────────────────────────────────

def get_sticker_pack(uid):
    row = get_conn().execute("SELECT * FROM sticker_packs WHERE user_id=?", (uid,)).fetchone()
    return dict(row) if row else None

def set_sticker_pack(uid, pack_name, pack_title):
    c = get_conn()
    c.execute("INSERT OR REPLACE INTO sticker_packs VALUES(?,?,?)", (uid, pack_name, pack_title))
    c.commit()

# ── top groups ────────────────────────────────────────────────────────────────

def set_top_group(rank, uid, name, link):
    c = get_conn()
    c.execute("INSERT OR REPLACE INTO top_groups VALUES(?,?,?,?)", (rank, uid, name, link))
    c.commit()

def get_top_groups():
    return get_conn().execute("SELECT * FROM top_groups ORDER BY rank").fetchall()

init_db()

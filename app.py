from flask import Flask, send_file, request, jsonify
from flask_cors import CORS
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

DB = "ns_master.db"

def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        mobile TEXT UNIQUE NOT NULL,
        username TEXT UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        caption TEXT,
        media TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        media_type TEXT DEFAULT 'post'
    )
    """)

    cur.execute("PRAGMA table_info(posts)")
    post_columns = {row[1] for row in cur.fetchall()}
    if "media_type" not in post_columns:
        cur.execute("ALTER TABLE posts ADD COLUMN media_type TEXT DEFAULT 'post'")

    cur.execute("PRAGMA table_info(users)")
    user_columns = {row[1] for row in cur.fetchall()}
    if "profile_photo" not in user_columns:
        cur.execute("ALTER TABLE users ADD COLUMN profile_photo TEXT")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS follows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        follower_id INTEGER NOT NULL,
        following_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(follower_id, following_id)
    )
    """)

    conn.commit()
    conn.close()

init_db()

@app.route("/")
def home():
    return send_file("index.html")

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_file(os.path.join(app.config["UPLOAD_FOLDER"], filename))

@app.route("/api/health")
def health():
    return jsonify({
        "ok": True,
        "app": "NS Master",
        "database": os.path.exists(DB)
    })

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json() or {}

    name = data.get("name", "").strip()
    mobile = data.get("mobile", "").strip()
    username = data.get("username", "").strip()
    bio = data.get("bio", "").strip()
    password = data.get("password", "")

    if not name or not mobile or not password:
        return jsonify({
            "ok": False,
            "message": "Name, mobile और password जरूरी है"
        }), 400

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO users (name, mobile, username, bio, password_hash) VALUES (?, ?, ?, ?, ?)",
            (name, mobile, username or None, bio, generate_password_hash(password))
        )
        conn.commit()
        user_id = cur.lastrowid

        return jsonify({
            "ok": True,
            "message": "Account created",
            "user_id": user_id
        })

    except sqlite3.IntegrityError:
        return jsonify({
            "ok": False,
            "message": "Mobile या username पहले से मौजूद है"
        }), 409

    finally:
        conn.close()


@app.route("/api/login", methods=["POST"])
def login_api():
    data = request.get_json() or {}

    mobile = data.get("mobile", "").strip()
    password = data.get("password", "")

    if not mobile or not password:
        return jsonify({
            "ok": False,
            "message": "Mobile और password जरूरी है"
        }), 400

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    user = conn.execute(
        "SELECT id, name, mobile, username, bio, created_at, password_hash FROM users WHERE mobile=?",
        (mobile,)
    ).fetchone()

    conn.close()

    if not user or not user["password_hash"]:
        return jsonify({
            "ok": False,
            "message": "Mobile या password गलत है"
        }), 401

    if not check_password_hash(user["password_hash"], password):
        return jsonify({
            "ok": False,
            "message": "Mobile या password गलत है"
        }), 401

    return jsonify({
        "ok": True,
        "message": "Login successful",
        "user": {
            "id": user["id"],
            "name": user["name"],
            "mobile": user["mobile"],
            "username": user["username"],
            "bio": user["bio"],
            "created_at": user["created_at"]
        }
    })


@app.route("/api/profile/<int:user_id>", methods=["GET", "PUT"])
def profile(user_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    if request.method == "GET":
        user = conn.execute(
            "SELECT id, name, mobile, username, bio, created_at FROM users WHERE id=?",
            (user_id,)
        ).fetchone()

        conn.close()

        if not user:
            return jsonify({"ok": False, "message": "User not found"}), 404

        return jsonify({"ok": True, "user": dict(user)})

    data = request.get_json() or {}
    name = data.get("name", "").strip()
    username = data.get("username", "").strip()

    if not name:
        conn.close()
        return jsonify({"ok": False, "message": "Name जरूरी है"}), 400

    try:
        conn.execute(
            "UPDATE users SET name=?, username=?, bio=? WHERE id=?",
            (name, username or None, bio, user_id)
        )
        conn.commit()

        user = conn.execute(
            "SELECT id, name, mobile, username, bio, created_at FROM users WHERE id=?",
            (user_id,)
        ).fetchone()

        conn.close()

        if not user:
            return jsonify({"ok": False, "message": "User not found"}), 404

        return jsonify({
            "ok": True,
            "message": "Profile updated",
            "user": dict(user)
        })

    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({
            "ok": False,
            "message": "Username पहले से मौजूद है"
        }), 409


@app.route("/api/upload", methods=["POST"])
def upload_media():
    user_id = request.form.get("user_id", "").strip()
    file = request.files.get("file")

    if not user_id:
        return jsonify({"ok": False, "message": "user_id जरूरी है"}), 400

    if not file or not file.filename:
        return jsonify({"ok": False, "message": "फोटो या वीडियो जरूरी है"}), 400

    user = sqlite3.connect(DB)
    exists = user.execute(
        "SELECT id FROM users WHERE id=?",
        (user_id,)
    ).fetchone()
    user.close()

    if not exists:
        return jsonify({"ok": False, "message": "User not found"}), 404

    filename = os.path.basename(file.filename)
    safe_name = f"{user_id}_{filename}"
    path = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)

    file.save(path)

    return jsonify({
        "ok": True,
        "message": "Media uploaded",
        "media": f"/uploads/{safe_name}"
    })

@app.route("/api/posts", methods=["GET", "POST"])
def posts():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    if request.method == "GET":
        rows = conn.execute("""
            SELECT posts.id, posts.user_id, users.name, users.username,
                   posts.caption, posts.media, posts.created_at
            FROM posts
            JOIN users ON users.id = posts.user_id
            ORDER BY posts.id DESC
        """).fetchall()

        conn.close()

        return jsonify({
            "ok": True,
            "posts": [dict(row) for row in rows]
        })

    data = request.get_json() or {}

    user_id = data.get("user_id")
    caption = data.get("caption", "").strip()
    media = data.get("media", "").strip()
    media_type = data.get("media_type", "post").strip()
    if media_type not in ("post", "reel"):
        media_type = "post"

    if not user_id:
        conn.close()
        return jsonify({
            "ok": False,
            "message": "user_id जरूरी है"
        }), 400

    user = conn.execute(
        "SELECT id FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    if not user:
        conn.close()
        return jsonify({
            "ok": False,
            "message": "User not found"
        }), 404

    cur = conn.execute(
        "INSERT INTO posts (user_id, caption, media, media_type) VALUES (?, ?, ?, ?)",
        (user_id, caption, media, media_type)
    )

    conn.commit()
    post_id = cur.lastrowid

    post = conn.execute("""
        SELECT posts.id, posts.user_id, users.name, users.username,
               posts.caption, posts.media, posts.created_at
        FROM posts
        JOIN users ON users.id = posts.user_id
        WHERE posts.id=?
    """, (post_id,)).fetchone()

    conn.close()

    return jsonify({
        "ok": True,
        "message": "Post created",
        "post": dict(post)
    })


@app.route("/api/like", methods=["POST"])
def like_post():
    data = request.get_json() or {}
    post_id = data.get("post_id")
    user_id = data.get("user_id")

    if not post_id or not user_id:
        return jsonify({"ok": False, "message": "post_id और user_id जरूरी है"}), 400

    conn = sqlite3.connect(DB)

    try:
        conn.execute(
            "INSERT INTO likes (post_id, user_id) VALUES (?, ?)",
            (post_id, user_id)
        )
        conn.commit()
        message = "Post liked"
    except sqlite3.IntegrityError:
        conn.execute(
            "DELETE FROM likes WHERE post_id=? AND user_id=?",
            (post_id, user_id)
        )
        conn.commit()
        message = "Post unliked"

    row = conn.execute(
        "SELECT COUNT(*) FROM likes WHERE post_id=?",
        (post_id,)
    ).fetchone()

    conn.close()

    return jsonify({
        "ok": True,
        "message": message,
        "post_id": post_id,
        "like_count": row[0]
    })

@app.route("/api/likes/<int:post_id>")
def post_likes(post_id):
    conn = sqlite3.connect(DB)

    row = conn.execute(
        "SELECT COUNT(*) FROM likes WHERE post_id=?",
        (post_id,)
    ).fetchone()

    conn.close()

    return jsonify({
        "ok": True,
        "post_id": post_id,
        "like_count": row[0]
    })

@app.route("/api/follow", methods=["POST"])
def follow_user():
    data = request.get_json() or {}

    follower_id = data.get("follower_id")
    following_id = data.get("following_id")

    if not follower_id or not following_id:
        return jsonify({
            "ok": False,
            "message": "follower_id और following_id जरूरी हैं"
        }), 400

    if int(follower_id) == int(following_id):
        return jsonify({
            "ok": False,
            "message": "आप खुद को Follow नहीं कर सकते"
        }), 400

    conn = sqlite3.connect(DB)

    try:
        conn.execute(
            "INSERT INTO follows (follower_id, following_id) VALUES (?, ?)",
            (follower_id, following_id)
        )
        conn.commit()
        conn.close()

        return jsonify({
            "ok": True,
            "message": "Following ✓"
        })

    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({
            "ok": False,
            "message": "आप पहले से Follow कर रहे हैं"
        }), 409


@app.route("/api/unfollow", methods=["POST"])
def unfollow_user():
    data=request.get_json() or {}

    follower_id=data.get("follower_id")
    following_id=data.get("following_id")

    if not follower_id or not following_id:
        return jsonify({
            "ok":False,
            "message":"follower_id और following_id जरूरी हैं"
        }),400

    conn=sqlite3.connect(DB)

    cur=conn.execute(
        "DELETE FROM follows WHERE follower_id=? AND following_id=?",
        (follower_id, following_id)
    )

    conn.commit()
    deleted=cur.rowcount
    conn.close()

    if deleted:
        return jsonify({
            "ok":True,
            "message":"Unfollow ✓"
        })

    return jsonify({
        "ok":False,
        "message":"Follow नहीं मिला"
    }),404


@app.route("/api/followers/<int:user_id>")
def followers(user_id):
    conn=sqlite3.connect(DB)
    conn.row_factory=sqlite3.Row

    rows=conn.execute("""
        SELECT users.id, users.name, users.username
        FROM follows
        JOIN users ON users.id=follows.follower_id
        WHERE follows.following_id=?
        ORDER BY follows.id DESC
    """,(user_id,)).fetchall()

    conn.close()

    return jsonify({
        "ok":True,
        "users":[dict(row) for row in rows]
    })


@app.route("/api/following/<int:user_id>")
def following(user_id):
    conn=sqlite3.connect(DB)
    conn.row_factory=sqlite3.Row

    rows=conn.execute("""
        SELECT users.id, users.name, users.username
        FROM follows
        JOIN users ON users.id=follows.following_id
        WHERE follows.follower_id=?
        ORDER BY follows.id DESC
    """,(user_id,)).fetchall()

    conn.close()

    return jsonify({
        "ok":True,
        "users":[dict(row) for row in rows]
    })


@app.route("/api/follow-count/<int:user_id>")
def follow_count(user_id):
    conn=sqlite3.connect(DB)

    followers=conn.execute(
        "SELECT COUNT(*) FROM follows WHERE following_id=?",
        (user_id,)
    ).fetchone()[0]

    following=conn.execute(
        "SELECT COUNT(*) FROM follows WHERE follower_id=?",
        (user_id,)
    ).fetchone()[0]

    conn.close()

    return jsonify({
        "ok": True,
        "followers": followers,
        "following": following
    })


@app.route("/api/users")
def users():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, name, mobile, username, created_at FROM users ORDER BY id DESC"
    ).fetchall()

    conn.close()

    return jsonify({
        "ok": True,
        "users": [dict(row) for row in rows]
    })


# ================= CHAT API =================

@app.route("/api/messages", methods=["POST"])
def send_message():
    data = request.get_json() or {}

    sender_id = data.get("sender_id")
    receiver_id = data.get("receiver_id")
    text = str(data.get("text", "")).strip()

    if not sender_id or not receiver_id or not text:
        return jsonify({"ok": False, "message": "sender_id, receiver_id और text जरूरी हैं"}), 400

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO messages (sender_id, receiver_id, text) VALUES (?, ?, ?)",
        (int(sender_id), int(receiver_id), text)
    )

    conn.commit()
    message_id = cur.lastrowid
    conn.close()

    return jsonify({
        "ok": True,
        "message": "Message sent",
        "message_id": message_id
    })


@app.route("/api/messages/<int:user_id>/<int:other_id>")
def get_messages(user_id, other_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT id, sender_id, receiver_id, text, created_at
        FROM messages
        WHERE (sender_id=? AND receiver_id=?)
           OR (sender_id=? AND receiver_id=?)
        ORDER BY id ASC
    """, (user_id, other_id, other_id, user_id)).fetchall()

    conn.close()

    return jsonify({
        "ok": True,
        "messages": [dict(row) for row in rows]
    })


# ================= WALLET / EARNING API =================

@app.route("/api/wallet/<int:user_id>")
def get_wallet(user_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    wallet = conn.execute(
        "SELECT user_id, balance, total_earned FROM wallets WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not wallet:
        conn.execute(
            "INSERT INTO wallets (user_id, balance, total_earned) VALUES (?, 0, 0)",
            (user_id,)
        )
        conn.commit()

        wallet = conn.execute(
            "SELECT user_id, balance, total_earned FROM wallets WHERE user_id=?",
            (user_id,)
        ).fetchone()

    conn.close()

    return jsonify({
        "ok": True,
        "wallet": dict(wallet)
    })


@app.route("/api/earning", methods=["POST"])
def add_earning():
    data = request.get_json() or {}

    user_id = data.get("user_id")
    amount = data.get("amount", 0)
    post_id = data.get("post_id")
    source = str(data.get("source", "creator"))

    try:
        amount = float(amount)
    except:
        return jsonify({"ok": False, "message": "Invalid amount"}), 400

    if not user_id or amount <= 0:
        return jsonify({"ok": False, "message": "user_id और valid amount जरूरी हैं"}), 400

    conn = sqlite3.connect(DB)

    conn.execute(
        "INSERT INTO earnings (user_id, post_id, amount, source, status) VALUES (?, ?, ?, ?, 'pending')",
        (int(user_id), post_id, amount, source)
    )

    conn.execute("""
        INSERT INTO wallets (user_id, balance, total_earned)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            balance = balance + excluded.balance,
            total_earned = total_earned + excluded.total_earned
    """, (int(user_id), amount, amount))

    conn.commit()

    wallet = conn.execute(
        "SELECT balance, total_earned FROM wallets WHERE user_id=?",
        (int(user_id),)
    ).fetchone()

    conn.close()

    return jsonify({
        "ok": True,
        "message": "Earning added",
        "wallet": {
            "balance": wallet[0],
            "total_earned": wallet[1]
        }
    })


@app.route("/api/withdrawals/<int:user_id>", methods=["GET"])
def get_withdrawals(user_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """SELECT id, user_id, amount, status, created_at
           FROM withdrawals
           WHERE user_id=?
           ORDER BY id DESC""",
        (user_id,)
    ).fetchall()

    conn.close()

    return jsonify({
        "ok": True,
        "withdrawals": [dict(row) for row in rows]
    })

@app.route("/api/withdraw", methods=["POST"])
def request_withdrawal():
    data = request.get_json() or {}

    user_id = data.get("user_id")

    try:
        amount = float(data.get("amount", 0))
    except:
        return jsonify({"ok": False, "message": "Invalid amount"}), 400

    if not user_id or amount <= 0:
        return jsonify({"ok": False, "message": "user_id और valid amount जरूरी हैं"}), 400

    conn = sqlite3.connect(DB)

    wallet = conn.execute(
        "SELECT balance FROM wallets WHERE user_id=?",
        (int(user_id),)
    ).fetchone()

    if not wallet:
        conn.close()
        return jsonify({"ok": False, "message": "Wallet नहीं मिला"}), 404

    if wallet[0] < amount:
        conn.close()
        return jsonify({"ok": False, "message": "Wallet balance कम है"}), 400

    conn.execute(
        "UPDATE wallets SET balance = balance - ? WHERE user_id=?",
        (amount, int(user_id))
    )

    conn.execute(
        "INSERT INTO withdrawals (user_id, amount, status) VALUES (?, ?, 'pending')",
        (int(user_id), amount)
    )

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "message": "Withdrawal request submitted"
    })


# ===== COMMENTS API =====

@app.route("/api/comments/<int:post_id>", methods=["GET"])
def get_comments(post_id):
    conn = sqlite3.connect("ns_master.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT comments.id, comments.post_id, comments.user_id,
               comments.text, comments.created_at,
               users.name, users.username, users.profile_photo
        FROM comments
        LEFT JOIN users ON users.id = comments.user_id
        WHERE comments.post_id = ?
        ORDER BY comments.id ASC
    """, (post_id,)).fetchall()
    conn.close()

    return jsonify({
        "ok": True,
        "comments": [dict(row) for row in rows]
    })


@app.route("/api/comments", methods=["POST"])
def add_comment():
    data = request.get_json(silent=True) or {}

    post_id = data.get("post_id")
    user_id = data.get("user_id")
    text = str(data.get("text", "")).strip()

    if not post_id or not user_id or not text:
        return jsonify({
            "ok": False,
            "error": "post_id, user_id and text are required"
        }), 400

    conn = sqlite3.connect("ns_master.db")
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO comments (post_id, user_id, text)
        VALUES (?, ?, ?)
    """, (post_id, user_id, text))

    comment_id = cur.lastrowid

    # Notification for post owner
    owner = cur.execute(
        "SELECT user_id FROM posts WHERE id = ?",
        (post_id,)
    ).fetchone()

    if owner and owner[0] and owner[0] != user_id:
        cur.execute("""
            INSERT INTO notifications
            (user_id, from_user_id, type, post_id, message)
            VALUES (?, ?, 'comment', ?, ?)
        """, (
            owner[0],
            user_id,
            post_id,
            "New comment on your post"
        ))

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "comment_id": comment_id
    })


# ===== NOTIFICATIONS API =====

@app.route("/api/notifications/<int:user_id>", methods=["GET"])
def get_notifications(user_id):
    conn = sqlite3.connect("ns_master.db")
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT notifications.id,
               notifications.user_id,
               notifications.from_user_id,
               notifications.type,
               notifications.post_id,
               notifications.message,
               notifications.is_read,
               notifications.created_at,
               users.name,
               users.username,
               users.profile_photo
        FROM notifications
        LEFT JOIN users ON users.id = notifications.from_user_id
        WHERE notifications.user_id = ?
        ORDER BY notifications.id DESC
    """, (user_id,)).fetchall()

    conn.close()

    return jsonify({
        "ok": True,
        "notifications": [dict(row) for row in rows]
    })


@app.route("/api/notifications/read/<int:notification_id>", methods=["POST"])
def mark_notification_read(notification_id):
    conn = sqlite3.connect("ns_master.db")

    conn.execute("""
        UPDATE notifications
        SET is_read = 1
        WHERE id = ?
    """, (notification_id,))

    conn.commit()
    conn.close()

    return jsonify({"ok": True})


@app.route("/api/notifications/read-all/<int:user_id>", methods=["POST"])
def mark_all_notifications_read(user_id):
    conn = sqlite3.connect("ns_master.db")

    conn.execute("""
        UPDATE notifications
        SET is_read = 1
        WHERE user_id = ?
    """, (user_id,))

    conn.commit()
    conn.close()

    return jsonify({"ok": True})


@app.route("/api/notifications/unread-count/<int:user_id>", methods=["GET"])
def unread_notification_count(user_id):
    conn = sqlite3.connect("ns_master.db")

    row = conn.execute("""
        SELECT COUNT(*)
        FROM notifications
        WHERE user_id = ? AND is_read = 0
    """, (user_id,)).fetchone()

    conn.close()

    return jsonify({
        "ok": True,
        "count": row[0]
    })


# ===== PROFILE PHOTO API =====

@app.route("/api/profile-photo", methods=["POST"])
def update_profile_photo():
    data = request.get_json(silent=True) or {}

    user_id = data.get("user_id")
    profile_photo = str(data.get("profile_photo", "")).strip()

    if not user_id or not profile_photo:
        return jsonify({
            "ok": False,
            "error": "user_id and profile_photo are required"
        }), 400

    conn = sqlite3.connect("ns_master.db")

    conn.execute("""
        UPDATE users
        SET profile_photo = ?
        WHERE id = ?
    """, (profile_photo, user_id))

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "message": "Profile photo updated"
    })


# ===== REELS API =====

@app.route("/api/reels", methods=["GET"])
def get_reels():
    conn = sqlite3.connect("ns_master.db")
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT posts.id,
               posts.user_id,
               posts.caption,
               posts.media,
               posts.media_type,
               posts.created_at,
               users.name,
               users.username,
               users.profile_photo
        FROM posts
        LEFT JOIN users ON users.id = posts.user_id
        WHERE posts.media_type = 'reel'
        ORDER BY posts.id DESC
    """).fetchall()

    conn.close()

    return jsonify({
        "ok": True,
        "reels": [dict(row) for row in rows]
    })


@app.route("/api/reels", methods=["POST"])
def create_reel():
    data = request.get_json(silent=True) or {}

    user_id = data.get("user_id")
    media = str(data.get("media", "")).strip()
    caption = str(data.get("caption", "")).strip()

    if not user_id or not media:
        return jsonify({
            "ok": False,
            "error": "user_id and media are required"
        }), 400

    conn = sqlite3.connect("ns_master.db")
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO posts
        (user_id, caption, media, media_type)
        VALUES (?, ?, ?, 'reel')
    """, (user_id, caption, media))

    reel_id = cur.lastrowid

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "reel_id": reel_id,
        "message": "Reel created successfully"
    })


@app.route("/api/user-reels/<int:user_id>", methods=["GET"])
def get_user_reels(user_id):
    conn = sqlite3.connect("ns_master.db")
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT id, user_id, caption, media, media_type, created_at
        FROM posts
        WHERE user_id = ? AND media_type = 'reel'
        ORDER BY id DESC
    """, (user_id,)).fetchall()

    conn.close()

    return jsonify({
        "ok": True,
        "reels": [dict(row) for row in rows]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5007)

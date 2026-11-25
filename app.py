# -*- coding: utf-8 -*-
"""
校园二手交易平台 —— 后端主程序

运行方式：双击 启动.bat，或者命令行执行 python app.py
然后浏览器打开 http://127.0.0.1:5000
"""

import hashlib
import json
import os
import random
import uuid
from datetime import datetime
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory, session
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

from models import Conversation, Message, Order, Product, User, db
from seed import seed_all, seed_demo_orders

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
# 目录不进 git（里面都是用户上传的图），所以要保证它自己会建出来
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# 预设标签库，前端的筛选面板从这里取
TAG_PRESET = [
    "数码", "摄影", "平板", "音频", "外设", "图书", "运动", "户外",
    "服饰", "鞋", "家居", "乐器", "音乐", "潮玩", "出行", "个护",
    "阅读", "游戏", "美妆", "其他",
]

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config.update(
    SECRET_KEY="market-demo-secret-key-please-change",
    SQLALCHEMY_DATABASE_URI="sqlite:///" + os.path.join(BASE_DIR, "market.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,      # 单张图最多 8MB
)
db.init_app(app)


# ---------------------------------------------------------------- 工具函数

def current_user():
    uid = session.get("uid")
    return db.session.get(User, uid) if uid else None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify({"error": "登录状态已失效，请重新登录"}), 401
        return fn(user, *args, **kwargs)

    return wrapper


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "图片太大了，请选 8MB 以内的图"}), 413


def ensure_columns():
    """给老的数据库补上后加的字段。

    直接删库重建最简单，但你电脑上可能已经有自己点出来的数据，删了可惜。
    所以这里检测一下缺哪一列就补哪一列（SQLite 支持 ADD COLUMN）。
    """
    insp = inspect(db.engine)
    todo = [
        ("conversations", "buyer_read_id", "INTEGER NOT NULL DEFAULT 0"),
        ("conversations", "seller_read_id", "INTEGER NOT NULL DEFAULT 0"),
        ("orders", "status", "VARCHAR(12) NOT NULL DEFAULT 'pending'"),
        ("orders", "status_at", "DATETIME"),
    ]
    for table, column, ddl in todo:
        if table not in insp.get_table_names():
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        if column not in existing:
            db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            print(f"数据库升级：{table} 增加 {column}")
    db.session.commit()

    # 老订单没有状态字段，补完之后统一当成"已完成"，避免它们卡在"待发货"
    db.session.execute(text("UPDATE orders SET status='done', status_at=created_at WHERE status_at IS NULL"))
    db.session.commit()


# 订单状态机：每个状态只允许走下面列出的那几步
ORDER_FLOW = {
    "pending": ["shipped", "cancelled"],
    "shipped": ["done"],
    "done": [],
    "cancelled": [],
}


# ---------------------------------------------------------------- 页面

@app.get("/")
def index():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "index.html")


# ---------------------------------------------------------------- 账号

@app.get("/api/tags")
def tags():
    return jsonify(TAG_PRESET)


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    avatar = data.get("avatar") or ""

    if len(username) < 2:
        return jsonify({"error": "用户名至少 2 个字"}), 400
    if len(password) < 6:
        return jsonify({"error": "密码至少 6 位"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "这个用户名已经有人用了"}), 400

    user = User(
        username=username,
        password_hash=generate_password_hash(password, method="pbkdf2:sha256"),
        avatar=avatar,
        balance=1000.0,       # 新用户送 1000 元，方便演示
    )
    db.session.add(user)
    db.session.commit()
    session["uid"] = user.id
    return jsonify(user.to_dict())


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user = User.query.filter_by(username=username).first()
    if user is None or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "用户名或密码不对"}), 400
    session["uid"] = user.id
    return jsonify(user.to_dict())


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
@login_required
def me(user):
    return jsonify(user.to_dict())


@app.put("/api/me")
@login_required
def update_me(user):
    data = request.get_json(silent=True) or {}

    if "username" in data:
        name = (data.get("username") or "").strip()
        if len(name) < 2:
            return jsonify({"error": "用户名至少 2 个字"}), 400
        exists = User.query.filter(User.username == name, User.id != user.id).first()
        if exists:
            return jsonify({"error": "这个用户名已经有人用了"}), 400
        user.username = name

    if data.get("password"):
        if len(data["password"]) < 6:
            return jsonify({"error": "密码至少 6 位"}), 400
        user.password_hash = generate_password_hash(data["password"], method="pbkdf2:sha256")

    if "avatar" in data:
        user.avatar = data.get("avatar") or ""

    db.session.commit()
    return jsonify(user.to_dict())


@app.post("/api/me/recharge")
@login_required
def recharge(user):
    data = request.get_json(silent=True) or {}
    amount = float(data.get("amount") or 0)
    if amount <= 0 or amount > 100000:
        return jsonify({"error": "充值金额不合法"}), 400
    user.balance = round(user.balance + amount, 2)
    db.session.commit()
    return jsonify(user.to_dict())


@app.post("/api/upload")
@login_required
def upload(_user):
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "没有收到文件"}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": "只支持 png / jpg / gif / webp 图片"}), 400
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    name = uuid.uuid4().hex + ext
    file.save(os.path.join(UPLOAD_DIR, name))
    return jsonify({"path": f"/static/uploads/{name}"})


# ---------------------------------------------------------------- 商品

@app.get("/api/products")
@login_required
def list_products(user):
    """首页商品：默认随机推荐（模拟算法），带筛选条件时只返回匹配的，支持翻页。

    这里有个容易被忽略的坑：随机 + 翻页 会打架。
    如果每次请求都重新 shuffle，第 2 页可能出现第 1 页已经看过的商品，
    甚至同一件商品出现两次。所以随机顺序要用一个固定种子算出来——
    同一个种子算出的顺序永远一样，翻页才稳定。

    种子的来源：前端第一次请求不带 seed，后端生成一个并随结果返回，
    之后翻页前端把它带上。之所以不用 session 存，是因为 session 靠 cookie，
    cookie 一丢顺序就变了，翻页立刻出现重复。"换一批"= 前端不带 seed 重新要。
    """
    query = Product.query.filter(Product.status == "on")

    min_price = request.args.get("min", type=float)
    max_price = request.args.get("max", type=float)
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    # 关键词搜索：只匹配商品名。故意不匹配描述，
    # 否则搜"iPad"可能翻出一堆只在描述里提了一句的无关商品。
    keyword = (request.args.get("q") or "").strip()
    if keyword:
        query = query.filter(Product.title.contains(keyword))

    items = query.all()

    wanted = [t for t in (request.args.get("tags") or "").split(",") if t]
    if wanted:
        # 命中任意一个标签就算匹配
        items = [p for p in items if set(wanted) & set(p.tag_list)]

    seed = request.args.get("seed")
    if not seed:
        seed = str(random.randint(1, 10 ** 9))
    items.sort(key=lambda p: hashlib.md5(f"{seed}:{p.id}".encode()).hexdigest())

    page = max(request.args.get("page", 1, type=int) or 1, 1)
    size = min(max(request.args.get("size", 12, type=int) or 12, 1), 48)
    total = len(items)
    chunk = items[(page - 1) * size: page * size]

    return jsonify(
        {
            "items": [p.to_dict(viewer_id=user.id) for p in chunk],
            "total": total,
            "page": page,
            "size": size,
            "has_more": page * size < total,
            "seed": seed,
        }
    )


@app.get("/api/my-products")
@login_required
def my_products(user):
    items = (
        Product.query.filter_by(owner_id=user.id)
        .order_by(Product.id.desc())
        .all()
    )
    return jsonify([p.to_dict(viewer_id=user.id) for p in items])


@app.post("/api/products")
@login_required
def create_product(user):
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    try:
        price = float(data.get("price") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "价格必须是数字"}), 400

    if not title:
        return jsonify({"error": "请填写商品名称"}), 400
    if price <= 0:
        return jsonify({"error": "价格需要大于 0"}), 400

    tags = data.get("tags") or []
    product = Product(
        title=title,
        price=round(price, 2),
        tags=json.dumps(tags, ensure_ascii=False),
        description=(data.get("description") or "").strip(),
        image=data.get("image") or "",
        status="off",            # 新增商品默认下架，由用户手动上架
        owner_id=user.id,
    )
    db.session.add(product)
    db.session.commit()
    return jsonify(product.to_dict(viewer_id=user.id))


@app.patch("/api/products/<int:pid>")
@login_required
def update_product(user, pid):
    """同一个接口负责两件事：改上下架状态、改商品信息（标题/价格/标签/描述/图）。

    改商品信息不会影响已经成交的订单——订单里存的是成交那一刻的快照，
    这正是当初多存那四个 snap_* 字段的意义。
    """
    product = db.session.get(Product, pid)
    if product is None:
        return jsonify({"error": "商品不存在"}), 404
    if product.owner_id != user.id:
        return jsonify({"error": "只能操作自己的商品"}), 403

    data = request.get_json(silent=True) or {}

    if "status" in data:
        if data["status"] not in ("on", "off"):
            return jsonify({"error": "状态不对"}), 400
        product.status = data["status"]

    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "商品名称不能为空"}), 400
        product.title = title

    if "price" in data:
        try:
            price = round(float(data["price"]), 2)
        except (TypeError, ValueError):
            return jsonify({"error": "价格必须是数字"}), 400
        if price <= 0:
            return jsonify({"error": "价格需要大于 0"}), 400
        product.price = price

    if "tags" in data:
        product.tags = json.dumps(data.get("tags") or [], ensure_ascii=False)

    if "description" in data:
        product.description = (data.get("description") or "").strip()

    if "image" in data:
        product.image = data.get("image") or ""

    db.session.commit()
    return jsonify(product.to_dict(viewer_id=user.id))


@app.delete("/api/products/<int:pid>")
@login_required
def delete_product(user, pid):
    product = db.session.get(Product, pid)
    if product is None:
        return jsonify({"error": "商品不存在"}), 404
    if product.owner_id != user.id:
        return jsonify({"error": "只能删除自己的商品"}), 403

    # 有成交记录的商品不允许删除，否则历史订单会查不到东西
    if Order.query.filter_by(product_id=pid).first():
        return jsonify({"error": "这件商品已经有成交记录，只能下架，不能删除"}), 400

    Conversation.query.filter_by(product_id=pid).delete()
    db.session.delete(product)
    db.session.commit()
    return jsonify({"ok": True})


@app.post("/api/products/<int:pid>/buy")
@login_required
def buy(user, pid):
    product = db.session.get(Product, pid)
    if product is None:
        return jsonify({"error": "商品不存在"}), 404
    if product.owner_id == user.id:
        return jsonify({"error": "不能购买自己的商品"}), 400
    if product.status != "on":
        return jsonify({"error": "这件商品已经下架或已售出"}), 400
    if user.balance < product.price:
        return jsonify({"error": f"余额不足，还差 ¥{product.price - user.balance:.2f}"}), 400

    seller = db.session.get(User, product.owner_id)

    # 下面这些操作必须在同一个事务里完成，否则可能出现"钱扣了东西没转"
    user.balance = round(user.balance - product.price, 2)
    seller.balance = round(seller.balance + product.price, 2)
    product.owner_id = user.id
    product.status = "off"        # 买到手默认下架，想再卖需要自己上架

    db.session.add(
        Order(
            product_id=product.id,
            buyer_id=user.id,
            seller_id=seller.id,
            deal_price=product.price,
            snap_title=product.title,
            snap_image=product.image,
            snap_desc=product.description,
            snap_tags=product.tags,
            status="pending",              # 刚付完钱，等卖家发货
            status_at=datetime.now(),
        )
    )
    db.session.commit()

    # 如果两人之前聊过，往会话里插一条系统提示。
    # 这样卖家在消息栏能直接看到"买家已拍下"，不用跑去订单页翻。
    conv = Conversation.query.filter_by(product_id=product.id, buyer_id=user.id).first()
    if conv is not None:
        db.session.add(
            Message(
                conversation_id=conv.id,
                sender_id=user.id,
                type="system",
                content=f"买家已拍下这件商品，成交价 ¥{product.price:.2f}，等待卖家发货",
            )
        )
        conv.updated_at = datetime.now()
        db.session.commit()

    return jsonify({"ok": True, "balance": user.balance})


# ---------------------------------------------------------------- 消息

def unread_count(conv, uid):
    """这个会话里有多少条我没看过的消息。

    判断方法：只看别人发的，且 id 大于我"已读到"的位置。
    不用给每条消息存已读状态，两个整数就够了。
    """
    read_id = conv.buyer_read_id if conv.buyer_id == uid else conv.seller_read_id
    return Message.query.filter(
        Message.conversation_id == conv.id,
        Message.id > (read_id or 0),
        Message.sender_id != uid,
    ).count()


def my_conversations(uid):
    return (
        Conversation.query.filter(
            (Conversation.buyer_id == uid) | (Conversation.seller_id == uid)
        )
        .order_by(Conversation.updated_at.desc())
        .all()
    )


@app.get("/api/conversations")
@login_required
def conversations(user):
    result = []
    for c in my_conversations(user.id):
        other = c.seller if c.buyer_id == user.id else c.buyer
        last = (
            Message.query.filter_by(conversation_id=c.id)
            .order_by(Message.id.desc())
            .first()
        )
        if last is None:
            preview = ""
        elif last.type == "offer":
            preview = f"[改价申请] ¥{last.price:g}"
        else:
            preview = last.content

        result.append(
            {
                "id": c.id,
                "product": {"id": c.product.id, "title": c.product.title, "image": c.product.image, "price": round(c.product.price, 2)},
                "other": {"id": other.id, "username": other.username, "avatar": other.avatar},
                "i_am_seller": c.seller_id == user.id,
                "last_message": preview,
                "unread": unread_count(c, user.id),
            }
        )
    return jsonify(result)


@app.get("/api/unread")
@login_required
def unread_total(user):
    """顶部导航那个小红点用的。单独开一个接口，是为了不用为了拿个数字拉全部会话。"""
    total = sum(unread_count(c, user.id) for c in my_conversations(user.id))
    return jsonify({"total": total})


@app.post("/api/conversations")
@login_required
def open_conversation(user):
    data = request.get_json(silent=True) or {}
    product = db.session.get(Product, data.get("product_id"))
    if product is None:
        return jsonify({"error": "商品不存在"}), 404
    if product.owner_id == user.id:
        return jsonify({"error": "这是你自己的商品，不用和自己聊"}), 400

    conv = Conversation.query.filter_by(product_id=product.id, buyer_id=user.id).first()
    if conv is None:
        conv = Conversation(
            product_id=product.id, buyer_id=user.id, seller_id=product.owner_id
        )
        db.session.add(conv)
        db.session.commit()
    return jsonify({"id": conv.id})


@app.get("/api/conversations/<int:cid>")
@login_required
def conversation_detail(user, cid):
    conv = db.session.get(Conversation, cid)
    if conv is None:
        return jsonify({"error": "会话不存在"}), 404
    if user.id not in (conv.buyer_id, conv.seller_id):
        return jsonify({"error": "无权查看这个会话"}), 403

    msgs = (
        Message.query.filter_by(conversation_id=cid)
        .order_by(Message.id.asc())
        .all()
    )

    # 打开会话就算看过了：把自己的"已读到"位置推到最新一条
    if msgs:
        latest = msgs[-1].id
        if conv.buyer_id == user.id and (conv.buyer_read_id or 0) < latest:
            conv.buyer_read_id = latest
            db.session.commit()
        elif conv.seller_id == user.id and (conv.seller_read_id or 0) < latest:
            conv.seller_read_id = latest
            db.session.commit()

    other = conv.seller if conv.buyer_id == user.id else conv.buyer
    return jsonify(
        {
            "id": conv.id,
            "i_am_seller": conv.seller_id == user.id,
            "other": {"id": other.id, "username": other.username, "avatar": other.avatar},
            "product": {
                "id": conv.product.id,
                "title": conv.product.title,
                "image": conv.product.image,
                "price": round(conv.product.price, 2),
                "status": conv.product.status,
            },
            "messages": [m.to_dict() for m in msgs],
        }
    )


@app.post("/api/conversations/<int:cid>/messages")
@login_required
def send_message(user, cid):
    conv = db.session.get(Conversation, cid)
    if conv is None:
        return jsonify({"error": "会话不存在"}), 404
    if user.id not in (conv.buyer_id, conv.seller_id):
        return jsonify({"error": "无权在这个会话里发言"}), 403

    data = request.get_json(silent=True) or {}

    if data.get("offer_price") is not None:
        try:
            price = round(float(data["offer_price"]), 2)
        except (TypeError, ValueError):
            return jsonify({"error": "价格必须是数字"}), 400
        if price <= 0:
            return jsonify({"error": "价格需要大于 0"}), 400
        if price >= conv.product.price:
            return jsonify({"error": f"改价申请需要低于当前价格 ¥{conv.product.price:g}"}), 400
        msg = Message(
            conversation_id=cid,
            sender_id=user.id,
            type="offer",
            content=f"申请把价格改成 ¥{price:g}",
            price=price,
        )
    else:
        text = (data.get("text") or "").strip()
        if not text:
            return jsonify({"error": "消息不能为空"}), 400
        if len(text) > 500:
            return jsonify({"error": "消息太长了"}), 400
        msg = Message(conversation_id=cid, sender_id=user.id, type="text", content=text)

    conv.updated_at = datetime.now()
    db.session.add(msg)
    db.session.commit()
    return jsonify(msg.to_dict())


@app.post("/api/messages/<int:mid>/accept")
@login_required
def accept_offer(user, mid):
    msg = db.session.get(Message, mid)
    if msg is None:
        return jsonify({"error": "消息不存在"}), 404
    conv = db.session.get(Conversation, msg.conversation_id)
    if user.id not in (conv.buyer_id, conv.seller_id):
        return jsonify({"error": "无权操作"}), 403
    if msg.sender_id == user.id:
        return jsonify({"error": "不能同意自己发出的申请"}), 400
    if msg.type != "offer":
        return jsonify({"error": "这条消息不是改价申请"}), 400
    if msg.accepted:
        return jsonify({"error": "这条申请已经处理过了"}), 400

    product = conv.product
    product.price = msg.price
    msg.accepted = True
    db.session.add(
        Message(
            conversation_id=conv.id,
            sender_id=user.id,
            type="system",
            content=f"已同意改价，商品现价 ¥{msg.price:g}",
        )
    )
    db.session.commit()
    return jsonify({"ok": True, "price": product.price})


# ---------------------------------------------------------------- 订单

@app.get("/api/orders")
@login_required
def orders(user):
    bought = Order.query.filter_by(buyer_id=user.id).order_by(Order.id.desc()).all()
    sold = Order.query.filter_by(seller_id=user.id).order_by(Order.id.desc()).all()
    return jsonify(
        {
            "bought": [o.to_dict() for o in bought],
            "sold": [o.to_dict() for o in sold],
            # 顶部待办数字：我还需要处理的订单有几单
            "todo_bought": sum(1 for o in bought if o.status == "shipped"),
            "todo_sold": sum(1 for o in sold if o.status == "pending"),
        }
    )


def _load_order(user, oid, role):
    """取出订单并检查身份。role='buyer' 表示只有买家能操作，'seller' 同理。"""
    order = db.session.get(Order, oid)
    if order is None:
        return None, (jsonify({"error": "订单不存在"}), 404)
    if role == "buyer" and order.buyer_id != user.id:
        return None, (jsonify({"error": "只有买家能操作这笔订单"}), 403)
    if role == "seller" and order.seller_id != user.id:
        return None, (jsonify({"error": "只有卖家能操作这笔订单"}), 403)
    return order, None


@app.post("/api/orders/<int:oid>/ship")
@login_required
def ship_order(user, oid):
    """卖家发货：待发货 → 待收货"""
    order, err = _load_order(user, oid, "seller")
    if err:
        return err
    if "shipped" not in ORDER_FLOW.get(order.status, []):
        return jsonify({"error": f"这笔订单现在是「{order.to_dict()['status_text']}」，不能发货"}), 400

    order.status = "shipped"
    order.status_at = datetime.now()
    db.session.commit()
    return jsonify(order.to_dict())


@app.post("/api/orders/<int:oid>/confirm")
@login_required
def confirm_order(user, oid):
    """买家确认收货：待收货 → 已完成"""
    order, err = _load_order(user, oid, "buyer")
    if err:
        return err
    if "done" not in ORDER_FLOW.get(order.status, []):
        return jsonify({"error": f"这笔订单现在是「{order.to_dict()['status_text']}」，不能确认收货"}), 400

    order.status = "done"
    order.status_at = datetime.now()
    db.session.commit()
    return jsonify(order.to_dict())


@app.post("/api/orders/<int:oid>/cancel")
@login_required
def cancel_order(user, oid):
    """买家取消订单（只在卖家发货前可以）。

    取消要把钱退回去、把商品还给卖家——这两件事必须一起做，
    只做其中一件就会出现"钱退了东西还在买家手里"这种对不上的情况。
    """
    order, err = _load_order(user, oid, "buyer")
    if err:
        return err
    if order.status == "shipped":
        return jsonify({"error": "卖家已经发货了，不能直接取消；收到货后确认即可"}), 400
    if order.status == "done":
        return jsonify({"error": "这笔订单已经完成了，不能取消"}), 400
    if "cancelled" not in ORDER_FLOW.get(order.status, []):
        return jsonify({"error": "这笔订单已经取消过了"}), 400

    buyer = db.session.get(User, order.buyer_id)
    seller = db.session.get(User, order.seller_id)
    product = db.session.get(Product, order.product_id)

    buyer.balance = round(buyer.balance + order.deal_price, 2)
    seller.balance = round(seller.balance - order.deal_price, 2)

    # 商品回到卖家手上，重新上架，别人还能买。
    # 加一个 owner 判断：万一买家在等发货期间已经把商品转卖给别人了，
    # 就不能再把商品从第三个人手里抢回来，只退钱。
    if product is not None and product.owner_id == buyer.id:
        product.owner_id = seller.id
        product.status = "on"

    order.status = "cancelled"
    order.status_at = datetime.now()
    db.session.commit()
    return jsonify({"ok": True, "balance": buyer.balance})


# ---------------------------------------------------------------- 启动

with app.app_context():
    db.create_all()
    ensure_columns()
    seed_all()
    seed_demo_orders()


if __name__ == "__main__":
    print("=" * 52)
    print("  校园二手交易平台已启动")
    print("  请在浏览器打开： http://127.0.0.1:5000")
    print("  演示账号： 小林 / 123456    老王 / 123456")
    print("  关闭这个黑窗口即可停止服务")
    print("=" * 52)

    import threading
    import webbrowser

    # 等服务起来再自动打开浏览器，省得用户手输地址
    threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(host="127.0.0.1", port=5000, debug=False)

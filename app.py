# -*- coding: utf-8 -*-
"""
校园二手交易平台 —— 后端主程序

运行方式：双击 启动.bat，或者命令行执行 python app.py
然后浏览器打开 http://127.0.0.1:5000
"""

import hashlib
import io
import json
import os
import random
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory, session
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

from models import (Comment, Conversation, Dispute, DisputeComment, DisputeVote,
                    Favorite, Follow, Message, Order, Product, ProductView, User, db)
from seed import seed_all, seed_demo_orders, seed_demo_disputes, backfill_seed_regions

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
# 目录不进 git（里面都是用户上传的图），所以要保证它自己会建出来
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALLOWED_VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v"}
IMAGE_MAX = 8 * 1024 * 1024       # 单张图最多 8MB
VIDEO_MAX = 50 * 1024 * 1024      # 单个视频最多 50MB

# 预设标签库，前端的筛选面板从这里取
TAG_PRESET = [
    "数码", "摄影", "平板", "音频", "外设", "图书", "运动", "户外",
    "服饰", "鞋", "家居", "乐器", "音乐", "潮玩", "出行", "个护",
    "阅读", "游戏", "美妆", "其他",
]

# 全国城市坐标表（city-coords.json 由 DataV 免费接口离线生成，见 static/geo/）。
# 城市名 → [lng, lat]。定位/距离全靠它算，纯本地查表不联网。
try:
    with open(os.path.join(BASE_DIR, "static", "geo", "city-coords.json"), encoding="utf-8") as _f:
        CITY_COORDS = json.load(_f)
except Exception:
    CITY_COORDS = {}

# 全国区县坐标表（make_district_coords.py 从 DataV 免费接口生成，见 static/geo/）。
# 结构 [{name: 区县名, city: 所属市, lng, lat}, ...]，定位结果反查"苏州市·姑苏区"用。
try:
    with open(os.path.join(BASE_DIR, "static", "geo", "district-coords.json"), encoding="utf-8") as _f:
        DISTRICT_ROWS = json.load(_f)
except Exception:
    DISTRICT_ROWS = []

# 市 → 省 映射（从区县表推出来），定位后把"IP属地"更新成定位地用
CITY2PROV = {}
for _r in DISTRICT_ROWS:
    if _r.get("city") and _r.get("province"):
        CITY2PROV.setdefault(_r["city"], _r["province"])


def coords_by_region(province, city):
    """按常住地查坐标：优先市名，直辖市(city='市辖区')用省名兜底。"""
    for key in (city, province):
        if key and key in CITY_COORDS:
            lng, lat = CITY_COORDS[key]
            return round(lat, 4), round(lng, 4)
    return None


def haversine_km(lat1, lng1, lat2, lng2):
    """两经纬度点间的球面距离（公里）。"""
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config.update(
    SECRET_KEY="market-demo-secret-key-please-change",
    SQLALCHEMY_DATABASE_URI="sqlite:///" + os.path.join(BASE_DIR, "market.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=60 * 1024 * 1024,     # 全局上限 60MB（视频最大 50MB + 请求开销）
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
    return jsonify({"error": "文件太大了：图片不超过 8MB，视频不超过 50MB"}), 413


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
        # 商品介绍的多图和视频（功能1），老库自动补
        ("products", "images", "TEXT NOT NULL DEFAULT '[]'"),
        ("products", "videos", "TEXT NOT NULL DEFAULT '[]'"),
        # 用户所在地区（省/市/县），商品所属地跟着卖家走
        ("users", "province", "VARCHAR(32) NOT NULL DEFAULT ''"),
        ("users", "city", "VARCHAR(32) NOT NULL DEFAULT ''"),
        ("users", "district", "VARCHAR(32) NOT NULL DEFAULT ''"),
        # 编辑主页资料项（昵称=username、头像=avatar 复用原字段）
        ("users", "bio", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("users", "gender", "VARCHAR(10) NOT NULL DEFAULT ''"),
        ("users", "birthday", "VARCHAR(20) NOT NULL DEFAULT ''"),
        ("users", "likes", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("users", "school", "VARCHAR(60) NOT NULL DEFAULT ''"),
        # 定位坐标（距离功能）
        ("users", "latitude", "REAL"),
        ("users", "longitude", "REAL"),
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

    # 编辑主页的资料项：简介 / 性别 / 生日 / 喜欢的 / 院校
    for key, maxlen in (("bio", 200), ("gender", 10), ("birthday", 20),
                        ("likes", 200), ("school", 60)):
        if key in data:
            user.__setattr__(key, (data.get(key) or "").strip()[:maxlen])

    # 所在地区：省/市/县 一起存，用于首页地区筛选和"同城好物"
    if "province" in data:
        user.province = (data.get("province") or "").strip()
        user.city = (data.get("city") or "").strip()
        user.district = (data.get("district") or "").strip()
        # 没有手动定位过时，按常住地自动配坐标（城市名查表）
        if user.latitude is None and user.longitude is None:
            c = coords_by_region(user.province, user.city)
            if c:
                user.latitude, user.longitude = c

    # 浏览器定位：直接写精确坐标（比城市中心点准得多）
    if "latitude" in data and "longitude" in data:
        try:
            lat, lng = float(data["latitude"]), float(data["longitude"])
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                user.latitude, user.longitude = round(lat, 6), round(lng, 6)
        except (TypeError, ValueError):
            pass

    db.session.commit()
    return jsonify(user.to_dict())


def _apply_location(user, lat, lng):
    """定位落点的公共逻辑：存本人坐标 + 更新省市区文字 + 其他演示账号重排。

    返回 (最近城市名|None, 最近区县{name,city}|None)，给界面显示用；
    距离计算用的是原始坐标，识别不准不影响距离精度。
    """
    import math

    user.latitude, user.longitude = round(lat, 6), round(lng, 6)

    # 找最近的城市中心（60km 内才算匹配上，不然显示"附近"）
    nearest, best = None, 60.0
    for name, (lng2, lat2) in CITY_COORDS.items():
        d = haversine_km(lat, lng, lat2, lng2)
        if d < best:
            nearest, best = name, d

    # 再反查最近的区/县中心（30km 内才算匹配上），显示"苏州市·姑苏区"
    near_district, best_d = None, 30.0
    for row in DISTRICT_ROWS:
        d = haversine_km(lat, lng, row["lat"], row["lng"])
        if d < best_d:
            best_d = d
            near_district = {"name": row["name"], "city": row["city"]}

    # 定位即"落籍"：IP 属地跟着定位走——定位人（和演示账号）的省市区文字
    # 更新为本次定位的省市县，主页 IP 徽标、商品卡地名、同城筛选全都一致。
    if nearest:
        prov = CITY2PROV.get(nearest)
        dist_name = near_district["name"] if near_district else (
            user.district if user.city == nearest else "")
        user.province = prov or user.province
        user.city = nearest
        user.district = dist_name
        for other in User.query.filter(User.id != user.id).all():
            other.province = prov or other.province
            other.city = nearest
            other.district = dist_name
    db.session.commit()
    return nearest, near_district


@app.post("/api/geo/locate")
@login_required
def geo_locate(user):
    """浏览器定位：前端拿到经纬度后调这里，存库并返回就近城市名。

    就近城市只是给界面显示"已定位·苏州市"用的，距离计算用原始坐标，
    所以城市识别不准也不影响距离的精度。
    """
    data = request.get_json(silent=True) or {}
    try:
        lat, lng = float(data.get("latitude")), float(data.get("longitude"))
    except (TypeError, ValueError):
        return jsonify({"error": "坐标格式不对"}), 400
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return jsonify({"error": "坐标超出范围"}), 400

    nearest, near_district = _apply_location(user, lat, lng)
    return jsonify({
        "ok": True,
        "near_city": nearest,
        "near_district": near_district,
        "region": {"province": user.province, "city": user.city, "district": user.district},
        "coords": [round(lat, 4), round(lng, 4)],
    })


def _is_lan_ip(ip):
    """内网/本机地址查不到位置，这种情况就查服务器自己的出口公网 IP。"""
    if not ip:
        return True
    if ip.startswith(("127.", "10.", "192.168.")):
        return True
    if ip.startswith("172."):
        try:
            return 16 <= int(ip.split(".")[1]) <= 31
        except (IndexError, ValueError):
            return True
    return False


@app.post("/api/geo/iplocate")
@login_required
def geo_iplocate(user):
    """IP 定位兜底：浏览器 Geolocation 只在 HTTPS 或 localhost 下开放，
    局域网里别的电脑用 http://192.168.x.x:5000 打开时定位会被浏览器直接禁掉。

    这时候按客户端的公网 IP 估个大概位置（精度只到城市级，够用）。
    客户端是内网 IP 时查不到，就查服务器自己的出口公网 IP——
    同一局域网（比如手机热点）下大家共用一个出口 IP，估出来就是热点的真实位置。
    """
    ip = (request.remote_addr or "").strip()
    query_ip = "" if _is_lan_ip(ip) else ip      # 空字符串 = 查本机出口 IP
    try:
        url = ("http://ip-api.com/json/" + query_ip +
               "?fields=status,lat,lon,city,regionName&lang=zh-CN")
        with urllib.request.urlopen(url, timeout=6) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        if info.get("status") != "success":
            return jsonify({"error": "IP 定位服务没查到位置"}), 502
        lat, lng = float(info["lat"]), float(info["lon"])
    except Exception:
        return jsonify({"error": "IP 定位服务不可用（服务器需要联网）"}), 502

    nearest, near_district = _apply_location(user, lat, lng)
    return jsonify({
        "ok": True,
        "mode": "ip",
        "near_city": nearest,
        "near_district": near_district,
        "region": {"province": user.province, "city": user.city, "district": user.district},
        "coords": [round(lat, 4), round(lng, 4)],
    })


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


# ---------------------------------------------------------------- 以图搜物

_IMG_FEAT_CACHE = {}      # {图片url: (mtime, 特征向量)}，商品图基本不变，缓存加速

def _image_feature(stream_or_path):
    """提取图片特征：4x4 分块的颜色均值/方差 + 整图 HSV 色相直方图。

    纯本地计算，不依赖外部 AI：同一件商品的照片（哪怕角度/明暗不同）
    颜色分布是相近的，用向量夹角就能排出"长得像"的商品。
    """
    import numpy as np
    from PIL import Image

    img = Image.open(stream_or_path).convert("RGB")
    img.thumbnail((256, 256))
    arr = np.asarray(img, dtype=np.float32) / 255.0

    feats = []
    h, w, _ = arr.shape
    G = 4
    for gy in range(G):
        for gx in range(G):
            block = arr[gy * h // G:(gy + 1) * h // G, gx * w // G:(gx + 1) * w // G]
            flat = block.reshape(-1, 3)
            feats.extend(flat.mean(axis=0))
            feats.extend(flat.std(axis=0) * 0.5)
    # HSV 色相直方图（18 桶，按饱和度过滤掉灰白背景像素）
    hsv = np.asarray(img.convert("HSV"), dtype=np.float32)
    hue = hsv[:, :, 0].reshape(-1)
    sat = hsv[:, :, 1].reshape(-1) / 255.0
    hist, _ = np.histogram(hue[sat > 0.2], bins=18, range=(0, 256))
    if hist.sum() > 0:
        hist = hist / hist.sum()
    feats.extend(hist * 2.0)
    v = np.array(feats, dtype=np.float32)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def _product_image_path(url):
    """把商品图 url（/static/...）转回磁盘路径；不存在返回 None。"""
    if not url or not url.startswith("/static/"):
        return None
    path = os.path.join(BASE_DIR, "static", url[len("/static/"):].replace("/", os.sep))
    return path if os.path.exists(path) else None


def _product_feature(url):
    """商品图特征（按磁盘 mtime 缓存，图片换了会自动重算）。"""
    path = _product_image_path(url)
    if path is None:
        return None
    mtime = os.path.getmtime(path)
    hit = _IMG_FEAT_CACHE.get(url)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        with open(path, "rb") as f:
            feat = _image_feature(f)
    except Exception:
        return None
    _IMG_FEAT_CACHE[url] = (mtime, feat)
    return feat


def _vlm_config():
    """读云端视觉模型配置（项目根目录 vision_config.json）。

    格式：{"base_url": "...", "api_key": "...", "model": "..."}
    默认按智谱 GLM-4V-Flash（免费）的接口地址预填，用户只填 api_key 就能用。
    没有配置文件 / 没填 key → 返回 None，接口自动退回本地颜色特征匹配。
    """
    path = os.path.join(BASE_DIR, "vision_config.json")
    if not os.path.exists(path):
        return None
    try:
        cfg = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    if not cfg.get("api_key"):
        return None
    return {
        "base_url": cfg.get("base_url", "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
        "api_key": cfg["api_key"],
        "model": cfg.get("model", "glm-4v-flash"),
    }


_VLM_PROMPT = (
    "你是二手交易平台的图片识别助手。看图里主要的商品是什么，"
    '只输出一行 JSON：{"品类":"数码/家电/图书/服饰/运动/乐器/其他",'
    '"商品名":"简短名称，如 游戏鼠标、机械键盘",'
    '"关键词":["用于搜索的词，3~6个，如 鼠标,电竞,游戏外设"],'
    '"描述":"一句话说明画面内容"}'
)


def _vlm_recognize(cfg, image_bytes):
    """调云端多模态大模型识别图片里的商品，返回 dict 或 None（失败不抛异常）。"""
    import base64
    import io as _io
    import json as _json
    import urllib.request
    from PIL import Image

    # 先压缩：截图/照片往往很大，压到 768px 以内的 JPEG，省流量也快
    try:
        img = Image.open(_io.BytesIO(image_bytes)).convert("RGB")
        img.thumbnail((768, 768))
        buf = _io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None

    body = _json.dumps({
        "model": cfg["model"],
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": _VLM_PROMPT},
            ],
        }],
        "temperature": 0.1,
    }).encode()

    req = urllib.request.Request(
        cfg["base_url"],
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = _json.loads(resp.read().decode())
        text = data["choices"][0]["message"]["content"].strip()
        # 模型偶尔会包 ```json ... ```，剥掉
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        out = _json.loads(text[start:end + 1])
        return out if out.get("商品名") or out.get("关键词") else None
    except Exception:
        return None


def _keyword_search(user, recog):
    """拿大模型识别出的商品名/关键词去匹配站内在售商品。

    打分：商品名命中 50 分，品类/关键词命中标题 20 分、标签 12 分、描述 6 分，
    归一成 0~100 的"匹配度"展示。全词命中≈100%，一个词没中≈0。
    """
    name = (recog.get("商品名") or "").strip()
    cat = (recog.get("品类") or "").strip()
    kws = [k.strip() for k in (recog.get("关键词") or []) if k and k.strip()]
    if not name and not kws:
        return []
    terms = []
    if name:
        terms.append((name, 50))
    if cat:
        terms.append((cat, 8))
    for k in kws:
        terms.append((k, 20))
    best_possible = 50 + 8 + 20 * max(1, len(kws))

    scored = []
    for p in Product.query.filter_by(status="on").all():
        hay_title, hay_tags, hay_desc = p.title, " ".join(p.tag_list or []), p.description or ""
        score = 0.0
        for term, weight in terms:
            if not term:
                continue
            if term in hay_title:
                score += weight
            elif term in hay_tags:
                score += weight * 0.6
            elif term in hay_desc:
                score += weight * 0.3
        if score > 0:
            scored.append((min(1.0, score / best_possible), p))
    scored.sort(key=lambda t: -t[0])
    results = []
    # 匹配度按相对最高分折算（第一名 100%，其余按相关度比例），比绝对分好读
    top = scored[0][0] if scored else 0
    for ratio, p in scored[:12]:
        d = p.to_dict(viewer_id=user.id)
        d["similarity"] = round(ratio / top * 100) if top > 0 else 0
        results.append(d)
    return results


@app.post("/api/search/image")
@login_required
def search_by_image(user):
    """以图搜物：优先走云端大模型"看图识别 → 关键词搜站内"，
    没配 vision_config.json 或网络失败时，退回本地颜色特征匹配。"""
    import numpy as np

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "没有收到图片"}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": "只支持 png / jpg / jpeg / webp 图片"}), 400
    image_bytes = file.read()
    try:
        qfeat = _image_feature(io.BytesIO(image_bytes))
    except Exception:
        return jsonify({"error": "图片解析失败，换一张试试"}), 400

    # —— 第一选择：大模型识别 ——
    cfg = _vlm_config()
    if cfg:
        recog = _vlm_recognize(cfg, image_bytes)
        if recog:
            results = _keyword_search(user, recog)
            if results:
                return jsonify({
                    "mode": "ai",
                    "recognition": {
                        "name": recog.get("商品名", ""),
                        "category": recog.get("品类", ""),
                        "keywords": recog.get("关键词", []),
                        "desc": recog.get("描述", ""),
                    },
                    "count": len(results),
                    "results": results,
                })

    # —— 兜底：本地颜色特征匹配（离线可用） ——
    scored = []
    for p in Product.query.filter_by(status="on").all():
        imgs = p.image_list or ([p.image] if p.image else [])
        best = None
        for img in imgs:
            f = _product_feature(img)
            if f is not None:
                sim = float(np.dot(qfeat, f))    # 向量已归一化，点积=余弦相似度
                best = sim if best is None else max(best, sim)
        if best is not None:
            scored.append((best, p))
    scored.sort(key=lambda t: -t[0])
    results = []
    for sim, p in scored[:12]:
        d = p.to_dict(viewer_id=user.id)
        d["similarity"] = round(max(0.0, min(1.0, sim)) * 100)
        results.append(d)
    return jsonify({"mode": "color", "count": len(results), "results": results})


@app.post("/api/upload")
@login_required
def upload(_user):
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "没有收到文件"}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    is_video = ext in ALLOWED_VIDEO_EXT
    if ext not in ALLOWED_EXT and not is_video:
        return jsonify({"error": "图片支持 png / jpg / gif / webp，视频支持 mp4 / webm / mov"}), 400
    # 全局上限是 60MB，这里按类型卡得更细
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if is_video and size > VIDEO_MAX:
        return jsonify({"error": "视频太大了，请控制在 50MB 以内"}), 400
    if not is_video and size > IMAGE_MAX:
        return jsonify({"error": "图片太大了，请选 8MB 以内的图"}), 400
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

    # —— 地区筛选：商品的"所属地"就是卖家所在的省/市/县 ——
    # 传了 province 就按卖家地区过滤（可只到省，也可以精确到市/县）；
    # 传了 local=1 则开启"同城好物"：只看同省商品，省外一律不展示，
    # 排序优先级为 县(同区) > 市(同市) > 省内(同省其他市)。
    prov = (request.args.get("province") or "").strip()
    city = (request.args.get("city") or "").strip()
    dist = (request.args.get("district") or "").strip()
    local = request.args.get("local", type=int) or 0

    if local:
        if not (user.province and user.city and user.district):
            return jsonify({"error": "请先在「用户中心 → 修改资料」里设置你的所在地区"}), 400
        query = query.join(User, Product.owner_id == User.id).filter(
            User.province == user.province
        )
    elif prov:
        query = query.join(User, Product.owner_id == User.id).filter(User.province == prov)
        if city:
            query = query.filter(User.city == city)
            if dist:
                query = query.filter(User.district == dist)

    items = query.all()

    wanted = [t for t in (request.args.get("tags") or "").split(",") if t]
    if wanted:
        # 命中任意一个标签就算匹配
        items = [p for p in items if set(wanted) & set(p.tag_list)]

    # 同城好物：地域档位（县>市>省内）。真正和随机种子合成一个排序键，
    # 放到下面统一排，避免被种子排序覆盖
    region_rank = None
    if local:
        def region_rank(p):
            o = p.owner
            if user.district and o.district == user.district:
                return 0          # 同县（区）：最高优先级
            if user.city and o.city == user.city:
                return 1          # 同市：次优先
            return 2              # 同省其他市：兜底

    seed = request.args.get("seed")
    if not seed:
        seed = str(random.randint(1, 10 ** 9))

    # —— 距离：我有坐标、卖家也有坐标才算得出（haversine 球面距离）。
    # 自己发布的商品不给距离：显示"距你 0km"没意义，距离排序时也不该霸榜 ——
    def dist_of(p):
        o = p.owner
        if p.owner_id == user.id:
            return None
        if user.latitude is None or user.longitude is None:
            return None
        if o.latitude is None or o.longitude is None:
            return None
        return haversine_km(user.latitude, user.longitude, o.latitude, o.longitude)

    distances = {p.id: dist_of(p) for p in items}
    sort_mode = (request.args.get("sort") or "").strip()

    # 随机顺序 + 翻页稳定：同一个种子算出的顺序永远一样。
    # "同城好物"时用 (地域档位, 距离) 复合排序：先按县>市>省内分档，
    # 同档内有坐标就按距离由近到远，没坐标退回随机种子的顺序，翻页不重复不跳。
    if sort_mode == "distance":
        # 距离最近：没定位/卖家没坐标的排最后，其余由近到远
        items.sort(key=lambda p: (distances[p.id] is None, distances[p.id] if distances[p.id] is not None else 0))
    elif region_rank is not None and user.latitude is not None:
        items.sort(key=lambda p: (
            region_rank(p),
            distances[p.id] if distances[p.id] is not None else 9e9,
            hashlib.md5(f"{seed}:{p.id}".encode()).hexdigest(),
        ))
    elif region_rank is not None:
        items.sort(key=lambda p: (region_rank(p), hashlib.md5(f"{seed}:{p.id}".encode()).hexdigest()))
    else:
        items.sort(key=lambda p: hashlib.md5(f"{seed}:{p.id}".encode()).hexdigest())

    page = max(request.args.get("page", 1, type=int) or 1, 1)
    size = min(max(request.args.get("size", 12, type=int) or 12, 1), 48)
    total = len(items)
    chunk = items[(page - 1) * size: page * size]

    result_items = []
    for p in chunk:
        d = p.to_dict(viewer_id=user.id)
        dkm = distances.get(p.id)
        d["distance_km"] = round(dkm, 1) if dkm is not None else None
        result_items.append(d)

    return jsonify(
        {
            "items": result_items,
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
        images=json.dumps(data.get("images") or [], ensure_ascii=False),
        videos=json.dumps(data.get("videos") or [], ensure_ascii=False),
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

    if "images" in data:
        product.images = json.dumps(data.get("images") or [], ensure_ascii=False)

    if "videos" in data:
        product.videos = json.dumps(data.get("videos") or [], ensure_ascii=False)

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


@app.get("/api/products/<int:pid>")
@login_required
def product_detail(user, pid):
    """商品详情页数据：商品全量信息 + 卖家资料 + 评论列表。

    顺手记录浏览历史（看自己的商品不记）：同一个商品只保留一条记录，
    再看一次就把它顶到最前面；每个用户最多留 20 条，超了自动淘汰最早的。
    """
    product = db.session.get(Product, pid)
    if product is None:
        return jsonify({"error": "商品不存在"}), 404

    if product.owner_id != user.id:
        _record_view(user.id, pid)

    data = product.to_dict(viewer_id=user.id)
    data["comments"] = _comment_dicts(pid, user.id)
    data["seller_followers"] = Follow.query.filter_by(followed_id=product.owner_id).count()
    data["is_following"] = (
        Follow.query.filter_by(follower_id=user.id, followed_id=product.owner_id).first()
        is not None
    )
    data["is_favorited"] = (
        Favorite.query.filter_by(user_id=user.id, product_id=pid).first() is not None
    )
    return jsonify(data)


HISTORY_LIMIT = 20      # 每个用户最多保留多少条浏览记录


def _record_view(uid, pid):
    """记一条浏览：同一商品只留一条（旧的重复行清掉），并淘汰超出 20 条的旧记录。"""
    existing = (
        ProductView.query.filter_by(user_id=uid, product_id=pid)
        .order_by(ProductView.id.desc())
        .all()
    )
    if existing:
        # 已经看过：把最新一条顶到最前面，其余重复行删掉
        existing[0].viewed_at = datetime.now()
        for stale in existing[1:]:
            db.session.delete(stale)
    else:
        db.session.add(ProductView(user_id=uid, product_id=pid))
    db.session.commit()

    keep_ids = [
        row[0]
        for row in ProductView.query.filter_by(user_id=uid)
        .order_by(ProductView.viewed_at.desc(), ProductView.id.desc())
        .limit(HISTORY_LIMIT)
        .with_entities(ProductView.id)
        .all()
    ]
    if keep_ids:
        ProductView.query.filter(
            ProductView.user_id == uid, ~ProductView.id.in_(keep_ids)
        ).delete(synchronize_session=False)
        db.session.commit()


def _comment_dicts(pid, viewer_id):
    """把评论组织成两层：普通评论在前，卖家回复嵌在每条评论下面。"""
    roots = (
        Comment.query.filter_by(product_id=pid, reply_to_id=None)
        .order_by(Comment.id.desc())
        .all()
    )
    result = []
    for c in roots:
        replies = (
            Comment.query.filter_by(reply_to_id=c.id)
            .order_by(Comment.id.asc())
            .all()
        )
        result.append({
            "id": c.id,
            "user": {"id": c.user.id, "username": c.user.username, "avatar": c.user.avatar},
            "content": c.content,
            "created_at": c.created_at.strftime("%m-%d %H:%M"),
            "is_mine": c.user_id == viewer_id,
            "replies": [
                {
                    "id": r.id,
                    "user": {"id": r.user.id, "username": r.user.username, "avatar": r.user.avatar},
                    "content": r.content,
                    "created_at": r.created_at.strftime("%m-%d %H:%M"),
                }
                for r in replies
            ],
        })
    return result


@app.post("/api/products/<int:pid>/comments")
@login_required
def add_comment(user, pid):
    """发表评论；带 reply_to_id 表示卖家回复某条评论。

    规则：所有人都能评论，但只有商品卖家能发回复——这是"商家回复"功能。
    """
    product = db.session.get(Product, pid)
    if product is None:
        return jsonify({"error": "商品不存在"}), 404

    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "评论内容不能为空"}), 400
    if len(content) > 500:
        return jsonify({"error": "评论太长了"}), 400

    reply_to_id = data.get("reply_to_id")
    if reply_to_id is not None:
        parent = db.session.get(Comment, reply_to_id)
        if parent is None or parent.product_id != pid:
            return jsonify({"error": "要回复的评论不存在"}), 400
        if product.owner_id != user.id:
            return jsonify({"error": "只有卖家可以回复评论"}), 403

    db.session.add(
        Comment(product_id=pid, user_id=user.id, content=content, reply_to_id=reply_to_id)
    )
    db.session.commit()
    return jsonify({"ok": True, "comments": _comment_dicts(pid, user.id)})


# ---------------------------------------------------------------- 关注 / 收藏 / 浏览历史

@app.get("/api/mine/summary")
@login_required
def mine_summary(user):
    """"我的"总览页的数字角标：一次请求拿齐所有入口的计数，避免页面发 5 个请求。"""
    return jsonify({
        "products": Product.query.filter_by(owner_id=user.id).count(),
        "sold": Order.query.filter_by(seller_id=user.id).count(),
        "bought": Order.query.filter_by(buyer_id=user.id).count(),
        "favorites": Favorite.query.filter_by(user_id=user.id).count(),
        "history": ProductView.query.filter_by(user_id=user.id).count(),
        "following": Follow.query.filter_by(follower_id=user.id).count(),
        "followers": Follow.query.filter_by(followed_id=user.id).count(),
    })


@app.post("/api/users/<int:uid>/follow")
@login_required
def follow_user(user, uid):
    """关注一个卖家。重复关注是幂等的，粉丝数每次都返回最新值。"""
    target = db.session.get(User, uid)
    if target is None:
        return jsonify({"error": "用户不存在"}), 404
    if target.id == user.id:
        return jsonify({"error": "不能关注你自己"}), 400

    if not Follow.query.filter_by(follower_id=user.id, followed_id=uid).first():
        db.session.add(Follow(follower_id=user.id, followed_id=uid))
        db.session.commit()
    return jsonify({
        "ok": True,
        "following": True,
        "followers": Follow.query.filter_by(followed_id=uid).count(),
    })


@app.delete("/api/users/<int:uid>/follow")
@login_required
def unfollow_user(user, uid):
    target = db.session.get(User, uid)
    if target is None:
        return jsonify({"error": "用户不存在"}), 404
    Follow.query.filter_by(follower_id=user.id, followed_id=uid).delete()
    db.session.commit()
    return jsonify({
        "ok": True,
        "following": False,
        "followers": Follow.query.filter_by(followed_id=uid).count(),
    })


@app.get("/api/me/following")
@login_required
def my_following(user):
    """我关注的卖家列表，供"我的-我的关注"页使用。"""
    rows = Follow.query.filter_by(follower_id=user.id).order_by(Follow.id.desc()).all()
    result = []
    for f in rows:
        u = db.session.get(User, f.followed_id)
        if u is None:
            continue
        result.append({
            "id": u.id,
            "username": u.username,
            "avatar": u.avatar,
            "followers": Follow.query.filter_by(followed_id=u.id).count(),
            "on_sale": Product.query.filter_by(owner_id=u.id, status="on").count(),
        })
    return jsonify(result)


@app.get("/api/me/followers")
@login_required
def my_followers(user):
    """关注我的人，供"我的-我的粉丝"页使用。

    和关注列表的区别：这里每个人还要带上「我有没有回关他」（is_following），
    页面上才能显示「回关 / 已互关」而不是笼统的一个按钮。
    """
    rows = Follow.query.filter_by(followed_id=user.id).order_by(Follow.id.desc()).all()
    result = []
    for f in rows:
        u = db.session.get(User, f.follower_id)
        if u is None:
            continue
        result.append({
            "id": u.id,
            "username": u.username,
            "avatar": u.avatar,
            "followers": Follow.query.filter_by(followed_id=u.id).count(),
            "on_sale": Product.query.filter_by(owner_id=u.id, status="on").count(),
            "is_following": Follow.query.filter_by(
                follower_id=user.id, followed_id=u.id
            ).first() is not None,
        })
    return jsonify(result)


def credit_info(done_count):
    """按已完成订单数给个信用档位（课程作业演示用，没有真实评分体系）。"""
    if done_count <= 0:
        return {"level": "萌新", "deals": 0, "rate": "暂无成交"}
    level = "优秀" if done_count >= 6 else ("良好" if done_count >= 2 else "新手")
    return {"level": level, "deals": done_count, "rate": "好评 100%"}


@app.get("/api/users/<int:uid>/profile")
@login_required
def user_profile(user, uid):
    """卖家小铺主页：资料 + 粉丝数据 + 在售商品 + 信用/评价/动态。"""
    u = db.session.get(User, uid)
    if u is None:
        return jsonify({"error": "用户不存在"}), 404

    products = (
        Product.query.filter_by(owner_id=uid, status="on")
        .order_by(Product.id.desc())
        .all()
    )

    # 评价：别人在他商品下留的言（不算卖家自己的回复）
    pids = [p.id for p in Product.query.filter_by(owner_id=uid).all()]
    c_query = (
        Comment.query.filter(Comment.product_id.in_(pids), Comment.reply_to_id.is_(None))
        .order_by(Comment.id.desc())
    )
    comments_count = c_query.count()
    comments = []
    for c in c_query.limit(20).all():
        p = db.session.get(Product, c.product_id)
        comments.append({
            "id": c.id,
            "content": c.content,
            "created_at": c.created_at.strftime("%Y-%m-%d"),
            "user": {"id": c.user.id, "username": c.user.username, "avatar": c.user.avatar},
            "product": {"id": p.id, "title": p.title} if p else None,
        })

    # 动态：他卖出的宝贝（已完成订单，用成交快照展示）
    sold_q = (
        Order.query.filter_by(seller_id=uid, status="done")
        .order_by(Order.id.desc())
    )
    sold_count = sold_q.count()
    sold = [{
        "id": o.id,
        "title": o.snap_title,
        "image": o.snap_image,
        "price": o.deal_price,
        "date": o.status_at.strftime("%Y-%m-%d") if o.status_at else "",
    } for o in sold_q.limit(20).all()]

    bought_done = Order.query.filter_by(buyer_id=uid, status="done").count()
    sold_done = Order.query.filter_by(seller_id=uid, status="done").all()
    buyer = credit_info(bought_done)
    seller = credit_info(len(sold_done))

    return jsonify({
        "id": u.id,
        "username": u.username,
        "avatar": u.avatar,
        "region": u.region_text,
        "region_short": u.city or u.province or "",
        "bio": u.bio or "",
        "gender": u.gender or "",
        "birthday": u.birthday or "",
        "likes": u.likes or "",
        "school": u.school or "",
        "followers": Follow.query.filter_by(followed_id=uid).count(),
        "following": Follow.query.filter_by(follower_id=uid).count(),
        "on_sale_count": len(products),
        "buyer_credit": buyer,
        "seller_credit": seller,
        "comments_count": comments_count,
        "comments": comments,
        "sold_count": sold_count,
        "sold": sold,
        "is_following": Follow.query.filter_by(follower_id=user.id, followed_id=uid).first()
        is not None,
        "is_me": uid == user.id,
        "products": [p.to_dict(viewer_id=user.id) for p in products],
    })


@app.post("/api/products/<int:pid>/favorite")
@login_required
def favorite_product(user, pid):
    product = db.session.get(Product, pid)
    if product is None:
        return jsonify({"error": "商品不存在"}), 404
    if not Favorite.query.filter_by(user_id=user.id, product_id=pid).first():
        db.session.add(Favorite(user_id=user.id, product_id=pid))
        db.session.commit()
    return jsonify({"ok": True, "favorited": True})


@app.delete("/api/products/<int:pid>/favorite")
@login_required
def unfavorite_product(user, pid):
    Favorite.query.filter_by(user_id=user.id, product_id=pid).delete()
    db.session.commit()
    return jsonify({"ok": True, "favorited": False})


@app.get("/api/favorites")
@login_required
def list_favorites(user):
    """我收藏的商品，按收藏时间倒序。"""
    favs = Favorite.query.filter_by(user_id=user.id).order_by(Favorite.id.desc()).all()
    items = []
    for f in favs:
        p = db.session.get(Product, f.product_id)
        if p is not None:
            items.append(p.to_dict(viewer_id=user.id))
    return jsonify(items)


@app.get("/api/history")
@login_required
def list_history(user):
    """我的浏览记录（最多 20 条，后端写入时已经自动淘汰旧记录）。"""
    rows = (
        ProductView.query.filter_by(user_id=user.id)
        .order_by(ProductView.viewed_at.desc(), ProductView.id.desc())
        .limit(HISTORY_LIMIT)
        .all()
    )
    items = []
    for v in rows:
        p = db.session.get(Product, v.product_id)
        if p is None:
            continue
        d = p.to_dict(viewer_id=user.id)
        d["viewed_at"] = v.viewed_at.strftime("%m-%d %H:%M") if v.viewed_at else ""
        items.append(d)
    return jsonify(items)


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
        # 改价只对"还挂在这个卖家名下"的商品有意义。
        # 一旦成交，buy() 会把商品过户到买家名下（product.owner_id 变了），
        # 这个会话就变成了历史会话——再改价改的是别人正在卖的东西，必须拦住。
        if conv.product.owner_id != conv.seller_id:
            return jsonify({"error": "这件商品已经成交，不能再申请改价了"}), 400
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
    # 同上：商品已经不在卖家名下，说明已经成交，旧申请不能再被"同意"
    if conv.product.owner_id != conv.seller_id:
        return jsonify({"error": "这件商品已经成交，这条改价申请已失效"}), 400
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


# ---------------------------------------------------------------- 小法庭
#
# 闲鱼式的"小法庭"：买卖双方有矛盾就开一庭，写下各自的陈述，
# 围观群众在期限内投票站买家/站卖家，到期按票数宣判——
# 买家胜诉 → 订单退款取消（钱退买家、商品回卖家手上）；
# 卖家胜诉 → 订单直接完成（货款归卖家）；
# 平票 → 各退一步，订单维持原状。判决在有人访问案件时懒执行，不用后台定时器。

DISPUTE_DAYS = [1, 3, 5, 7]          # 发起时可选的审理期限（天）
DISPUTE_DELETE_ROLES = True          # 发起人/当事双方都可以删案


def _judge_if_due(d):
    """期限一到就宣判。在列表/详情接口里懒执行，不用起后台定时器。"""
    if d.status != "open" or datetime.now() < d.deadline:
        return
    b, s = d.vote_counts()
    d.status = "closed"
    d.verdict = "buyer" if b > s else ("seller" if s > b else "draw")

    order = db.session.get(Order, d.order_id) if d.order_id else None
    # 有订单才谈得上"满足胜利者的需求"；纯口角案只记录投票结果
    if d.verdict == "buyer" and order and order.status in ("pending", "shipped"):
        buyer = db.session.get(User, order.buyer_id)
        seller = db.session.get(User, order.seller_id)
        product = db.session.get(Product, order.product_id)
        buyer.balance = round(buyer.balance + order.deal_price, 2)
        seller.balance = round(seller.balance - order.deal_price, 2)
        if product is not None and product.owner_id == order.buyer_id:
            product.owner_id = order.seller_id
            product.status = "on"
        order.status = "cancelled"
        order.status_at = datetime.now()
        d.verdict_note = f"买家以 {b}:{s} 胜诉，订单已退款取消"
    elif d.verdict == "seller" and order and order.status in ("pending", "shipped"):
        order.status = "done"
        order.status_at = datetime.now()
        d.verdict_note = f"卖家以 {s}:{b} 胜诉，订单已完成，货款归卖家"
    elif d.verdict == "draw":
        d.verdict_note = f"双方 {b}:{s} 战平，各退一步，订单维持原状"
    else:
        d.verdict_note = f"投票结果 买家{b} : 卖家{s}"
    db.session.commit()


def _load_dispute(did):
    d = db.session.get(Dispute, did)
    if d is None:
        return None, (jsonify({"error": "案件不存在"}), 404)
    return d, None


@app.get("/api/court")
@login_required
def court_list(user):
    # 先把到期的案子都判了再列出来，保证列表里看到的永远是最新状态
    for d in Dispute.query.filter_by(status="open").all():
        _judge_if_due(d)
    items = Dispute.query.order_by(Dispute.id.desc()).all()
    out = []
    for d in items:
        row = d.to_dict()
        row["is_participant"] = user.id in (d.buyer_id, d.seller_id)
        out.append(row)
    return jsonify({"items": out})


@app.post("/api/court")
@login_required
def court_create(user):
    """发起小法庭：从自己的一笔订单发起（买家或卖家都行），写陈词、定审理期限。"""
    data = request.get_json(silent=True) or {}
    order = db.session.get(Order, data.get("order_id") or 0)
    if order is None:
        return jsonify({"error": "请选择要申诉的订单"}), 400
    if user.id not in (order.buyer_id, order.seller_id):
        return jsonify({"error": "只能对自己的订单发起小法庭"}), 403
    if order.status not in ("pending", "shipped"):
        return jsonify({"error": "已完成/已取消的订单没什么好判的，开不了庭"}), 400
    if Dispute.query.filter_by(order_id=order.id, status="open").first():
        return jsonify({"error": "这笔订单已经有一件审理中的案子了"}), 400

    statement = (data.get("statement") or "").strip()
    if not statement:
        return jsonify({"error": "请写下你的陈述"}), 400
    if len(statement) > 500:
        return jsonify({"error": "陈述最多 500 字"}), 400

    days = data.get("days") or 3
    if days not in DISPUTE_DAYS:
        days = 3

    if user.id == order.buyer_id:
        b_stmt, s_stmt = statement, ""
    else:
        b_stmt, s_stmt = "", statement

    d = Dispute(
        order_id=order.id,
        product_id=order.product_id,
        buyer_id=order.buyer_id,
        seller_id=order.seller_id,
        buyer_statement=b_stmt,
        seller_statement=s_stmt,
        deadline=datetime.now() + timedelta(days=days),
        created_by=user.id,
    )
    db.session.add(d)
    db.session.commit()
    row = d.to_dict()
    row["is_participant"] = True
    return jsonify(row)


@app.get("/api/court/<int:did>")
@login_required
def court_detail(user, did):
    d, err = _load_dispute(did)
    if err:
        return err
    _judge_if_due(d)
    row = d.to_dict()
    row["is_participant"] = user.id in (d.buyer_id, d.seller_id)
    my_vote = DisputeVote.query.filter_by(dispute_id=d.id, user_id=user.id).first()
    row["my_vote"] = my_vote.side if my_vote else None
    row["can_vote"] = (not row["is_participant"]) and d.status == "open" and datetime.now() < d.deadline
    row["comments"] = [c.to_dict() for c in DisputeComment.query
                       .filter_by(dispute_id=d.id).order_by(DisputeComment.id.asc()).all()]
    return jsonify(row)


@app.delete("/api/court/<int:did>")
@login_required
def court_delete(user, did):
    """删案：发起人或当事双方可以删（演示用，真实平台一般是管理员权限）。"""
    d, err = _load_dispute(did)
    if err:
        return err
    if user.id not in (d.created_by, d.buyer_id, d.seller_id):
        return jsonify({"error": "只有当事人或发起人可以删除"}), 403
    DisputeVote.query.filter_by(dispute_id=d.id).delete()
    DisputeComment.query.filter_by(dispute_id=d.id).delete()
    db.session.delete(d)
    db.session.commit()
    return jsonify({"ok": True})


@app.post("/api/court/<int:did>/statement")
@login_required
def court_statement(user, did):
    """当事人补充/修改自己的陈述。"""
    d, err = _load_dispute(did)
    if err:
        return err
    if d.status == "closed":
        return jsonify({"error": "案子已宣判，不能再补充陈述"}), 400
    statement = (request.get_json(silent=True) or {}).get("statement") or ""
    statement = statement.strip()
    if not statement:
        return jsonify({"error": "陈述不能为空"}), 400
    if user.id == d.buyer_id:
        d.buyer_statement = statement[:500]
    elif user.id == d.seller_id:
        d.seller_statement = statement[:500]
    else:
        return jsonify({"error": "只有本案当事人可以补充陈述"}), 403
    db.session.commit()
    return jsonify(d.to_dict())


@app.post("/api/court/<int:did>/comments")
@login_required
def court_comment(user, did):
    d, err = _load_dispute(did)
    if err:
        return err
    content = (request.get_json(silent=True) or {}).get("content") or ""
    content = content.strip()
    if not content:
        return jsonify({"error": "评论不能为空"}), 400
    c = DisputeComment(dispute_id=d.id, user_id=user.id, content=content[:300])
    db.session.add(c)
    db.session.commit()
    return jsonify(c.to_dict())


@app.post("/api/court/<int:did>/vote")
@login_required
def court_vote(user, did):
    """投票站队：当事人不能投自己；期限内可投可改票，到期后宣判不可投。"""
    d, err = _load_dispute(did)
    if err:
        return err
    if d.status == "closed" or datetime.now() >= d.deadline:
        _judge_if_due(d)
        return jsonify({"error": "本案已宣判，投票结束"}), 400
    if user.id in (d.buyer_id, d.seller_id):
        return jsonify({"error": "当事人不能投票，等着大家评理吧"}), 403
    side = (request.get_json(silent=True) or {}).get("side")
    if side not in ("buyer", "seller"):
        return jsonify({"error": "只能站买家或站卖家"}), 400
    v = DisputeVote.query.filter_by(dispute_id=d.id, user_id=user.id).first()
    if v is None:
        v = DisputeVote(dispute_id=d.id, user_id=user.id, side=side)
        db.session.add(v)
    else:
        v.side = side
    db.session.commit()
    b, s = d.vote_counts()
    return jsonify({"ok": True, "votes_buyer": b, "votes_seller": s, "my_vote": side})


# ---------------------------------------------------------------- AI 淘好物 Agent
#
# 一个接入 DeepSeek 的购物助手：用户用大白话描述需求，
# 模型自己决定调用 search_products 工具去商品表里查，
# 拿到真实结果后再组织成推荐语。模型只负责"理解需求 + 挑商品 + 说话"，
# 查数据永远走本地数据库，不会编造不存在的商品。
#
# API Key 配置：项目根目录 agent_config.json 里填 api_key，
# 或者设置环境变量 DEEPSEEK_API_KEY（环境变量优先，方便部署时不把 key 提交进 git）。

AGENT_CONFIG_PATH = os.path.join(BASE_DIR, "agent_config.json")


def load_agent_config():
    cfg = {
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",        # deepseek-chat 是通用对话模型，工具调用支持最好
    }
    if os.path.exists(AGENT_CONFIG_PATH):
        try:
            with open(AGENT_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (ValueError, OSError):
            pass
    env_key = os.environ.get("DEEPSEEK_API_KEY")
    if env_key:
        cfg["api_key"] = env_key
    return cfg


def agent_search_products(keyword="", min_price=None, max_price=None, tag=""):
    """Agent 的工具：按条件查在售商品。

    关键词匹配标题、描述和标签（比首页搜索只查标题更宽一些，
    因为用户口语里的词不一定正好出现在商品名里，比如"琴"要能搜到"吉他"）。
    """
    query = Product.query.filter(Product.status == "on")
    if min_price is not None:
        try:
            query = query.filter(Product.price >= float(min_price))
        except (TypeError, ValueError):
            pass
    if max_price is not None:
        try:
            query = query.filter(Product.price <= float(max_price))
        except (TypeError, ValueError):
            pass
    items = query.all()

    keyword = (keyword or "").strip()
    if keyword:
        matched = []
        for p in items:
            hay = p.title + " " + (p.description or "") + " " + " ".join(p.tag_list)
            if keyword in hay:
                matched.append(p)
        items = matched

    tag = (tag or "").strip()
    if tag:
        items = [p for p in items if tag in p.tag_list]

    # 最多给模型看 8 件，够了；再多 token 费用上去，推荐质量也不会更好
    items.sort(key=lambda p: p.id, reverse=True)
    return items[:8]


def agent_search_payload(items):
    """给模型看的商品摘要（截断描述，控制 token 用量）。"""
    return [
        {
            "id": p.id,
            "title": p.title,
            "price": round(p.price, 2),
            "tags": p.tag_list,
            "description": (p.description or "")[:60],
            "owner": p.owner.username if p.owner else "",
        }
        for p in items
    ]


AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "在平台在售商品中搜索。可按关键词、价格区间、标签组合筛选；不带条件则返回最新的在售商品。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "商品关键词，如 iPad、吉他、相机、台灯"},
                    "min_price": {"type": "number", "description": "最低价格（元）"},
                    "max_price": {"type": "number", "description": "最高价格（元）"},
                    "tag": {"type": "string", "description": "标签筛选，必须是平台预设标签之一"},
                },
                "required": [],
            },
        },
    }
]


# ---------- 本地降级模式（没配 API Key 时也能用） ----------
#
# 不走大模型，直接用正则把用户那句话拆成 关键词 / 价格区间 / 标签 三类条件
# 去查库。效果不如 DeepSeek 会"聊天"，但断网、没 key 也能演示。

# 价格上限的说法："3000以内" "预算3000" "不超过3000" "最多3000"
_PRICE_MAX_PATTERNS = [
    r"(\d+(?:\.\d+)?)\s*(?:元|块)?\s*(?:以内|之内|以下)",
    r"(?:预算|不超过|最多|最高|控制在?)\s*(\d+(?:\.\d+)?)",
]
# 价格下限的说法："100以上" "最低100"
_PRICE_MIN_PATTERNS = [
    r"(\d+(?:\.\d+)?)\s*(?:元|块)?\s*(?:以上|往上|起步)",
    r"(?:最低|至少)\s*(\d+(?:\.\d+)?)",
]
# 口语里的客套话，拆关键词前先扔掉（按长度倒序替换，避免"我想买"被"我"拆碎）
_LOCAL_STOP_WORDS = [
    "帮我找", "推荐一下", "帮我看看", "有没有", "想买个", "想买台", "想找",
    "推荐", "帮我", "找一下", "想要", "想买", "求购", "找一个", "找一台",
    "看看", "请问", "帮忙", "一下", "一台", "一件", "一个", "预算",
    "我", "想", "要", "买", "找", "求",
]


def _local_extract_conditions(text):
    """把一句话拆成 (关键词, 最低价, 最高价, 标签)。"""
    min_price = max_price = None
    for pat in _PRICE_MAX_PATTERNS:
        m = re.search(pat, text)
        if m:
            max_price = float(m.group(1))
            break
    for pat in _PRICE_MIN_PATTERNS:
        m = re.search(pat, text)
        if m:
            min_price = float(m.group(1))
            break

    t = text
    # 价格片段整个删掉，免得数字混进关键词
    t = re.sub(r"(\d+(?:\.\d+)?)\s*(?:元|块)?\s*(?:以内|之内|以下|以上|往上|起步)", "", t)
    t = re.sub(r"(?:预算|不超过|最多|最高|控制在?|最低|至少)\s*\d+(?:\.\d+)?", "", t)

    # 命中了平台预设标签就单独拎出来当筛选条件
    tag = ""
    for tg in TAG_PRESET:
        if tg in t:
            tag = tg
            t = t.replace(tg, "")
            break

    for w in sorted(_LOCAL_STOP_WORDS, key=len, reverse=True):
        t = t.replace(w, "")
    t = t.strip(" ，。？?!！的、和与或了台件双把")

    return t, min_price, max_price, tag


def agent_local_reply(text):
    """本地模式的回答：搜到就列出，搜不到就给建议。返回 (回复文本, 商品列表)。"""
    keyword, min_price, max_price, tag = _local_extract_conditions(text)

    items = agent_search_products(keyword=keyword or "", min_price=min_price,
                                  max_price=max_price, tag=tag)
    if not items and keyword:
        # 关键词没命中就放宽：只按价格和标签搜
        items = agent_search_products(min_price=min_price, max_price=max_price, tag=tag)

    if items:
        lines = []
        for p in items[:4]:
            desc = (p.description or "").strip()
            line = f"《{p.title}》¥{p.price:g}"
            if desc:
                line += "：" + (desc[:40] + ("…" if len(desc) > 40 else ""))
            lines.append(f"- {line}")
        reply = (
            f"帮你在站内找到了 {len(items)} 件相关商品，点下面的卡片可以直接查看：\n\n"
            + "\n".join(lines)
            + "\n\n想再筛价格或换个关键词，直接告诉我就行。"
        )
    else:
        reply = (
            "暂时没找到相关的在售商品。可以试试直接说商品名（比如 iPad、吉他），"
            "或者放宽价格范围，也可以过几天再来看看有没有新上架的。"
        )
    return reply, items


@app.post("/api/agent/chat")
@login_required
def agent_chat(user):
    cfg = load_agent_config()

    data = request.get_json(silent=True) or {}
    history = data.get("messages") or []
    # 只保留 role/content 两个字段，且最多带最近 10 条，防止聊得越久请求越大
    msgs = [
        {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))[:2000]}
        for m in history
        if m.get("role") in ("user", "assistant") and m.get("content")
    ][-10:]
    if not msgs:
        return jsonify({"error": "消息不能为空"}), 400

    # 没配 API Key：降级为本地关键词搜索，功能照样可用（mode=local 供前端区分）
    if not cfg["api_key"]:
        first_user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        reply, items = agent_local_reply(first_user)
        if len(msgs) <= 1:
            reply = (
                "（本地搜索模式：把 DeepSeek API Key 填进 agent_config.json 并重启，"
                "可以解锁更聪明的对话推荐）\n\n" + reply
            )
        return jsonify({
            "reply": reply,
            "products": [p.to_dict(viewer_id=user.id) for p in items[:8]],
            "mode": "local",
        })

    system_prompt = (
        "你是校园二手交易平台「余物集」的购物助手，名字叫小余。"
        "用户会用大白话描述需求，你负责帮他在平台上找到合适的在售商品。\n"
        f"平台预设标签：{'、'.join(TAG_PRESET)}。\n"
        f"当前对话的用户：{user.username}，余额 ¥{user.balance:.2f}。\n"
        "规则：\n"
        "1. 用户提出任何找商品的需求，先调用 search_products 工具查询真实商品，再根据查询结果回答，"
        "绝不编造平台上不存在的商品。\n"
        "2. 搜不到就换个更宽泛的关键词再试一次；确实没有就如实告诉用户，"
        "并建议他换个说法、放宽价格或过几天再来看看。\n"
        "3. 回复简短自然，像朋友帮忙淘东西：一次最多推荐 3 件，"
        "说清楚每件是什么、多少钱、为什么合适。提到商品时写成《商品名 ¥价格》。\n"
        "4. 和找商品无关的问题，友好地把你拉回购物话题。"
    )

    api_url = cfg["base_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + cfg["api_key"],
    }

    def call_deepseek(messages):
        body = {"model": cfg["model"], "messages": messages, "tools": AGENT_TOOLS}
        req = urllib.request.Request(
            api_url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
            except Exception:
                pass
            raise RuntimeError(f"DeepSeek 返回 {e.code}：{detail or e.reason}")

    found = []                 # 本次对话中搜到的商品（按 id 去重）
    seen_ids = set()
    reply = ""
    messages = [{"role": "system", "content": system_prompt}] + msgs

    try:
        for _ in range(3):     # 最多 3 轮：模型可能要换关键词搜几次才满意
            result = call_deepseek(messages)
            msg = result["choices"][0]["message"]
            tool_calls = msg.get("tool_calls")

            if tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": tool_calls,
                })
                for tc in tool_calls:
                    if tc.get("function", {}).get("name") != "search_products":
                        continue
                    try:
                        args = json.loads(tc["function"].get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    items = agent_search_products(
                        keyword=args.get("keyword"),
                        min_price=args.get("min_price"),
                        max_price=args.get("max_price"),
                        tag=args.get("tag"),
                    )
                    for p in items:
                        if p.id not in seen_ids:
                            seen_ids.add(p.id)
                            found.append(p)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(agent_search_payload(items), ensure_ascii=False),
                    })
                continue

            reply = (msg.get("content") or "").strip()
            break
    except (RuntimeError, KeyError, OSError, ValueError) as e:
        return jsonify({"error": f"调用 AI 服务失败：{e}"}), 502

    if not reply:
        reply = "抱歉，我这边出了点小状况，请再问一次。"

    # 模型搜了不代表推荐了（可能换过几次关键词），
    # 只把回复里真正提到的商品做成卡片；万一一个都没对上就退回全部搜索结果
    mentioned = [p for p in found if p.title in reply]
    if mentioned:
        found = mentioned

    return jsonify({
        "reply": reply,
        "products": [p.to_dict(viewer_id=user.id) for p in found[:8]],
    })


# ---------------------------------------------------------------- 启动

# 少数演示账号的区级坐标（比市中心准，距离看起来更真实）。
# 没命中的区在 backfill_user_coords 里退回市中心坐标。
DISTRICT_COORDS = {
    ("江苏省", "苏州市", "姑苏区"): (31.3140, 120.6190),   # 古城
    ("江苏省", "苏州市", "虎丘区"): (31.3350, 120.5650),   # 狮山一带，离姑苏约 6km
    ("广东省", "广州市", "天河区"): (23.1250, 113.3650),
}


def backfill_user_coords():
    """给没坐标的老用户按 常住地 查表补坐标（区级准坐标优先，市中心兜底）。"""
    n = 0
    for u in User.query.filter(User.latitude.is_(None)).all():
        if not (u.province or u.city):
            continue
        c = DISTRICT_COORDS.get((u.province, u.city, u.district)) \
            or coords_by_region(u.province, u.city)
        if c:
            u.latitude, u.longitude = c
            n += 1
    db.session.commit()
    if n:
        print(f"已为 {n} 个老账号补定位坐标")


with app.app_context():
    db.create_all()
    ensure_columns()
    seed_all()
    seed_demo_orders()
    seed_demo_disputes()      # 小法庭空着的时候放两单演示案件
    backfill_seed_regions()   # 老库的演示账号补地区（已有设置的不动）
    backfill_user_coords()    # 老库的演示账号补定位坐标


def _ensure_https_cert(lan_ip_str):
    """生成自签名 HTTPS 证书（浏览器定位要求安全上下文，HTTP 页面会被禁用定位）。

    证书带 SAN（localhost / 127.0.0.1 / 本机局域网 IP），IP 变了才重新生成；
    同一 IP 下重启复用旧证书，浏览器里点过一次"继续前往"就一直有效。
    返回 (cert_path, key_path)，失败（没装 cryptography）返回 None。
    """
    cert_dir = os.path.join(BASE_DIR, "certs")
    cert_path = os.path.join(cert_dir, "server.pem")
    key_path = os.path.join(cert_dir, "server.key")
    meta_path = os.path.join(cert_dir, "meta.json")
    os.makedirs(cert_dir, exist_ok=True)

    # 证书已存在且是为同一个 IP 生成的，直接复用
    try:
        if (os.path.exists(cert_path) and os.path.exists(key_path)
                and os.path.exists(meta_path)):
            with open(meta_path, encoding="utf-8") as f:
                if json.load(f).get("ip") == lan_ip_str:
                    return cert_path, key_path
    except Exception:
        pass

    try:
        import datetime
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "校园二手交易平台")])
        san = x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.IPAddress(ipaddress.ip_address(lan_ip_str)),
        ])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(san, critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )
        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"ip": lan_ip_str}, f)
        return cert_path, key_path
    except Exception as e:
        print(f"  [HTTPS] 证书生成失败（{e}），只提供 HTTP 访问")
        return None


def _start_https(lan_ip_str, port=5001):
    """在 5001 端口额外起一个 HTTPS 服务（和 HTTP 共用同一个 app，同进程无线程争库问题）。"""
    pair = _ensure_https_cert(lan_ip_str)
    if not pair:
        return None
    from werkzeug.serving import make_server
    import threading
    server = make_server("0.0.0.0", port, app, ssl_context=pair)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    import socket

    def lan_ip():
        """拿本机在局域网里的 IP（UDP connect 不会真发包，只是选路由，断网也不报错）。"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "127.0.0.1"

    ip = lan_ip()

    # HTTPS 端口：浏览器只允许在 HTTPS（或 localhost）页面上用定位功能。
    # 别的电脑用 http://IP:5000 打开时定位会被禁（自动退 IP 定位兜底），
    # 用 https://IP:5001 打开则是完整定位体验。自签名证书首次打开要点
    # "高级 → 继续前往"，之后浏览器会记住。
    try:
        _start_https(ip)
    except OSError as e:
        # 5001 被占用等情况：不拦着主服务，HTTP 照常可用
        print(f"  [HTTPS] 5001 端口启动失败（{e}），只提供 HTTP")

    print("=" * 52)
    print("  校园二手交易平台已启动")
    print("  本机访问：   http://127.0.0.1:5000")
    print(f"  局域网访问： http://{ip}:5000（定位受限，自动退 IP 估位）")
    print(f"  局域网HTTPS：https://{ip}:5001 （定位完整可用）")
    print("  HTTPS 首次打开：点『高级』→『继续前往』即可，之后浏览器会记住")
    print("  手机连同一个 Wi-Fi，用上面的局域网地址即可打开")
    print("  演示账号： 小林 / 123456    老王 / 123456")
    print("  关闭这个黑窗口即可停止服务")
    print("=" * 52)

    import threading
    import webbrowser

    # 等服务起来再自动打开浏览器，省得用户手输地址
    threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    # host 0.0.0.0 = 监听所有网卡，局域网里的手机/别的电脑才能访问
    app.run(host="0.0.0.0", port=5000, debug=False)

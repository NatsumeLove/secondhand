# -*- coding: utf-8 -*-
"""
演示数据 —— 第一次运行时自动写入，让系统一打开就有东西可看

包含 3 个账号、22 件商品，商品封面是本地生成的 SVG 图，
所以断网也能正常显示，不会出现一片裂图。
"""

import json
import os
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from models import db, Order, Product, User

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")


def _write_svg(name: str, svg: str) -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    return f"/static/uploads/{name}"


def make_cover(name: str, label: str, c1: str, c2: str) -> str:
    """生成一张渐变色封面图，中间是商品短名。"""
    size = 76 if len(label) <= 4 else 46 if len(label) <= 8 else 34
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" viewBox="0 0 600 600">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>
</linearGradient></defs>
<rect width="600" height="600" fill="url(#g)"/>
<text x="300" y="300" text-anchor="middle" dominant-baseline="central"
 font-family="PingFang SC, Microsoft YaHei, sans-serif" font-size="{size}"
 fill="#ffffff" fill-opacity="0.94">{label}</text>
</svg>"""
    return _write_svg(name, svg)


def make_avatar(name: str, char: str, color: str) -> str:
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">
<rect width="120" height="120" rx="60" fill="{color}"/>
<text x="60" y="62" text-anchor="middle" dominant-baseline="central"
 font-family="PingFang SC, Microsoft YaHei, sans-serif" font-size="52"
 fill="#ffffff">{char}</text>
</svg>"""
    return _write_svg(name, svg)


# (标题, 价格, 标签, 描述, 封面短名, 渐变色)
PRODUCTS = [
    ("iPad Air 4 64G 深空灰", 1850, ["数码", "平板"], "自用两年，屏幕无划痕，电池健康 89%，附带原装充电器。", "iPad Air 4", ("#5b7cfa", "#8f6bf5")),
    ("罗技 MX Master 3S 鼠标", 320, ["数码", "外设"], "换了静音鼠标所以出，滚轮和按键都正常，无掉漆。", "MX Master", ("#2f9e8f", "#4fb8a5")),
    ("索尼 WH-1000XM4 头戴式耳机", 780, ["数码", "音频"], "降噪正常，耳罩有轻微使用痕迹，附收纳包。", "WH-1000XM4", ("#3f4a5a", "#66748a")),
    ("Kindle Paperwhite 五代 8G", 380, ["数码", "阅读"], "读书习惯改成 iPad 了，屏幕无亮点，送保护套。", "Kindle", ("#b8860b", "#d9a441")),
    ("尼康 D5300 单反相机 套机", 2100, ["数码", "摄影"], "含 18-55mm 套头，快门数约 1.2 万，成色很好。", "D5300", ("#c0392b", "#e26a4f")),
    ("珂芝 K75 机械键盘 茶轴", 180, ["数码", "外设"], "茶轴手感，附带原装键帽，有线连接正常。", "K75 键盘", ("#7f5539", "#a9714b")),
    ("宜家 福尔马 台灯", 35, ["家居"], "宿舍搬走用不上，暖光灯泡还在，功能完好。", "台灯", ("#c9a227", "#e0c060")),
    ("宿舍折叠小桌板", 40, ["家居"], "床上用小桌，可折叠收纳，桌面无破损。", "折叠桌", ("#8d99ae", "#a9b4c5")),
    ("飞利浦电动牙刷 全新未拆", 90, ["个护"], "朋友送错了型号，包装完整未拆封。", "电动牙刷", ("#2a9d8f", "#57c0b2")),
    ("膳魔师保温杯 500ml", 55, ["家居", "个护"], "保温效果依旧，杯身有一道浅划痕，不影响使用。", "保温杯", ("#457b9d", "#6a9fc0")),
    ("迪卡侬羽毛球拍 双拍装", 70, ["运动"], "打了几次，拍线完好，附赠三个球。", "羽毛球拍", ("#2d6a4f", "#52a37a")),
    ("瑜伽垫 加厚 10mm", 25, ["运动"], "买来练了两次就吃灰了，无异味，已擦洗。", "瑜伽垫", ("#6a4c93", "#8e6bb5")),
    ("小米米家走步机", 400, ["运动", "家居"], "在家走了半年，功能正常，需自提，太重不发快递。", "走步机", ("#495057", "#6f7880")),
    ("阿迪达斯 Ultraboost 42码", 260, ["服饰", "鞋"], "穿了一季，鞋底磨损不严重，已清洗。", "Ultraboost", ("#1d3557", "#43618a")),
    ("优衣库 摇粒绒外套 L", 60, ["服饰"], "冬款，洗过两次，无起球，颜色是米白。", "摇粒绒外套", ("#a68a64", "#c4ab86")),
    ("北面 男款冲锋衣 M", 480, ["服饰", "户外"], "防水层完好，袖口有轻微磨白，拉链顺滑。", "冲锋衣", ("#22333b", "#41555f")),
    ("曼昆《经济学原理》上下册", 45, ["图书"], "第七版，有少量笔记，不影响阅读。", "经济学原理", ("#8a5a2b", "#b07c46")),
    ("张宇考研数学 1000 题", 30, ["图书"], "全新未写，买重复了。", "考研数学", ("#5c677d", "#7c879c")),
    ("雅思真题 4-18 合集", 60, ["图书"], "做过 4-10，后面几本全新，答案册齐全。", "雅思真题", ("#9c6644", "#bd8764")),
    ("雅马哈 F310 民谣吉他", 450, ["乐器", "音乐"], "入门琴，弦距已调过，附琴包和变调夹。", "F310 吉他", ("#7d4e24", "#a06c3c")),
    ("捷安特 通勤自行车", 620, ["户外", "出行"], "骑了一年，刚换过刹车皮，车锁一起送。", "自行车", ("#1b4965", "#3d6f92")),
    ("泡泡玛特 盲盒三只", 80, ["潮玩"], "重复款出掉，盒子和卡片都在。", "盲盒", ("#c9184a", "#e2557d")),
]

USERS = [
    ("小林", "123456", 5000, "林", "#f2601a"),
    ("老王", "123456", 3000, "王", "#2f6fed"),
    ("苏苏", "123456", 800, "苏", "#2a9d8f"),
]


def seed_all():
    """已经有数据就直接跳过，不会重复插入。"""
    if User.query.count() > 0:
        return

    users = []
    for i, (name, pwd, balance, char, color) in enumerate(USERS, start=1):
        avatar = make_avatar(f"seed-avatar-{i}.svg", char, color)
        u = User(
            username=name,
            password_hash=generate_password_hash(pwd, method="pbkdf2:sha256"),
            avatar=avatar,
            balance=balance,
        )
        db.session.add(u)
        users.append(u)
    db.session.flush()          # 拿到自增 id 后再插商品

    owners = [users[1], users[2], users[1], users[0]]   # 老王 / 苏苏 为主，小林也放几件
    for i, (title, price, tags, desc, label, colors) in enumerate(PRODUCTS, start=1):
        image = make_cover(f"seed-{i:02d}.svg", label, colors[0], colors[1])
        db.session.add(
            Product(
                title=title,
                price=price,
                tags=json.dumps(tags, ensure_ascii=False),
                description=desc,
                image=image,
                status="on",
                owner_id=owners[(i - 1) % len(owners)].id,
            )
        )

    db.session.commit()
    print(f"演示数据已生成：{len(users)} 个账号，{len(PRODUCTS)} 件商品")


def seed_demo_orders():
    """造三笔不同状态的订单，一打开"我的订单"就能看到三种状态。

    为什么要有这个：如果订单页一开始是空的，演示时必须先手动买一单
    才能讲状态流转，节奏会乱。提前放三单，三种状态一眼看全。

    造订单时照着真实流程走：商品过户给买家、下架、双方余额一增一减，
    这样数据是自洽的，不会出现"订单说买了、商品还在卖家那儿"。
    """
    if Order.query.count() > 0:
        return

    lin = User.query.filter_by(username="小林").first()
    wang = User.query.filter_by(username="老王").first()
    su = User.query.filter_by(username="苏苏").first()
    if not (lin and wang and su):
        return

    # (买家, 卖家, 订单状态, 几天前下的单)
    plans = [
        (lin, wang, "pending", 0),    # 刚付完钱，等老王发货
        (su, wang, "shipped", 2),     # 老王已发货，等苏苏确认收货
        (lin, su, "done", 9),         # 早就完成的一单
    ]

    made = 0
    for buyer, seller, status, days_ago in plans:
        product = (
            Product.query.filter_by(owner_id=seller.id, status="on")
            .order_by(Product.price.asc())
            .first()
        )
        if product is None:
            continue

        created = datetime.now() - timedelta(days=days_ago, hours=2)
        buyer.balance = round(buyer.balance - product.price, 2)
        seller.balance = round(seller.balance + product.price, 2)

        db.session.add(
            Order(
                product_id=product.id,
                buyer_id=buyer.id,
                seller_id=seller.id,
                deal_price=product.price,
                snap_title=product.title,
                snap_image=product.image,
                snap_desc=product.description,
                snap_tags=product.tags,
                status=status,
                status_at=created + timedelta(hours=6),
                created_at=created,
            )
        )

        product.owner_id = buyer.id
        product.status = "off"
        made += 1

    db.session.commit()
    if made:
        print(f"演示订单已生成：{made} 笔")

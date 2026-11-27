# -*- coding: utf-8 -*-
"""
演示数据 —— 第一次运行时自动写入，让系统一打开就有东西可看

包含 3 个账号、30 件商品。商品配的是 AI 生成的实拍风格图片和介绍视频
（在 static/seed-assets/ 目录），素材丢失时自动退回本地生成的 SVG 渐变图，
所以断网也能正常显示，不会出现一片裂图。
"""

import json
import os
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from models import db, Dispute, DisputeComment, DisputeVote, Order, Product, User

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
    # —— 以下 8 件参考真实二手平台（闲鱼/转转/校园群）热门品类和价位补充 ——
    ("小熊电煮锅 1.5L 九成新", 80, ["家居"], "毕业急出，用了一学期，锅里干净无异味，功率低宿舍不跳闸，电源线和说明书都在，宿舍楼下自提。", "电煮锅", ("#e07a5f", "#f2a68c")),
    ("雅迪电动车 48V 已上牌", 780, ["出行", "户外"], "大三骑了一年，电池去年刚换的，充满能跑 40 公里，手续齐全可过户，校内面交可试骑，不议价。", "雅迪电动车", ("#264653", "#3d7a8a")),
    ("惠普喷墨打印机 打论文神器", 260, ["数码"], "学姐毕业出，墨盒基本是满的，电源线说明书齐全，宿舍打论文再也不用跑打印店，楼下自提。", "打印机", ("#4361ee", "#6c8ff2")),
    ("考研全套资料 政英数+真题笔记", 220, ["图书", "阅读"], "学长一战上岸整理的全套：政治英语数学资料加历年真题，重点都用荧光笔画好了，比买新书省一半。", "考研资料", ("#7209b7", "#9d4edd")),
    ("漫步者 LolliPods Pro 降噪耳机", 150, ["数码", "音频"], "用过一学期，降噪正常续航拉满，充电仓和两副备用耳塞都在，成色很新。", "蓝牙耳机", ("#2a9d8f", "#57c0b2")),
    ("AOC 24寸显示器 75Hz 九成新", 300, ["数码"], "宿舍升级双屏所以出，屏幕无亮点无坏点，HDMI 线一起送，包装盒还在，校内面交。", "显示器", ("#333d4d", "#5c6b80")),
    ("新秀丽 24寸行李箱 只用过一次", 95, ["出行"], "毕业打包用了一次，轮子拉杆都顺滑，密码锁功能正常，有行李牌，需要的同学面交。", "行李箱", ("#1d3557", "#43618a")),
    ("小米手环8 NFC版 95新", 130, ["数码", "运动"], "用了三个月，贴膜都没撕，包装盒充电线齐全，NFC 刷饭卡很好用。", "小米手环8", ("#f77f00", "#fca311")),
    # —— 以下 17 件实拍素材来自 Wikimedia Commons（免费授权），见 SEED_ASSETS 的 q 系列 ——
    ("罗技 C920 高清摄像头 网课必备", 120, ["数码", "外设"], "网课直播用过一学期，1080P 画面清晰，夹在显示器上很稳，即插即用。", "摄像头", ("#457b9d", "#6a9fc0")),
    ("任天堂 Switch 主机 续航增强版", 900, ["数码", "游戏"], "买了就吃灰系列，拆封使用不到十次，主机+Joy-Con+底座全套都在，可面交试机。", "Switch", ("#e63946", "#f2747f")),
    ("哈利波特全集 英文原版 1-7", 150, ["图书", "阅读"], "英版套装收藏，纸质很好，前三本有少量铅笔笔记，送配套书立。", "哈利波特", ("#6d3b1f", "#8a5a35")),
    ("乐高积木散件一大盒约三斤", 60, ["潮玩", "玩具"], "毕业清仓，散装积木一整盒，已清洗装袋，基础颗粒多，适合练手 MOC。", "乐高积木", ("#1d6fb8", "#4a9bd6")),
    ("索尼 A6000 微单 + 16-50 套头", 1600, ["数码", "摄影"], "成色 95 新，快门数不到 8000，两块原装电池，相机包和 64G 卡一起送。", "A6000", ("#3a3a3a", "#5c5c5c")),
    ("Apple Pencil 一代 95新", 380, ["数码", "平板"], "笔尖磨损很小，配 iPad 写笔记做手账很方便，原装盒和备用笔尖都在。", "Apple Pencil", ("#d8d8d8", "#efefef")),
    ("富士拍立得黑白相纸 两盒全新", 75, ["数码", "摄影"], "mono 黑白款 10 张装，买多了出两盒，保质期到 2027 年，未拆封。", "拍立得相纸", ("#2b2b2b", "#4d4d4d")),
    ("笔记本散热支架 四风扇静音", 45, ["数码", "家居"], "宿舍打游戏用的，风扇静音效果好，高度六档可调，送 USB 分线器。", "散热支架", ("#22252b", "#454a52")),
    ("半导体小冰箱 20L 冷暖两用", 180, ["家居", "电器"], "宿舍神器，夏天冰饮料冬天热牛奶，制冷正常有轻微水流声，需自提。", "小冰箱", ("#e8e8e6", "#f5f5f2")),
    ("英雄 100 钢笔 + 原装墨水", 65, ["文具", "收藏"], "上大学买的没怎么用，笔尖顺滑不刮纸，F 尖日常书写够用，附吸墨器。", "钢笔", ("#14141c", "#3c3c52")),
    ("电竞椅 人体工学 可后仰", 220, ["家居", "家具"], "毕业急出，黑白配色，气杆正常椅背 135 度可调，坐垫无破损，自提。", "电竞椅", ("#2c2f36", "#545a66")),
    ("可调节哑铃 20kg + 臂力器", 110, ["运动"], "健身卡到期不练了，哑铃电镀款无锈迹，臂力器 40kg 可调，校内自提。", "哑铃", ("#3d3d8f", "#6a6ac0")),
    ("漫步者 M230 蓝牙音箱 复古款", 95, ["数码", "音频"], "复古造型颜值很高，音质同价位里算强的，用三个月几乎全新，包装盒在。", "蓝牙音箱", ("#b8b8b6", "#d6d6d2")),
    ("卡西欧 G-SHOCK 运动手表", 260, ["配饰", "运动"], "戴了一年功能全好，防震防水秒表闹钟都在，表带已清洗，附原装表盒。", "G-SHOCK", ("#1c1c1c", "#3a3a3a")),
    ("尤克里里 23寸 Concert 单板", 160, ["乐器", "音乐"], "入门练手琴，音准没问题，送琴包+拨片+调音器，宿舍可试弹再决定。", "尤克里里", ("#b5762a", "#d29a55")),
    ("Nendoroid 粘土人手办 盒装", 130, ["潮玩", "收藏"], "重复款出掉，盒子说明书表情件都在，关节完好可摆姿势，可小刀。", "粘土人", ("#e0a63c", "#f2c977")),
    ("复古黑胶唱片机 蓝牙+CD一体", 480, ["数码", "音频", "家居"], "学长毕业出，复古造型摆宿舍超有氛围，蓝牙和 CD 功能都正常，附说明书。", "唱片机", ("#6b4a26", "#8f6a42")),
]

# AI 生成的商品实拍图和介绍视频（在 static/seed-assets/ 里，会一起提交进 git）。
# 键是 PRODUCTS 里的序号（从 1 开始），值是 (图片文件列表, 视频文件列表)。
# 命中了的商品用真实图片，没命中的继续用上面的 SVG 渐变封面兜底。
SEED_ASSETS = {
    1: (["p01.png", "d01.png"], ["v01.mp4"]),    # iPad：主图+细节图+介绍视频
    2: (["p02.png"], []),
    3: (["p03.png"], []),
    4: (["p04.png"], []),
    5: (["p05.png", "d05.png"], []),             # 相机：主图+细节图
    6: (["p06.png"], []),
    7: (["p07.png"], []),
    8: (["p08.png"], []),
    9: (["p09.png"], []),
    10: (["p10.png"], []),
    11: (["p11.png"], []),
    12: (["p12.png"], []),
    13: (["p13.png"], []),
    14: (["p14.png"], []),
    15: (["p15.png"], []),
    16: (["p16.png"], []),
    17: (["p17.png"], []),
    18: (["p18.png"], []),
    19: (["p19.png"], []),
    20: (["p20.png", "d20.png"], ["v20.mp4"]),   # 吉他：主图+细节图+弹奏视频
    21: (["p21.png", "d21.png"], []),            # 自行车：主图+细节图
    22: (["p22.png"], []),
    23: (["p23.png"], []),
    24: (["p24.png"], []),
    25: (["p25.png"], []),
    26: (["p26.png"], []),
    27: (["p27.png"], []),
    28: (["p28.png"], []),
    29: (["p29.png"], []),
    30: (["p30.png"], []),
    # —— 31-47：Wikimedia Commons 免费授权实拍图（q 系列）——
    31: (["q01.jpg"], []),                       # 摄像头
    32: (["q02.jpg"], []),                       # Switch
    33: (["q03.jpg"], []),                       # 哈利波特
    34: (["q04.jpg"], []),                       # 乐高
    35: (["q05.jpg"], []),                       # A6000 微单
    36: (["q06.jpg"], []),                       # Apple Pencil
    37: (["q07.jpg"], []),                       # 拍立得相纸
    38: (["q08.jpg"], []),                       # 散热支架
    39: (["q09.jpg"], []),                       # 小冰箱
    40: (["q10.jpg"], []),                       # 钢笔
    41: (["q11.jpg"], []),                       # 电竞椅
    42: (["q12.jpg"], []),                       # 哑铃
    43: (["q13.jpg"], []),                       # 蓝牙音箱
    44: (["q14.jpg"], []),                       # G-SHOCK
    45: (["q15.jpg"], []),                       # 尤克里里
    46: (["q16.jpg"], []),                       # 粘土人
    47: (["q17.jpg"], ["v02.webm"]),             # 黑胶唱片机：主图+转盘实拍视频
}

USERS = [
    # (用户名, 密码, 余额, 头像字, 头像色, (省, 市, 区))
    # 地区故意分两省，演示"同城好物"时：小林能刷到老王（同城），刷不到苏苏（省外）
    ("小林", "123456", 5000, "林", "#f2601a", ("江苏省", "苏州市", "姑苏区")),
    ("老王", "123456", 3000, "王", "#2f6fed", ("江苏省", "苏州市", "虎丘区")),
    ("苏苏", "123456", 800, "苏", "#2a9d8f", ("广东省", "广州市", "天河区")),
]


def seed_all():
    """已经有数据就直接跳过，不会重复插入。"""
    if User.query.count() > 0:
        return

    users = []
    for i, (name, pwd, balance, char, color, region) in enumerate(USERS, start=1):
        avatar = make_avatar(f"seed-avatar-{i}.svg", char, color)
        u = User(
            username=name,
            password_hash=generate_password_hash(pwd, method="pbkdf2:sha256"),
            avatar=avatar,
            balance=balance,
            province=region[0],
            city=region[1],
            district=region[2],
        )
        db.session.add(u)
        users.append(u)
    db.session.flush()          # 拿到自增 id 后再插商品

    owners = [users[1], users[2], users[1], users[0]]   # 老王 / 苏苏 为主，小林也放几件
    for i, (title, price, tags, desc, label, colors) in enumerate(PRODUCTS, start=1):
        # 有 AI 实拍素材就用素材，没有才用 SVG 渐变封面兜底（断网/素材丢失也能看）
        asset = SEED_ASSETS.get(i)
        if asset:
            image = f"/static/seed-assets/{asset[0][0]}"
            images = [f"/static/seed-assets/{x}" for x in asset[0]]
            videos = [f"/static/seed-assets/{x}" for x in asset[1]]
        else:
            image = make_cover(f"seed-{i:02d}.svg", label, colors[0], colors[1])
            images, videos = [image], []
        db.session.add(
            Product(
                title=title,
                price=price,
                tags=json.dumps(tags, ensure_ascii=False),
                description=desc,
                image=image,
                images=json.dumps(images, ensure_ascii=False),
                videos=json.dumps(videos, ensure_ascii=False),
                status="on",
                owner_id=owners[(i - 1) % len(owners)].id,
            )
        )

    db.session.commit()
    print(f"演示数据已生成：{len(users)} 个账号，{len(PRODUCTS)} 件商品")


def backfill_seed_regions():
    """给老库里的演示账号补上所在地区（地区功能上线时对老库跑一次）。

    只处理 province 为空的演示账号；用户自己已经设置过地区的不动。
    """
    regions = {name: (p, c, d) for name, _, _, _, _, (p, c, d) in USERS}
    changed = 0
    for u in User.query.filter(User.province == "").all():
        if u.username in regions:
            p, c, d = regions[u.username]
            u.province, u.city, u.district = p, c, d
            changed += 1
    if changed:
        db.session.commit()
        print(f"已为 {changed} 个演示账号补上所在地区")


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


def seed_demo_disputes():
    """小法庭空着时放两单演示案件，一打开就有"审理中"和"已宣判"可看。

    案子挂在 seed_demo_orders 造出的订单上，判决生效时就能真实地
    退款/完成订单，把钱和商品都动起来，数据始终自洽。
    """
    if Dispute.query.count() > 0:
        return
    lin = User.query.filter_by(username="小林").first()
    wang = User.query.filter_by(username="老王").first()
    su = User.query.filter_by(username="苏苏").first()
    if not (lin and wang and su):
        return

    def _order(buyer_id, seller_id):
        return (Order.query.filter_by(buyer_id=buyer_id, seller_id=seller_id)
                .order_by(Order.id.desc()).first())

    now = datetime.now()
    made = 0

    # 案一：小林(买家) vs 老王(卖家)，那笔"待发货"的订单——还没发货就想催单
    o1 = _order(lin.id, wang.id)
    if o1:
        d1 = Dispute(
            order_id=o1.id, product_id=o1.product_id,
            buyer_id=lin.id, seller_id=wang.id,
            buyer_statement="付钱三天了还没发货！客服问了也不回，再不发货我就要退款了。",
            seller_statement="实在抱歉！家里有事先耽搁了，今天下午一定发货，求再宽限一天。",
            deadline=now + timedelta(days=3), created_by=lin.id,
        )
        db.session.add(d1)
        db.session.flush()
        db.session.add(DisputeVote(dispute_id=d1.id, user_id=su.id, side="buyer"))
        db.session.add(DisputeComment(dispute_id=d1.id, user_id=su.id,
                                      content="三天不发货确实过分了，我站买家。"))
        db.session.add(DisputeComment(dispute_id=d1.id, user_id=wang.id,
                                      content="真不是故意拖，家中有急事，下午发货单号第一时间发。"))
        made += 1

    # 案二：苏苏(买家) vs 老王(卖家)，那笔"待收货"的订单——说好的九成新到手有划痕
    o2 = _order(su.id, wang.id)
    if o2:
        d2 = Dispute(
            order_id=o2.id, product_id=o2.product_id,
            buyer_id=su.id, seller_id=wang.id,
            buyer_statement="商品页写的是95新无划痕，到手侧面一道明显划痕，要求退款！",
            seller_statement="发货前我拍了视频确认过没划痕，可能是运输磕碰，可以补偿10元维修费。",
            deadline=now + timedelta(days=5), created_by=su.id,
        )
        db.session.add(d2)
        db.session.flush()
        db.session.add(DisputeVote(dispute_id=d2.id, user_id=lin.id, side="seller"))
        db.session.add(DisputeComment(dispute_id=d2.id, user_id=lin.id,
                                      content="运输磕碰不该全怪卖家吧，补偿个维修费合理。"))
        made += 1

    db.session.commit()
    if made:
        print(f"演示案件已生成：{made} 件")

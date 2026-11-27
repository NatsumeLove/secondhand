# -*- coding: utf-8 -*-
"""
数据模型 —— 对应数据库里的 5 张表

users         用户表：用户名、密码（加密后）、头像、余额
products      商品表：名称、价格、标签、图片、描述、上架状态、归属人
conversations 会话表：谁和谁、围绕哪件商品聊
messages      消息表：会话里每一句话，含"改价申请"这种特殊类型
orders        订单表：成交记录，含成交那一刻的商品快照

为什么订单要存快照？
因为商品是可以被买走、再上架、改标题的。如果订单只存 product_id，
三个月后翻旧订单，看到的会是商品"现在"的样子，历史记录就被篡改了。
所以下单那一刻把商品名、图、描述复制一份存进 orders 表里。
"""

import json
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# 订单状态与它的中文名。状态只能沿着下面 app.py 里的规则跳转，不能随便改
ORDER_STATUS_TEXT = {
    "pending": "待发货",
    "shipped": "待收货",
    "done": "已完成",
    "cancelled": "已取消",
}

# 小法庭判决结果与它的中文名
COURT_VERDICT_TEXT = {
    "buyer": "买家胜诉",
    "seller": "卖家胜诉",
    "draw": "平局收场",
}


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    avatar = db.Column(db.String(255), default="")
    balance = db.Column(db.Float, nullable=False, default=0.0)
    # 所在地区：省 / 市 / 县（区）。商品的"所属地"跟着卖家走
    province = db.Column(db.String(32), default="")
    city = db.Column(db.String(32), default="")
    district = db.Column(db.String(32), default="")
    # 编辑主页的资料项（老库由 ensure_columns 自动补列）
    bio = db.Column(db.String(200), default="")            # 个人简介
    gender = db.Column(db.String(10), default="")          # 男 / 女 / 保密
    birthday = db.Column(db.String(20), default="")        # 生日，YYYY-MM-DD
    likes = db.Column(db.String(200), default="")          # 喜欢的（标签，逗号分隔）
    school = db.Column(db.String(60), default="")          # 院校名称
    # 定位坐标：浏览器定位写入精确值；只填了常住地时按城市名查表兜底
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    @property
    def region_text(self):
        """完整地区串，如「江苏省苏州市姑苏区」。没填返回空串。"""
        return f"{self.province or ''}{self.city or ''}{self.district or ''}"

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "avatar": self.avatar,
            "balance": round(self.balance, 2),
            "province": self.province or "",
            "city": self.city or "",
            "district": self.district or "",
            "region": self.region_text,
            "region_short": self.city or self.province or "",
            "bio": self.bio or "",
            "gender": self.gender or "",
            "birthday": self.birthday or "",
            "likes": self.likes or "",
            "school": self.school or "",
            # 坐标给前端判断"是否已定位"，精确值不下发给其他用户（隐私）
            "has_geo": self.latitude is not None and self.longitude is not None,
        }


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(80), nullable=False)
    price = db.Column(db.Float, nullable=False, default=0.0)
    tags = db.Column(db.Text, default="[]")          # 存 JSON 字符串，如 ["数码","摄影"]
    description = db.Column(db.Text, default="")
    image = db.Column(db.String(255), default="")
    # 商品介绍的多图和视频，也是 JSON 字符串，如 ["/static/uploads/xx.jpg", ...]
    # 老数据没有这两列也没关系，ensure_columns 会补，且封面继续用 image 字段
    images = db.Column(db.Text, default="[]")
    videos = db.Column(db.Text, default="[]")
    status = db.Column(db.String(8), nullable=False, default="off")   # on=上架  off=下架
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    owner = db.relationship("User", foreign_keys=[owner_id])

    @property
    def tag_list(self):
        try:
            return json.loads(self.tags or "[]")
        except (ValueError, TypeError):
            return []

    @property
    def image_list(self):
        """详情页的图片画廊：多图在前，老的单图封面兜底。"""
        try:
            images = json.loads(self.images or "[]")
        except (ValueError, TypeError):
            images = []
        if not images and self.image:
            images = [self.image]
        return [i for i in images if i]

    @property
    def video_list(self):
        try:
            return [v for v in json.loads(self.videos or "[]") if v]
        except (ValueError, TypeError):
            return []

    def to_dict(self, viewer_id=None):
        return {
            "id": self.id,
            "title": self.title,
            "price": round(self.price, 2),
            "tags": self.tag_list,
            "description": self.description,
            "image": self.image or (self.image_list[0] if self.image_list else ""),
            "images": self.image_list,
            "videos": self.video_list,
            "status": self.status,
            "owner": {
                "id": self.owner.id,
                "username": self.owner.username,
                "avatar": self.owner.avatar,
                # 商品所属地 = 卖家所在地区。region_short 用于卡片上的小地名
                "region": self.owner.region_text,
                "region_short": self.owner.city or self.owner.province or "",
            },
            "is_mine": viewer_id == self.owner_id,
            "created_at": self.created_at.strftime("%m-%d %H:%M") if self.created_at else "",
        }


class Comment(db.Model):
    """商品评论。reply_to_id 为空就是普通评论，不为空则是卖家对某条评论的回复。"""

    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reply_to_id = db.Column(db.Integer, db.ForeignKey("comments.id"), nullable=True)
    content = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship("User", foreign_keys=[user_id])


class Conversation(db.Model):
    """一个会话 = 一件商品 + 一个买家。同一件商品，不同买家各聊各的。"""

    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now)

    # 两个人各自"读到了第几条消息"。比逐条存已读状态省事得多：
    # 只要消息 id 大于自己的这个数字，就是还没看的
    buyer_read_id = db.Column(db.Integer, nullable=False, default=0)
    seller_read_id = db.Column(db.Integer, nullable=False, default=0)

    product = db.relationship("Product", foreign_keys=[product_id])
    buyer = db.relationship("User", foreign_keys=[buyer_id])
    seller = db.relationship("User", foreign_keys=[seller_id])


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    type = db.Column(db.String(8), nullable=False, default="text")   # text / offer / system
    content = db.Column(db.Text, default="")
    price = db.Column(db.Float)                  # 改价申请里提出的价格
    accepted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "sender_id": self.sender_id,
            "type": self.type,
            "content": self.content,
            "price": round(self.price, 2) if self.price is not None else None,
            "accepted": bool(self.accepted),
            "created_at": self.created_at.strftime("%H:%M") if self.created_at else "",
        }


class Follow(db.Model):
    """用户关注关系：follower 关注了 followed。"""

    __tablename__ = "follows"

    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    followed_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class Favorite(db.Model):
    """商品收藏。"""

    __tablename__ = "favorites"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class ProductView(db.Model):
    """浏览记录：谁在什么时间看过哪件商品（看自己的商品不记）。"""

    __tablename__ = "product_views"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    viewed_at = db.Column(db.DateTime, default=datetime.now)


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    deal_price = db.Column(db.Float, nullable=False)

    # —— 下面四个是"成交那一刻"的快照，之后商品怎么改都不影响这里 ——
    snap_title = db.Column(db.String(80), default="")
    snap_image = db.Column(db.String(255), default="")
    snap_desc = db.Column(db.Text, default="")
    snap_tags = db.Column(db.Text, default="[]")

    # 订单状态：pending 待发货 → shipped 待收货 → done 已完成
    #           pending 也可以直接 cancelled 已取消（此时退款、商品回到卖家手上）
    status = db.Column(db.String(12), nullable=False, default="pending")
    status_at = db.Column(db.DateTime, default=datetime.now)

    created_at = db.Column(db.DateTime, default=datetime.now)

    buyer = db.relationship("User", foreign_keys=[buyer_id])
    seller = db.relationship("User", foreign_keys=[seller_id])

    def to_dict(self):
        try:
            tags = json.loads(self.snap_tags or "[]")
        except (ValueError, TypeError):
            tags = []
        return {
            "id": self.id,
            "product_id": self.product_id,
            "title": self.snap_title,
            "image": self.snap_image,
            "description": self.snap_desc,
            "tags": tags,
            "deal_price": round(self.deal_price, 2),
            "status": self.status,
            "status_text": ORDER_STATUS_TEXT.get(self.status, self.status),
            "status_at": self.status_at.strftime("%Y-%m-%d %H:%M") if self.status_at else "",
            "buyer": {"id": self.buyer.id, "username": self.buyer.username, "avatar": self.buyer.avatar},
            "seller": {"id": self.seller.id, "username": self.seller.username, "avatar": self.seller.avatar},
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else "",
        }


class Dispute(db.Model):
    """小法庭案件：买卖双方的矛盾，期限内由围观群众投票，到期按票数宣判。"""

    __tablename__ = "disputes"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # 双方的主要发言（发起人先写自己那侧，对面可以后补陈述）
    buyer_statement = db.Column(db.Text, default="")
    seller_statement = db.Column(db.Text, default="")

    deadline = db.Column(db.DateTime, nullable=False)                 # 投票截止 = 宣判时间
    status = db.Column(db.String(8), nullable=False, default="open")  # open 审理中 / closed 已宣判
    verdict = db.Column(db.String(8), default=None)                   # buyer / seller / draw
    verdict_note = db.Column(db.String(200), default="")              # 判决落地说明（退款/完成）

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    product = db.relationship("Product", foreign_keys=[product_id])
    buyer = db.relationship("User", foreign_keys=[buyer_id])
    seller = db.relationship("User", foreign_keys=[seller_id])

    def vote_counts(self):
        """(站买家票数, 站卖家票数)。"""
        votes = DisputeVote.query.filter_by(dispute_id=self.id).all()
        return (sum(1 for v in votes if v.side == "buyer"),
                sum(1 for v in votes if v.side == "seller"))

    def to_dict(self):
        b_votes, s_votes = self.vote_counts()
        return {
            "id": self.id,
            "order_id": self.order_id,
            "product": {
                "id": self.product.id,
                "title": self.product.title,
                "image": self.product.image or (self.product.image_list[0] if self.product.image_list else ""),
                "price": round(self.product.price, 2),
            },
            "buyer": {"id": self.buyer.id, "username": self.buyer.username, "avatar": self.buyer.avatar},
            "seller": {"id": self.seller.id, "username": self.seller.username, "avatar": self.seller.avatar},
            "buyer_statement": self.buyer_statement or "",
            "seller_statement": self.seller_statement or "",
            "deadline": self.deadline.strftime("%Y-%m-%d %H:%M"),
            "deadline_ts": self.deadline.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": self.status,
            "verdict": self.verdict,
            "verdict_text": COURT_VERDICT_TEXT.get(self.verdict, "") if self.verdict else "",
            "verdict_note": self.verdict_note or "",
            "votes_buyer": b_votes,
            "votes_seller": s_votes,
            "is_participant": False,   # 接口层按当前用户覆盖
            "created_at": self.created_at.strftime("%m-%d %H:%M") if self.created_at else "",
        }


class DisputeComment(db.Model):
    """小法庭里的围观评论（和投票独立，谁都能评）。"""

    __tablename__ = "dispute_comments"

    id = db.Column(db.Integer, primary_key=True)
    dispute_id = db.Column(db.Integer, db.ForeignKey("disputes.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    content = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "user": {"id": self.user.id, "username": self.user.username, "avatar": self.user.avatar},
            "content": self.content,
            "created_at": self.created_at.strftime("%m-%d %H:%M") if self.created_at else "",
        }


class DisputeVote(db.Model):
    """小法庭投票：站买家 / 站卖家。一人一案一票，期限内可以改票。"""

    __tablename__ = "dispute_votes"
    __table_args__ = (db.UniqueConstraint("dispute_id", "user_id", name="uq_dispute_vote"),)

    id = db.Column(db.Integer, primary_key=True)
    dispute_id = db.Column(db.Integer, db.ForeignKey("disputes.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    side = db.Column(db.String(8), nullable=False)   # buyer / seller
    created_at = db.Column(db.DateTime, default=datetime.now)

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


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    avatar = db.Column(db.String(255), default="")
    balance = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "avatar": self.avatar,
            "balance": round(self.balance, 2),
        }


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(80), nullable=False)
    price = db.Column(db.Float, nullable=False, default=0.0)
    tags = db.Column(db.Text, default="[]")          # 存 JSON 字符串，如 ["数码","摄影"]
    description = db.Column(db.Text, default="")
    image = db.Column(db.String(255), default="")
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

    def to_dict(self, viewer_id=None):
        return {
            "id": self.id,
            "title": self.title,
            "price": round(self.price, 2),
            "tags": self.tag_list,
            "description": self.description,
            "image": self.image,
            "status": self.status,
            "owner": {
                "id": self.owner.id,
                "username": self.owner.username,
                "avatar": self.owner.avatar,
            },
            "is_mine": viewer_id == self.owner_id,
            "created_at": self.created_at.strftime("%m-%d %H:%M") if self.created_at else "",
        }


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

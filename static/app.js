/* =========================================================================
   余物集 —— 前端逻辑
   所有数据都通过 /api/... 从后端取，页面不直接碰数据库
   ========================================================================= */

const { createApp, nextTick } = Vue

/* ---------- 图标（内联 SVG，不依赖网络） ---------- */
const icon = (d) =>
  `<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor"
        stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`

const ICONS = {
  user: icon('<circle cx="8" cy="5.5" r="2.6"/><path d="M3 13.2c.6-2.3 2.6-3.4 5-3.4s4.4 1.1 5 3.4"/>'),
  home: icon('<path d="M2.8 7.2 8 2.8l5.2 4.4V13H2.8z"/><path d="M6.4 13V9.4h3.2V13"/>'),
  chat: icon('<path d="M13.4 8.6c0 2.4-2.4 4.3-5.4 4.3-.7 0-1.3-.1-1.9-.3L3 13.4l.8-2.2c-.8-.7-1.2-1.6-1.2-2.6 0-2.4 2.4-4.3 5.4-4.3s5.4 1.9 5.4 4.3z"/>'),
  box: icon('<path d="M8 2.2 13.4 5v6L8 13.8 2.6 11V5z"/><path d="M2.6 5 8 7.8 13.4 5"/><path d="M8 7.8v6"/>'),
  receipt: icon('<path d="M4 2.4h8v11.2l-2-1.2-2 1.2-2-1.2-2 1.2z"/><path d="M6 5.6h4M6 8h4"/>'),
}

/* ---------- 请求封装 ---------- */
async function api(path, options = {}) {
  const res = await fetch('/api' + path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  let data = null
  try {
    data = await res.json()
  } catch (e) {
    data = null
  }
  if (!res.ok) throw new Error((data && data.error) || '请求失败')
  return data
}

async function uploadFile(file) {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch('/api/upload', { method: 'POST', body: fd, credentials: 'same-origin' })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error || '上传失败')
  return data.path
}

createApp({
  data() {
    return {
      me: null,
      loading: false,
      tab: 'home',
      tabs: [
        { key: 'me', label: '用户中心', icon: ICONS.user },
        { key: 'home', label: '首页', icon: ICONS.home },
        { key: 'msg', label: '消息', icon: ICONS.chat },
        { key: 'items', label: '我的商品', icon: ICONS.box },
        { key: 'orders', label: '我的订单', icon: ICONS.receipt },
      ],

      // 登录 / 注册
      authForm: { username: '', password: '' },
      registerForm: { username: '', password: '', avatar: '' },
      showRegister: false,

      // 首页
      products: [],
      presetTags: [],
      filters: { min: '', max: '', tags: [] },
      tagKeyword: '',
      searchKeyword: '',   // 输入框里的字（边打字边变）
      searchApplied: '',   // 真正提交去查的字（防抖后才更新）
      searchTimer: null,
      detail: null,
      buying: false,
      page: 1,
      pageSize: 12,
      total: 0,
      hasMore: false,
      loadingMore: false,
      feedSeed: '',        // 推荐顺序的随机种子，翻页时要原样带回去

      // 消息
      conversations: [],
      activeConv: null,
      messages: [],
      chatText: '',
      showOffer: false,
      offerPrice: '',
      pollTimer: null,
      unread: 0,
      unreadTimer: null,

      // 我的商品
      myProducts: [],
      showCreate: false,
      editingId: null,
      createForm: { title: '', price: '', tags: [], description: '', image: '' },

      // 订单
      orderTab: 'bought',
      orders: { bought: [], sold: [], todo_bought: 0, todo_sold: 0 },

      // 用户中心
      profileForm: { username: '', password: '' },

      toast: null,
    }
  },

  computed: {
    tagSuggestions() {
      const pool = this.presetTags.filter((t) => !this.filters.tags.includes(t))
      const kw = this.tagKeyword.trim()
      if (!kw) return pool          // 没输入时把预设标签全列出来，方便直接点
      return pool.filter((t) => t.includes(kw)).slice(0, 10)
    },
    currentOrders() {
      return this.orderTab === 'bought' ? this.orders.bought : this.orders.sold
    },
    // 聊天窗里能不能直接下单：我是买家，且这件商品还在售
    chatBuyable() {
      const c = this.activeConv
      return !!c && !c.i_am_seller && c.product && c.product.status === 'on'
    },
  },

  mounted() {
    this.boot()
  },

  methods: {
    /* ================= 启动 ================= */
    async boot() {
      try {
        this.me = await api('/me')
        this.profileForm.username = this.me.username
        this.presetTags = await api('/tags')
        await this.loadProducts()
        this.startUnreadPoll()
        // 支持用 #msg 这样的地址直接打开某一栏，刷新也不会跳回首页
        const hash = location.hash.replace('#', '')
        if (hash && this.tabs.some((t) => t.key === hash)) {
          await this.switchTab(hash)
        }
      } catch (e) {
        this.me = null          // 没登录，停在登录页
      }
    },

    notify(text, type = 'ok') {
      this.toast = { text, type }
      clearTimeout(this._toastTimer)
      this._toastTimer = setTimeout(() => (this.toast = null), 2200)
    },

    /* ================= 登录 / 注册 ================= */
    async doLogin() {
      if (!this.authForm.username || !this.authForm.password) {
        return this.notify('请输入用户名和密码', 'err')
      }
      this.loading = true
      try {
        this.me = await api('/login', {
          method: 'POST',
          body: JSON.stringify(this.authForm),
        })
        this.profileForm.username = this.me.username
        this.presetTags = await api('/tags')
        await this.loadProducts()
        this.tab = 'home'
        this.startUnreadPoll()
        this.notify(`欢迎回来，${this.me.username}`)
      } catch (e) {
        this.notify(e.message, 'err')
      } finally {
        this.loading = false
      }
    },

    openRegister() {
      this.registerForm = { username: '', password: '', avatar: '' }
      this.showRegister = true
    },

    async doRegister() {
      if (this.loading) return
      this.loading = true
      try {
        this.me = await api('/register', {
          method: 'POST',
          body: JSON.stringify(this.registerForm),
        })
        this.showRegister = false
        this.profileForm.username = this.me.username
        this.presetTags = await api('/tags')
        await this.loadProducts()
        this.tab = 'home'
        this.startUnreadPoll()
        this.notify('注册成功，赠送 1000 元余额')
      } catch (e) {
        this.notify(e.message, 'err')
      } finally {
        this.loading = false
      }
    },

    async uploadRegisterAvatar(e) {
      const file = e.target.files[0]
      if (!file) return
      try {
        this.registerForm.avatar = await uploadFile(file)
      } catch (err) {
        this.notify(err.message, 'err')
      }
    },

    async doLogout() {
      await api('/logout', { method: 'POST' })
      clearInterval(this.pollTimer)
      clearInterval(this.unreadTimer)
      this.unread = 0
      this.me = null
      this.authForm = { username: '', password: '' }
      this.activeConv = null
      this.messages = []
      this.notify('已退出登录')
    },

    /* ================= 首页 ================= */
    async loadProducts({ reset = true, reshuffle = false } = {}) {
      if (reset) {
        this.page = 1
        this.products = []
        this.loadingMore = true
      }
      if (reshuffle) this.feedSeed = ''
      const params = new URLSearchParams()
      if (this.filters.min !== '' && this.filters.min !== null) params.set('min', this.filters.min)
      if (this.filters.max !== '' && this.filters.max !== null) params.set('max', this.filters.max)
      if (this.filters.tags.length) params.set('tags', this.filters.tags.join(','))
      if (this.searchApplied) params.set('q', this.searchApplied)
      params.set('page', this.page)
      params.set('size', this.pageSize)
      if (this.feedSeed) params.set('seed', this.feedSeed)

      try {
        const res = await api('/products?' + params.toString())
        this.products = reset ? res.items : this.products.concat(res.items)
        this.total = res.total
        this.hasMore = res.has_more
        this.feedSeed = res.seed
      } catch (e) {
        this.notify(e.message, 'err')
      } finally {
        this.loadingMore = false
      }
    },

    async loadMore() {
      if (!this.hasMore || this.loadingMore) return
      this.page += 1
      await this.loadProducts({ reset: false })
    },

    async reshuffle() {
      await this.loadProducts({ reset: true, reshuffle: true })
    },

    /* 搜索：边打字边搜，但要防抖。
       每敲一个字就请求一次，网络和数据库都受不了，
       所以等用户停手 300ms 再真正去查。 */
    onSearchInput() {
      clearTimeout(this.searchTimer)
      this.searchTimer = setTimeout(() => this.applySearch(), 300)
    },

    applySearch() {
      clearTimeout(this.searchTimer)
      const kw = this.searchKeyword.trim()
      if (kw === this.searchApplied) return
      this.searchApplied = kw
      this.loadProducts({ reset: true, reshuffle: true })
    },

    clearSearch() {
      this.searchKeyword = ''
      this.applySearch()
    },

    applyFilters() {
      if (this.filters.max !== '' && this.filters.min > this.filters.max) {
        return this.notify('最低价不能高于最高价', 'err')
      }
      this.loadProducts()
    },

    clearFilters() {
      this.filters = { min: '', max: '', tags: [] }
      this.tagKeyword = ''
      this.searchKeyword = ''
      this.searchApplied = ''
      this.loadProducts({ reset: true, reshuffle: true })
    },

    toggleTag(t) {
      const i = this.filters.tags.indexOf(t)
      if (i >= 0) this.filters.tags.splice(i, 1)
      else this.filters.tags.push(t)
      this.loadProducts()
    },

    openDetail(p) {
      this.detail = p
    },

    async buy(p) {
      if (!confirm(`确认用 ¥${p.price} 买下「${p.title}」吗？`)) return
      this.buying = true
      try {
        const res = await api(`/products/${p.id}/buy`, { method: 'POST' })
        this.me.balance = res.balance
        this.detail = null
        await this.loadProducts()
        this.notify('购买成功，订单已进入「待发货」')
      } catch (e) {
        this.notify(e.message, 'err')
      } finally {
        this.buying = false
      }
    },

    // 在聊天窗里直接下单。和详情页下单走的是同一个接口，
    // 区别只在下单后要把会话和首页列表都刷新一遍。
    async buyFromChat() {
      const c = this.activeConv
      if (!c) return
      const p = c.product
      if (!confirm(`确认用 ¥${p.price} 买下「${p.title}」吗？`)) return
      this.buying = true
      try {
        const res = await api(`/products/${p.id}/buy`, { method: 'POST' })
        this.me.balance = res.balance
        await this.openConversation(c.id)   // 重新拉会话，商品状态和系统提示都会更新
        await this.loadConversations()
        await this.loadProducts()
        this.notify('购买成功，订单已进入「待发货」')
      } catch (e) {
        this.notify(e.message, 'err')
      } finally {
        this.buying = false
      }
    },

    async startBargain(p) {
      try {
        const conv = await api('/conversations', {
          method: 'POST',
          body: JSON.stringify({ product_id: p.id }),
        })
        this.detail = null
        await this.switchTab('msg')
        await this.openConversation(conv.id)
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    /* ================= 消息 ================= */
    async loadConversations() {
      this.conversations = await api('/conversations')
      // 导航栏那个小红点 = 所有会话未读数之和
      this.unread = this.conversations.reduce((sum, c) => sum + (c.unread || 0), 0)
    },

    async refreshUnread() {
      try {
        const r = await api('/unread')
        this.unread = r.total
      } catch (e) {
        /* 轮询失败不打扰用户 */
      }
    },

    startUnreadPoll() {
      clearInterval(this.unreadTimer)
      this.refreshUnread()
      // 每 8 秒问一次有没有新消息，这样不在消息页也能看到红点
      this.unreadTimer = setInterval(() => {
        if (this.me) this.refreshUnread()
      }, 8000)
    },

    async openConversation(id) {
      const data = await api(`/conversations/${id}`)
      this.activeConv = data
      this.messages = data.messages
      this.chatText = ''
      this.showOffer = false
      this.scrollChat()
      await this.loadConversations()   // 打开即已读，顺手把红点清掉

      clearInterval(this.pollTimer)
      // 每 3 秒拉一次，模拟"实时"效果：另一个窗口发来的消息会自动出现
      this.pollTimer = setInterval(async () => {
        if (!this.activeConv || this.tab !== 'msg') return
        try {
          const fresh = await api(`/conversations/${this.activeConv.id}`)
          if (fresh.messages.length !== this.messages.length) {
            this.messages = fresh.messages
            this.activeConv = fresh
            this.scrollChat()
          }
        } catch (e) {
          /* 忽略轮询错误 */
        }
      }, 3000)
    },

    scrollChat() {
      nextTick(() => {
        const el = this.$refs.chatBody
        if (el) el.scrollTop = el.scrollHeight
      })
    },

    async sendText() {
      const text = this.chatText.trim()
      if (!text || !this.activeConv) return
      try {
        await api(`/conversations/${this.activeConv.id}/messages`, {
          method: 'POST',
          body: JSON.stringify({ text }),
        })
        this.chatText = ''
        await this.refreshMessages()
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    async sendOffer() {
      const price = Number(this.offerPrice)
      if (!price || price <= 0) return this.notify('请输入一个有效价格', 'err')
      try {
        await api(`/conversations/${this.activeConv.id}/messages`, {
          method: 'POST',
          body: JSON.stringify({ offer_price: price }),
        })
        this.offerPrice = ''
        this.showOffer = false
        await this.refreshMessages()
        this.notify('改价申请已发出')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    async acceptOffer(m) {
      try {
        await api(`/messages/${m.id}/accept`, { method: 'POST' })
        await this.refreshMessages()
        await this.loadConversations()
        this.notify('已同意改价')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    async refreshMessages() {
      const fresh = await api(`/conversations/${this.activeConv.id}`)
      this.activeConv = fresh
      this.messages = fresh.messages
      this.scrollChat()
    },

    /* ================= 我的商品 ================= */
    async loadMyProducts() {
      this.myProducts = await api('/my-products')
    },

    openCreate() {
      this.editingId = null
      this.createForm = { title: '', price: '', tags: [], description: '', image: '' }
      this.showCreate = true
    },

    closeProductForm() {
      this.showCreate = false
      this.editingId = null
    },

    openEdit(p) {
      this.editingId = p.id
      // 复制一份到表单里改，改的过程中不直接动原数据，取消就什么都没变
      this.createForm = {
        title: p.title,
        price: p.price,
        tags: [...p.tags],
        description: p.description,
        image: p.image,
      }
      this.showCreate = true
    },

    toggleCreateTag(t) {
      const i = this.createForm.tags.indexOf(t)
      if (i >= 0) this.createForm.tags.splice(i, 1)
      else this.createForm.tags.push(t)
    },

    async uploadProductImage(e) {
      const file = e.target.files[0]
      if (!file) return
      try {
        this.createForm.image = await uploadFile(file)
      } catch (err) {
        this.notify(err.message, 'err')
      }
    },

    async submitProduct() {
      const f = this.createForm
      if (!f.title) return this.notify('请填写商品名称', 'err')
      if (!f.price || f.price <= 0) return this.notify('请填写大于 0 的价格', 'err')
      const isEdit = !!this.editingId
      try {
        if (isEdit) {
          await api(`/products/${this.editingId}`, {
            method: 'PATCH',
            body: JSON.stringify(f),
          })
        } else {
          await api('/products', { method: 'POST', body: JSON.stringify(f) })
        }
        this.showCreate = false
        this.editingId = null
        await this.loadMyProducts()
        if (this.tab === 'home') await this.loadProducts()
        this.notify(isEdit ? '已保存修改' : '已发布，默认是下架状态，记得上架')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    async toggleStatus(p) {
      try {
        await api(`/products/${p.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ status: p.status === 'on' ? 'off' : 'on' }),
        })
        await this.loadMyProducts()
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    async removeProduct(p) {
      if (!confirm(`确认删除「${p.title}」吗？删除后无法恢复。`)) return
      try {
        await api(`/products/${p.id}`, { method: 'DELETE' })
        await this.loadMyProducts()
        this.notify('已删除')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    /* ================= 订单 ================= */
    async loadOrders() {
      this.orders = await api('/orders')
    },

    // 卖家发货：待发货 → 待收货
    async shipOrder(o) {
      try {
        await api(`/orders/${o.id}/ship`, { method: 'POST' })
        await this.loadOrders()
        this.notify('已发货，等待买家确认收货')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    // 买家确认收货：待收货 → 已完成
    async confirmOrder(o) {
      if (!confirm(`确认已经收到「${o.title}」了吗？`)) return
      try {
        await api(`/orders/${o.id}/confirm`, { method: 'POST' })
        await this.loadOrders()
        this.notify('订单已完成')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    // 买家取消：只在卖家发货前有效，会退款并把商品还给卖家
    async cancelOrder(o) {
      if (!confirm(`取消这笔订单？¥${o.deal_price} 会退回你的余额。`)) return
      try {
        const res = await api(`/orders/${o.id}/cancel`, { method: 'POST' })
        this.me.balance = res.balance
        await this.loadOrders()
        await this.loadProducts()
        this.notify('订单已取消，钱已退回')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    /* ================= 用户中心 ================= */
    async uploadAvatar(e) {
      const file = e.target.files[0]
      if (!file) return
      try {
        const path = await uploadFile(file)
        this.me = await api('/me', {
          method: 'PUT',
          body: JSON.stringify({ avatar: path }),
        })
        this.notify('头像已更新')
      } catch (err) {
        this.notify(err.message, 'err')
      }
    },

    async saveProfile() {
      const body = {}
      if (this.profileForm.username && this.profileForm.username !== this.me.username) {
        body.username = this.profileForm.username
      }
      if (this.profileForm.password) body.password = this.profileForm.password
      if (!Object.keys(body).length) return this.notify('没有要修改的内容', 'err')
      try {
        this.me = await api('/me', { method: 'PUT', body: JSON.stringify(body) })
        this.profileForm.password = ''
        this.notify('资料已保存')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    async recharge(amount) {
      try {
        this.me = await api('/me/recharge', {
          method: 'POST',
          body: JSON.stringify({ amount }),
        })
        this.notify(`充值成功，当前余额 ¥${this.me.balance}`)
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    /* ================= 切换标签页 ================= */
    async switchTab(key) {
      this.tab = key
      if (location.hash !== '#' + key) location.hash = key
      if (key === 'home') await this.loadProducts()
      if (key === 'msg') await this.loadConversations()
      if (key === 'items') await this.loadMyProducts()
      if (key === 'orders') await this.loadOrders()
      if (key === 'me') this.profileForm.username = this.me.username
    },
  },
}).mount('#app')

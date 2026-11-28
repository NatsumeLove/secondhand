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
  mine: icon('<rect x="2.6" y="2.6" width="4.4" height="4.4" rx="1"/><rect x="9" y="2.6" width="4.4" height="4.4" rx="1"/><rect x="2.6" y="9" width="4.4" height="4.4" rx="1"/><rect x="9" y="9" width="4.4" height="4.4" rx="1"/>'),
  heart: icon('<path d="M8 13.2 3.6 8.8a2.8 2.8 0 0 1 4-4L8 5.3l.4-.5a2.8 2.8 0 0 1 4 4z"/>'),
  clock: icon('<circle cx="8" cy="8" r="5.6"/><path d="M8 5.2V8l2 1.5"/>'),
  people: icon('<circle cx="5.8" cy="5.8" r="2.4"/><path d="M2.2 12.9c.5-2 2-3.1 3.6-3.1s3.1 1.1 3.6 3.1"/><circle cx="11.4" cy="6.6" r="1.9"/><path d="M11 9.9c1.4.2 2.5 1.1 2.9 2.7"/>'),
  box: icon('<path d="M8 2.2 13.4 5v6L8 13.8 2.6 11V5z"/><path d="M2.6 5 8 7.8 13.4 5"/><path d="M8 7.8v6"/>'),
  receipt: icon('<path d="M4 2.4h8v11.2l-2-1.2-2 1.2-2-1.2-2 1.2z"/><path d="M6 5.6h4M6 8h4"/>'),
  court: icon('<path d="M8 2.8v9.6M4.4 4.6h7.2M4.4 4.6 2.6 8.8a2.1 2.1 0 0 0 3.6 0zM11.6 4.6 9.8 8.8a2.1 2.1 0 0 0 3.6 0zM5.8 13.6h4.4"/>'),
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

const __app = createApp({
  data() {
    return {
      ICONS,               // 模板里直接用 <span v-html="ICONS.xxx"> 渲染图标
      me: null,
      loading: false,
      tab: 'home',
      // 顶部导航：首页 / 消息 / 我的。"我的"是独立的总览页，
      // 用户中心、交易管理、收藏、浏览、关注都收纳在里面
      tabs: [
        { key: 'home', label: '首页', icon: ICONS.home },
        { key: 'court', label: '小法庭', icon: ICONS.court },
        { key: 'msg', label: '消息', icon: ICONS.chat },
      ],

      // 登录 / 注册
      authForm: { username: '', password: '' },
      registerForm: { username: '', password: '', avatar: '' },
      showRegister: false,

      // 首页
      products: [],
      presetTags: [],
      filters: { min: '', max: '', tags: [], province: '', city: '', district: '' },
      localOnly: false,     // "同城好物"：只看同省，县>市>省内排序
      locating: false,      // 正在浏览器定位
      sortByDistance: false, // "按距离由近到远"排序开关
      geoNearCity: '',      // 浏览器定位识别出的就近城市名（展示用）
      geoNearDistrict: null, // 就近区县 {name, city}，显示"苏州市·姑苏区"用
      regionData: null,     // 全国省/市/县数据（懒加载 static/region-data.json）
      tagKeyword: '',
      searchKeyword: '',   // 输入框里的字（边打字边变）
      searchApplied: '',   // 真正提交去查的字（防抖后才更新）
      searchTimer: null,
      detail: null,        // 商品详情页数据（含评论），从弹窗升级成了独立页面
      detailFrom: 'home',  // 打开详情前所在的栏目，返回时回到那里
      activeMediaSrc: '',  // 详情页正在展示的图片/视频地址
      activeMediaIsVideo: false,
      commentText: '',     // 详情页评论输入框
      replyTo: null,       // 卖家正在回复哪条评论
      replyText: '',
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
      createForm: { title: '', price: '', tags: [], description: '', image: '', images: [], videos: [] },

      // 订单
      orderTab: 'bought',
      orders: { bought: [], sold: [], todo_bought: 0, todo_sold: 0 },

      // 用户中心
      profileForm: { username: '', password: '' },
      profileRegion: { province: '', city: '', district: '' },   // 所在地区（省/市/县）

      // 编辑主页（资料行）
      editPop: null,        // 当前正在编辑哪一项（null=没有弹层）
      editTitles: { username: '修改昵称', bio: '编辑简介', gender: '选择性别', birthday: '选择生日',
                    likes: '选择喜欢的', school: '填写院校名称', region: '选择常住地' },
      editForm: { username: '', bio: '', gender: '', birthday: '', likesArr: [], school: '' },

      // 以图搜物（拍照 / 上传图片找相似宝贝）
      camOpen: false,       // 拍照弹窗
      camMode: 'idle',      // idle 未开相机 / live 取景中 / shot 已拍好待确认
      camShot: '',          // 拍好的照片 dataURL
      camStream: null,      // getUserMedia 的视频流
      imgSearching: false,
      imgResults: [],       // 以图搜物结果（带 similarity）
      imgSearchImg: '',     // 查询图预览（本地 objectURL / dataURL）
      imgRecog: null,       // 大模型识别结果 {name, category, keywords, desc}；null=走的颜色兜底
      imgSearchFrom: 'home',

      // 小法庭：案件列表 / 详情 / 发起弹窗
      courtList: [],
      courtDetail: null,
      courtModal: false,
      courtOrders: [],          // 我可以发起申诉的订单（买到的+卖出的）
      courtForm: { order_id: '', statement: '', days: 3 },
      courtComment: '',         // 详情页评论输入
      courtStmt: '',            // 详情页"补充陈述"输入
      courtStmtOpen: false,
      courtVoting: false,

      // 我的（总览页）：收藏 / 浏览记录 / 关注
      favorites: [],
      history: [],
      following: [],
      mineSummary: { products: 0, sold: 0, bought: 0, favorites: 0, history: 0, following: 0 },

      // 卖家小铺主页
      shop: null,
      shopFrom: 'home',

      // AI 淘好物
      agentOpen: false,
      agentMsgs: [],        // { role: 'user'|'assistant', text, products: [...] }
      agentInput: '',
      agentLoading: false,
      petBroken: false,    // 3D 看板起不来（没有 WebGL）时退回悬浮球

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
    /* —— 省市县级联列表（首页筛选 + 用户中心共用一套数据） —— */
    provinceList() {
      return this.regionData || []
    },
    filterCityList() {
      const p = (this.regionData || []).find((x) => x.name === this.filters.province)
      return p ? p.children : []
    },
    filterDistrictList() {
      const c = this.filterCityList.find((x) => x.name === this.filters.city)
      return c ? (c.children || []) : []
    },
    profileCityList() {
      const p = (this.regionData || []).find((x) => x.name === this.profileRegion.province)
      return p ? p.children : []
    },
    profileDistrictList() {
      const c = this.profileCityList.find((x) => x.name === this.profileRegion.city)
      return c ? (c.children || []) : []
    },
    currentOrders() {
      return this.orderTab === 'bought' ? this.orders.bought : this.orders.sold
    },
    // 聊天窗里能不能直接下单：我是买家，且这件商品还在售
    chatBuyable() {
      const c = this.activeConv
      return !!c && !c.i_am_seller && c.product && c.product.status === 'on'
    },
    // "我的"是否处于选中态：总览页本身或它收纳的任何子页面
    mineActive() {
      return ['mine', 'items', 'orders', 'favorites', 'history', 'following', 'me', 'editme'].includes(this.tab)
    },
  },

  watch: {
    // 3D 看板只在登录后出现；退出登录就销毁，别让它在登录页后台空转。
    // 登录瞬间 .app 分支还没挂载，要等 nextTick 拿到 ref 再启动
    me(v) {
      if (v) nextTick(() => this.startPet())
      else this.stopPet()
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
        this.syncProfileRegion()
        this.presetTags = await api('/tags')
        await this.ensureRegions()
        await this.loadProducts()
        this.autoLocate()          // 每次打开页面：静默重定位，刷新所有人的距离
        this.startUnreadPoll()
        // 支持用 #msg 这样的地址直接打开某一栏，刷新也不会跳回首页；
        // #product/12 打开商品详情页，#user/2 打开卖家小铺
        const hash = location.hash.replace('#', '')
        if (hash.startsWith('product/')) {
          await this.openDetail(Number(hash.split('/')[1]), 'home')
        } else if (hash.startsWith('user/')) {
          await this.openShop(Number(hash.split('/')[1]), 'home')
        } else if (hash.startsWith('court/')) {
          this.tab = 'court'
          await this.openCourtDetail(Number(hash.split('/')[1]))
        } else if (['me', 'home', 'court', 'msg', 'mine', 'items', 'orders', 'favorites', 'history', 'following', 'editme', 'imgsearch'].includes(hash)) {
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
        this.syncProfileRegion()
        this.presetTags = await api('/tags')
        await this.ensureRegions()
        await this.loadProducts()
        this.autoLocate()          // 登录后同样静默重定位一次
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
        this.syncProfileRegion()
        this.presetTags = await api('/tags')
        await this.ensureRegions()
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
      // 地区筛选 + 同城好物
      if (this.filters.province) params.set('province', this.filters.province)
      if (this.filters.city) params.set('city', this.filters.city)
      if (this.filters.district) params.set('district', this.filters.district)
      if (this.localOnly) params.set('local', 1)
      if (this.sortByDistance && this.me.has_geo) params.set('sort', 'distance')
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
      this.filters = { min: '', max: '', tags: [], province: '', city: '', district: '' }
      this.localOnly = false
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

    /* ================= 地区筛选 / 同城好物 ================= */

    // 懒加载全国省/市/县数据（~140KB，只拉一次）
    async ensureRegions() {
      if (this.regionData) return
      try {
        const res = await fetch('/static/region-data.json')
        this.regionData = await res.json()
      } catch (e) {
        this.notify('地区数据加载失败', 'err')
      }
    },

    // 把后端存的地区同步到用户中心的级联选择器
    syncProfileRegion() {
      this.profileRegion = {
        province: this.me.province || '',
        city: this.me.city || '',
        district: this.me.district || '',
      }
    },

    // 首页筛选：选了省 → 清掉市/县；选了市 → 清掉县。改完立刻生效
    onFilterProvChange() {
      this.filters.city = ''
      this.filters.district = ''
      this.loadProducts({ reset: true, reshuffle: true })
    },
    onFilterCityChange() {
      this.filters.district = ''
      this.loadProducts({ reset: true, reshuffle: true })
    },
    onFilterDistrictChange() {
      this.loadProducts({ reset: true, reshuffle: true })
    },

    // "同城好物"开关：只展示同省商品，按 县 > 市 > 省内 排序，省外不展示
    async toggleLocal() {
      if (this.localOnly && !(this.me.province && this.me.city && this.me.district)) {
        this.localOnly = false
        return this.notify('请先在「用户中心 → 修改资料」里设置你的所在地区', 'err')
      }
      await this.loadProducts({ reset: true, reshuffle: true })
    },

    /* ================= 距离定位 ================= */

    // IP 定位兜底：浏览器 Geolocation 只在 HTTPS 或 localhost 下开放，
    // 局域网里别的电脑用 http://192.168.x.x:5000 打开时定位会被浏览器禁掉，
    // 这时让后端按公网 IP 估个大概位置（城市级精度，够用）。
    async locateByIp({ notifyFail = false } = {}) {
      try {
        const res = await api('/geo/iplocate', { method: 'POST', body: '{}' })
        this.me.has_geo = true
        this.geoNearCity = res.near_city || ''
        this.geoNearDistrict = res.near_district || null
        this.applyLocatedRegion(res)
        await this.loadProducts({ reset: true, reshuffle: true })
        if (notifyFail) {
          const place = this.geoLabel()
          this.notify(place
            ? `浏览器定位不可用，已按 IP 定位到 ${place}附近`
            : '浏览器定位不可用，已按 IP 估位')
        }
        return res
      } catch (e) {
        if (notifyFail) this.notify(e.message, 'err')
        return null
      }
    },

    // 定位结果的展示文案：有区县就"苏州市·姑苏区"，只有城市就"苏州市"
    geoLabel() {
      if (this.geoNearDistrict) return `${this.geoNearDistrict.city}·${this.geoNearDistrict.name}`
      return this.geoNearCity || ''
    },

    // 定位后同步 me 的省市区：主页 IP 徽标、商品卡地名、同城筛选跟着定位走
    applyLocatedRegion(res) {
      if (!res || !res.region) return
      const r = res.region
      this.me.province = r.province || ''
      this.me.city = r.city || ''
      this.me.district = r.district || ''
      this.me.region = (r.province || '') + (r.city || '') + (r.district || '')
      this.me.region_short = this.me.city || this.me.province || ''
      this.syncProfileRegion()      // 编辑主页的地区选择也跟着刷新
    },

    // 每次打开页面/登录时静默重定位一次：拿到最新坐标就写库，
    // 后端会把所有演示账号围着你这次的位置重新落点，距离永远是"这次定位"算出来的。
    // 浏览器定位不可用就退 IP 定位，都失败才沿用库里上一次的坐标（全程静默）。
    autoLocate() {
      if (!this.me) return
      if (!navigator.geolocation) return void this.locateByIp()
      navigator.geolocation.getCurrentPosition(async (pos) => {
        try {
          const res = await api('/geo/locate', {
            method: 'POST',
            body: JSON.stringify({
              latitude: pos.coords.latitude,
              longitude: pos.coords.longitude,
            }),
          })
          this.me.has_geo = true
          this.applyLocatedRegion(res)
          await this.loadProducts({ reset: true, reshuffle: true })
        } catch (e) { /* 静默失败，不影响正常浏览 */ }
      }, () => { this.locateByIp() /* 静默转 IP 定位 */ }, {
        enableHighAccuracy: false, timeout: 8000, maximumAge: 0,
      })
    },

    // 浏览器定位：拿真实经纬度存库，商品卡就会显示与你的距离
    locateMe() {
      if (!navigator.geolocation) return void this.locateByIp({ notifyFail: true })
      this.locating = true
      navigator.geolocation.getCurrentPosition(async (pos) => {
        try {
          const res = await api('/geo/locate', {
            method: 'POST',
            body: JSON.stringify({
              latitude: pos.coords.latitude,
              longitude: pos.coords.longitude,
            }),
          })
          this.me.has_geo = true
          this.geoNearCity = res.near_city || ''
          this.geoNearDistrict = res.near_district || null
          this.applyLocatedRegion(res)
          await this.loadProducts({ reset: true, reshuffle: true })
          const place = this.geoLabel()
          this.notify(place ? `定位成功：${place}附近` : '定位成功')
        } catch (e) {
          this.notify(e.message, 'err')
        } finally {
          this.locating = false
        }
      }, (err) => {
        // 授权被拒/超时/HTTP 页面被浏览器禁定位：退 IP 定位兜底
        this.locateByIp({ notifyFail: true }).finally(() => { this.locating = false })
      }, { enableHighAccuracy: true, timeout: 10000 })
    },

    /* ================= 小法庭 ================= */

    // 案件列表
    async loadCourt() {
      try {
        const res = await api('/court')
        this.courtList = res.items || []
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    // 剩余审理时间文案："剩 2 天 4 小时" / "剩 3 小时" / "已到期"
    courtCountdown(d) {
      const end = new Date(d.deadline_ts).getTime()
      const diff = end - Date.now()
      if (diff <= 0) return '已到期，等待宣判'
      const h = Math.floor(diff / 3600000)
      const day = Math.floor(h / 24)
      if (day >= 1) return `剩 ${day} 天 ${h % 24} 小时`
      return `剩 ${h} 小时 ${Math.floor((diff % 3600000) / 60000)} 分钟`
    },

    // 发起弹窗：拉我自己的订单（买到的+卖出的）供选择
    async openCourtCreate() {
      try {
        const res = await api('/orders')
        const rows = []
        for (const o of (res.bought || [])) {
          if (o.status === 'pending' || o.status === 'shipped') {
            rows.push({ id: o.id, label: `【我买的】${o.title} · ¥${o.deal_price} · ${o.status_text}` })
          }
        }
        for (const o of (res.sold || [])) {
          if (o.status === 'pending' || o.status === 'shipped') {
            rows.push({ id: o.id, label: `【我卖的】${o.title} · ¥${o.deal_price} · ${o.status_text}` })
          }
        }
        this.courtOrders = rows
        if (!rows.length) {
          return this.notify('没有可申诉的订单（只有进行中的买卖订单能开庭）', 'err')
        }
        this.courtForm = { order_id: rows[0].id, statement: '', days: 3 }
        this.courtModal = true
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    async submitCourt() {
      if (!this.courtForm.order_id) return this.notify('请选择订单', 'err')
      if (!this.courtForm.statement.trim()) return this.notify('请写下你的陈述', 'err')
      try {
        const d = await api('/court', {
          method: 'POST',
          body: JSON.stringify({
            order_id: this.courtForm.order_id,
            statement: this.courtForm.statement,
            days: Number(this.courtForm.days) || 3,
          }),
        })
        this.courtModal = false
        this.notify('已开庭，等待围观群众投票判决')
        await this.loadCourt()
        this.openCourtDetail(d.id)
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    // 案件详情页
    async openCourtDetail(id) {
      try {
        const d = await api('/court/' + id)
        this.courtDetail = d
        this.courtComment = ''
        this.courtStmt = ''
        this.courtStmtOpen = false
        this.tab = 'courtDetail'
        if (location.hash !== '#court/' + id) location.hash = 'court/' + id
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    // 当事人补充/修改自己的陈述
    async submitCourtStatement() {
      if (!this.courtStmt.trim()) return this.notify('陈述不能为空', 'err')
      try {
        const d = await api(`/court/${this.courtDetail.id}/statement`, {
          method: 'POST',
          body: JSON.stringify({ statement: this.courtStmt }),
        })
        this.courtDetail = { ...this.courtDetail, ...d }
        this.courtStmtOpen = false
        this.notify('陈述已提交')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    // 投票站队
    async voteCourt(side) {
      if (this.courtVoting) return
      this.courtVoting = true
      try {
        const res = await api(`/court/${this.courtDetail.id}/vote`, {
          method: 'POST',
          body: JSON.stringify({ side }),
        })
        this.courtDetail.votes_buyer = res.votes_buyer
        this.courtDetail.votes_seller = res.votes_seller
        this.courtDetail.my_vote = res.my_vote
        this.notify(res.my_vote === side ? `已投：站${side === 'buyer' ? '买家' : '卖家'}` : '已改票')
      } catch (e) {
        this.notify(e.message, 'err')
      } finally {
        this.courtVoting = false
      }
    },

    // 围观评论
    async submitCourtComment() {
      if (!this.courtComment.trim()) return this.notify('评论不能为空', 'err')
      try {
        const c = await api(`/court/${this.courtDetail.id}/comments`, {
          method: 'POST',
          body: JSON.stringify({ content: this.courtComment }),
        })
        this.courtDetail.comments.push(c)
        this.courtComment = ''
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    // 删除案件（发起人/当事人）
    async deleteCourt(id) {
      if (!confirm('确定撤销这件案子吗？投票和评论会一起删除。')) return
      try {
        await api('/court/' + id, { method: 'DELETE' })
        this.notify('案件已撤销')
        this.tab = 'court'
        location.hash = 'court'
        await this.loadCourt()
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    backToCourt() {
      this.tab = 'court'
      location.hash = 'court'
      this.courtDetail = null
      this.loadCourt()
    },

    onSortChange() {
      this.loadProducts({ reset: true, reshuffle: true })
    },

    // 用户中心：改省 → 清市县；改市 → 清县
    onProfileProvChange() {
      this.profileRegion.city = ''
      this.profileRegion.district = ''
    },
    onProfileCityChange() {
      this.profileRegion.district = ''
    },

    /* ============ 商品详情页（原来是弹窗） ============ */

    // 打开详情：拉完整数据（含评论），并切到详情页
    async openDetail(p, from) {
      const id = typeof p === 'number' ? p : p.id
      this.detailFrom = from || this.tab
      try {
        const data = await api(`/products/${id}`)
        this.detail = data
        this.tab = 'product'
        if (location.hash !== '#product/' + id) location.hash = 'product/' + id
        this.commentText = ''
        this.replyTo = null
        this.replyText = ''
        this.setMedia(data.images[0] || '')
        window.scrollTo(0, 0)
        // 从消息页跳来的话商品可能刚被卖掉，顺手把会话里的状态也刷了
        if (this.activeConv && this.activeConv.product && this.activeConv.product.id === id) {
          await this.loadConversations()
        }
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    // 返回打开详情前的那个栏目
    closeDetail() {
      const from = this.detailFrom || 'home'
      this.switchTab(from === 'product' ? 'home' : from)
    },

    // 切换详情页正在展示的图片/视频
    setMedia(src) {
      this.activeMediaSrc = src || ''
      this.activeMediaIsVideo = /\.(mp4|webm|mov|m4v)$/i.test(this.activeMediaSrc)
    },

    // 发布评论
    async postComment() {
      const text = this.commentText.trim()
      if (!text || !this.detail) return
      try {
        const res = await api(`/products/${this.detail.id}/comments`, {
          method: 'POST',
          body: JSON.stringify({ content: text }),
        })
        this.detail.comments = res.comments
        this.commentText = ''
        this.notify('评论已发布')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    // 卖家回复评论
    startReply(c) {
      this.replyTo = c
      this.replyText = ''
    },

    cancelReply() {
      this.replyTo = null
      this.replyText = ''
    },

    async sendReply() {
      const text = this.replyText.trim()
      if (!text || !this.replyTo) return
      try {
        const res = await api(`/products/${this.detail.id}/comments`, {
          method: 'POST',
          body: JSON.stringify({ content: text, reply_to_id: this.replyTo.id }),
        })
        this.detail.comments = res.comments
        this.cancelReply()
        this.notify('已回复')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    async buy(p) {
      if (!confirm(`确认用 ¥${p.price} 买下「${p.title}」吗？`)) return
      this.buying = true
      try {
        const res = await api(`/products/${p.id}/buy`, { method: 'POST' })
        this.me.balance = res.balance
        await this.loadProducts()
        this.notify('购买成功，订单已进入「待发货」')
        // 刷新详情页：商品已经变成自己的了，状态也会变成已下架
        if (this.detail && this.detail.id === p.id) {
          this.detail = await api(`/products/${p.id}`)
        }
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
      // 成交（或卖家下架）之后商品就不在售了，议价没有意义，后端也会拦
      if (this.activeConv.product.status !== 'on') {
        return this.notify('商品已成交或下架，无法改价', 'err')
      }
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
      this.createForm = { title: '', price: '', tags: [], description: '', image: '', images: [], videos: [] }
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
        images: [...(p.images || [])],
        videos: [...(p.videos || [])],
      }
      this.showCreate = true
    },

    toggleCreateTag(t) {
      const i = this.createForm.tags.indexOf(t)
      if (i >= 0) this.createForm.tags.splice(i, 1)
      else this.createForm.tags.push(t)
    },

    // 多张商品介绍图：循环上传，全部传完才入库
    async uploadProductImages(e) {
      const files = [...e.target.files]
      e.target.value = ''
      if (!files.length) return
      for (const file of files) {
        try {
          this.createForm.images.push(await uploadFile(file))
        } catch (err) {
          this.notify(err.message, 'err')
          break
        }
      }
    },

    // 商品介绍视频（一次一个，可以传多个视频）
    async uploadProductVideo(e) {
      const file = e.target.files[0]
      e.target.value = ''
      if (!file) return
      try {
        this.createForm.videos.push(await uploadFile(file))
        this.notify('视频已上传')
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
      // 所在地区：省/市/县 整组一起提交
      body.province = this.profileRegion.province
      body.city = this.profileRegion.city
      body.district = this.profileRegion.district
      if (!Object.keys(body).length) return this.notify('没有要修改的内容', 'err')
      try {
        this.me = await api('/me', { method: 'PUT', body: JSON.stringify(body) })
        this.profileForm.password = ''
        this.syncProfileRegion()
        this.notify(this.me.region ? '资料已保存，所在地区：' + this.me.region : '资料已保存')
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

    /* ================= AI 淘好物 ================= */
    /* ================= 3D 看板：小余 ================= */
    startPet() {
      this.stopPet()
      // 面板开合直接读 agentOpen，所以她会在面板打开时走到面板旁边站好
      this._pet = window.AgentPet && AgentPet.create({
        host: this.$refs.agentPet,
        onClick: () => this.openAgent(),
        getPanelOpen: () => this.agentOpen,
        onFail: () => { this.stopPet(); this.petBroken = true },
      })
      window.__xiaoyu = this._pet || null      // 调试句柄：控制台可看 snapshot()
      this.petBroken = !this._pet
    },

    stopPet() {
      if (this._pet) { this._pet.destroy(); this._pet = null }
    },

    openAgent() {
      this.agentOpen = true
      this.scrollAgent()
    },

    scrollAgent() {
      nextTick(() => {
        const el = this.$refs.agentBody
        if (el) el.scrollTop = el.scrollHeight
      })
    },

    // 点快捷提问：填进输入框直接发
    askAgent(text) {
      this.agentInput = text
      this.sendAgent()
    },

    // 点 Agent 里的商品卡片：先收起面板再打开详情弹窗，
    // 不然详情弹窗会被悬浮面板压在下面
    openAgentDetail(p) {
      this.agentOpen = false
      this.openDetail(p)
    },

    async sendAgent() {
      const text = this.agentInput.trim()
      if (!text || this.agentLoading) return
      this.agentInput = ''
      this.agentMsgs.push({ role: 'user', text, products: [] })
      this.scrollAgent()

      this.agentLoading = true
      try {
        // 只把文字历史发给后端，商品卡片不用带
        const history = this.agentMsgs.map((m) => ({ role: m.role, content: m.text }))
        const res = await api('/agent/chat', {
          method: 'POST',
          body: JSON.stringify({ messages: history }),
        })
        this.agentMsgs.push({ role: 'assistant', text: res.reply, products: res.products || [] })
      } catch (e) {
        this.agentMsgs.push({ role: 'assistant', text: '⚠️ ' + e.message, products: [] })
      } finally {
        this.agentLoading = false
        this.scrollAgent()
      }
    },

    /* ================= 我的（总览页） ================= */

    async loadMineSummary() {
      // 首选：一次请求拿全部计数。接口失败（比如服务是改动前启动的老进程）
      // 就并行拉 5 个列表接口，本地实时计算——保证一打开"我的"数字就是准的
      try {
        this.mineSummary = await api('/mine/summary')
      } catch (e) {
        console.warn('summary 接口不可用，改为并行拉取各列表计算角标', e)
        try {
          const results = await Promise.allSettled([
            api('/my-products'),
            api('/orders'),
            api('/favorites'),
            api('/history'),
            api('/me/following'),
          ])
          const values = results.map((r) => (r.status === 'fulfilled' ? r.value : null))
          const [products, orders, favorites, history, following] = values
          // 顺手把拉到的数据存起来，进对应子页面时不用再请求一次
          if (products) this.myProducts = products
          if (orders) this.orders = orders
          if (favorites) this.favorites = favorites
          if (history) this.history = history
          if (following) this.following = following
          this.mineSummary = {
            products: this.myProducts.length,
            sold: this.orders.sold.length,
            bought: this.orders.bought.length,
            favorites: this.favorites.length,
            history: this.history.length,
            following: this.following.length,
          }
        } catch (err) {
          /* 彻底失败时保持旧值，不打扰用户 */
        }
      }
    },

    // 点总览页的入口卡片：跳到对应子页面
    async goMine(kind) {
      if (kind === 'items') return this.switchTab('items')
      if (kind === 'orders-sold') {
        this.orderTab = 'sold'
        return this.switchTab('orders')
      }
      if (kind === 'orders-bought') {
        this.orderTab = 'bought'
        return this.switchTab('orders')
      }
      return this.switchTab(kind)      // favorites / history / following
    },

    async loadFavorites() {
      try {
        this.favorites = await api('/favorites')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    async loadHistory() {
      try {
        this.history = await api('/history')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    async loadFollowing() {
      try {
        this.following = await api('/me/following')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    /* ================= 卖家小铺主页 ================= */

    // 点卖家头像/名字 → 进入他的小铺
    async openShop(uid, from) {
      if (!uid) return
      this.shopFrom = from || this.tab
      try {
        this.shop = await api(`/users/${uid}/profile`)
        this.tab = 'user'
        if (location.hash !== '#user/' + uid) location.hash = 'user/' + uid
        window.scrollTo(0, 0)
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    closeShop() {
      const from = this.shopFrom || 'home'
      this.switchTab(from === 'user' ? 'home' : from)
    },

    // 小铺主页上的关注 / 取关
    async toggleFollowShop() {
      if (!this.shop || this.shop.is_me) return
      try {
        const res = await api(`/users/${this.shop.id}/follow`, {
          method: this.shop.is_following ? 'DELETE' : 'POST',
        })
        this.shop.is_following = res.following
        this.shop.followers = res.followers
        this.notify(res.following ? `已关注 ${this.shop.username}` : '已取消关注')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    // 详情页卖家卡片上的关注 / 取关
    async toggleFollowSeller() {
      if (!this.detail || this.detail.is_mine) return
      try {
        const res = await api(`/users/${this.detail.owner.id}/follow`, {
          method: this.detail.is_following ? 'DELETE' : 'POST',
        })
        this.detail.is_following = res.following
        this.detail.seller_followers = res.followers
        this.notify(res.following ? '已关注卖家' : '已取消关注')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    // 详情页收藏 / 取消收藏
    async toggleFavorite() {
      if (!this.detail) return
      try {
        const res = await api(`/products/${this.detail.id}/favorite`, {
          method: this.detail.is_favorited ? 'DELETE' : 'POST',
        })
        this.detail.is_favorited = res.favorited
        this.notify(res.favorited ? '已加入收藏' : '已取消收藏')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    // 关注列表里直接取关
    async unfollowFromList(u) {
      try {
        await api(`/users/${u.id}/follow`, { method: 'DELETE' })
        await this.loadFollowing()
        this.notify(`已取消关注 ${u.username}`)
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    /* ================= 编辑主页 ================= */

    openEditMe() {
      this.syncProfileRegion()
      this.switchTab('editme')
    },

    // 点某一行资料 → 弹出对应的编辑器，先把当前值填进表单
    startEdit(field) {
      this.editPop = field
      this.editForm = {
        username: this.me.username,
        bio: this.me.bio,
        gender: this.me.gender,
        birthday: this.me.birthday,
        likesArr: this.me.likes ? this.me.likes.split(',').filter(Boolean) : [],
        school: this.me.school,
      }
      if (field === 'region') this.syncProfileRegion()
    },

    cancelEdit() {
      this.editPop = null
      this.syncProfileRegion()    // 万一地区改了一半取消，恢复成已保存的值
    },

    toggleLike(t) {
      const i = this.editForm.likesArr.indexOf(t)
      if (i >= 0) this.editForm.likesArr.splice(i, 1)
      else this.editForm.likesArr.push(t)
    },

    async saveEdit() {
      const f = this.editPop
      const body = {}
      if (f === 'username') {
        if (this.editForm.username.length < 2) return this.notify('昵称至少 2 个字', 'err')
        if (this.editForm.username !== this.me.username) body.username = this.editForm.username
      } else if (f === 'bio') body.bio = this.editForm.bio
      else if (f === 'gender') body.gender = this.editForm.gender
      else if (f === 'birthday') body.birthday = this.editForm.birthday
      else if (f === 'likes') body.likes = this.editForm.likesArr.join(',')
      else if (f === 'school') body.school = this.editForm.school
      else if (f === 'region') {
        body.province = this.profileRegion.province
        body.city = this.profileRegion.city
        body.district = this.profileRegion.district
      }
      if (!Object.keys(body).length) {
        this.editPop = null
        return
      }
      try {
        this.me = await api('/me', { method: 'PUT', body: JSON.stringify(body) })
        this.editPop = null
        this.notify('已保存')
      } catch (e) {
        this.notify(e.message, 'err')
      }
    },

    /* ================= 以图搜物 ================= */

    // 搜索栏相机图标 / 结果页"换一张"入口：弹出发起面板
    openImgSearchPicker() {
      this.imgSearchFrom = this.tab === 'imgsearch' ? this.imgSearchFrom : this.tab
      this.camShot = ''
      this.camMode = 'idle'
      this.camOpen = true
    },

    closeCam() {
      this.stopCamStream()
      this.camOpen = false
      this.camMode = 'idle'
      this.camShot = ''
    },

    async startCam() {
      try {
        // 手机优先调后置摄像头，桌面走默认摄像头
        this.camStream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'environment' },
          audio: false,
        })
        this.camMode = 'live'
        this.$nextTick(() => {
          if (this.$refs.camVideo) this.$refs.camVideo.srcObject = this.camStream
        })
      } catch (e) {
        this.notify('相机打开失败（可能没授权或没有摄像头），可以改用上传图片', 'err')
        this.camMode = 'idle'
      }
    },

    stopCamStream() {
      if (this.camStream) {
        this.camStream.getTracks().forEach((t) => t.stop())
        this.camStream = null
      }
    },

    // 把视频当前帧截到 canvas，变成 dataURL
    shootCam() {
      const video = this.$refs.camVideo
      if (!video || !video.videoWidth) return this.notify('相机还没准备好，稍等一下', 'err')
      const canvas = this.$refs.camCanvas
      canvas.width = video.videoWidth
      canvas.height = video.videoHeight
      canvas.getContext('2d').drawImage(video, 0, 0)
      this.camShot = canvas.toDataURL('image/jpeg', 0.9)
      this.stopCamStream()
      this.camMode = 'shot'
    },

    retakeCam() {
      this.camShot = ''
      this.startCam()
    },

    pickImgSearchFile() {
      this.$refs.imgSearchFile.click()
    },

    // 相册选图（手机上系统选单自带"拍照"选项）：选完直接搜
    async onImgSearchFile(e) {
      const file = e.target.files[0]
      e.target.value = ''
      if (!file) return
      this.imgSearchImg = URL.createObjectURL(file)
      await this.doImgSearch(file)
    },

    // 拍好的照片（dataURL → Blob）发起搜索
    async searchByImage() {
      if (!this.camShot) return
      const [meta, b64] = this.camShot.split(',')
      const mime = (meta.match(/:(.*?);/) || [])[1] || 'image/jpeg'
      const bin = atob(b64)
      const u8 = new Uint8Array(bin.length)
      for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i)
      this.imgSearchImg = this.camShot
      await this.doImgSearch(new Blob([u8], { type: mime }))
    },

    async doImgSearch(fileOrBlob) {
      this.imgSearching = true
      this.imgRecog = null
      try {
        const fd = new FormData()
        fd.append('file', fileOrBlob, 'photo.jpg')
        const res = await fetch('/api/search/image', {
          method: 'POST',
          credentials: 'same-origin',
          body: fd,
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(data.error || '搜索失败')
        this.imgResults = data.results
        this.imgRecog = data.mode === 'ai' ? (data.recognition || null) : null
        this.closeCam()
        this.tab = 'imgsearch'
        if (location.hash !== '#imgsearch') location.hash = 'imgsearch'
        window.scrollTo(0, 0)
        this.notify(data.mode === 'ai'
          ? `AI 认出这是「${this.imgRecog ? this.imgRecog.name : ''}」，找到 ${data.count} 件相关宝贝`
          : `找到 ${data.count} 件相似宝贝`)
      } catch (e) {
        this.notify(e.message, 'err')
      } finally {
        this.imgSearching = false
      }
    },

    closeImgSearch() {
      const from = this.imgSearchFrom === 'imgsearch' ? 'home' : (this.imgSearchFrom || 'home')
      this.switchTab(from)
    },

    /* ================= 切换标签页 ================= */
    async switchTab(key) {
      this.tab = key
      // 详情页/小铺的地址带 id（#product/12、#user/2），不能被这里覆盖
      if (key !== 'product' && key !== 'user' && location.hash !== '#' + key) location.hash = key
      if (key === 'home') await this.loadProducts()
      if (key === 'court') await this.loadCourt()
      if (key === 'msg') await this.loadConversations()
      if (key === 'mine') await this.loadMineSummary()
      if (key === 'items') await this.loadMyProducts()
      if (key === 'orders') await this.loadOrders()
      if (key === 'favorites') await this.loadFavorites()
      if (key === 'history') await this.loadHistory()
      if (key === 'following') await this.loadFollowing()
      if (key === 'editme') this.syncProfileRegion()
      if (key === 'me') {
        this.profileForm.username = this.me.username
        this.syncProfileRegion()
        this.ensureRegions()
      }
    },
  },
})
const __root = __app.mount('#app')
// 调试句柄：控制台可用 __app.me / __app.doImgSearch() 等，便于排查问题
window.__app = __root && __root.me !== undefined ? __root : (__app._instance && __app._instance.proxy ? __app._instance.proxy : __app)

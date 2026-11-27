/* =========================================================================
   小余 —— 古风 Live2D 桌宠（替代右下角的 AI 悬浮球）
   引擎：PIXI 6 + pixi-live2d-display(Cubism2) + Live2D Cubism 2 core
   模型：食物语·冰糖葫芦（红斗篷双马尾喜庆小妹妹，本地化于 static/live2d/bingtanghulu/，
   素材来自公开模型收集仓库，仅用于个人课程作业演示）

   行为（按需求收敛）：
   1. 固定待在屏幕右下角，播放待机动作（轻微呼吸）
   2. 鼠标在哪，她眼睛/头就平滑转向哪（model.focus）
   3. 点击她 → 举手动作 → 打开 AI 淘好物面板
   ========================================================================= */
(function (global) {
  'use strict'

  const PANEL_RIGHT = 28    // 与 .agent-panel 的 right / width 保持一致
  const PANEL_WIDTH = 380
  const MODEL_URL = '/static/live2d/bingtanghulu/bingtanghulu.model.json'

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v))

  function create(opts) {
    const host = opts.host
    const PIXI = global.PIXI
    if (!host || !PIXI || !PIXI.live2d) return null     // 库没加载成功 → 走悬浮球兜底

    /* ---------- 渲染层 ---------- */
    let app
    try {
      app = new PIXI.Application({
        width: global.innerWidth,
        height: global.innerHeight,
        backgroundAlpha: 0,
        antialias: true,
        autoDensity: true,
        resolution: Math.min(global.devicePixelRatio || 1, 2),
      })
    } catch (e) {
      return null
    }
    host.appendChild(app.view)

    const tip = document.createElement('div')
    tip.className = 'agent-pet-tip'
    tip.textContent = '点我，帮你淘好物'
    host.appendChild(tip)

    /* ---------- 状态 ---------- */
    let W = global.innerWidth, H = global.innerHeight, spriteH = 0, naturalH = 0
    let x = 0, y = 0                    // 脚底锚点（屏幕像素）
    let model = null, dead = false
    let mouseX = 0, mouseY = 0, mouseSet = false, hover = false
    let bornAt = performance.now()

    function homeSpot() {
      // 固定待在右下角：面板打开时让开面板，露出完整身体
      const pw = Math.min(PANEL_WIDTH, W - 32)
      return { x: W - PANEL_RIGHT - (opts.getPanelOpen() ? pw : 0) - spriteH * 0.62, y: H * 0.985 }
    }

    function fit() {
      spriteH = clamp(H * 0.2375, 162, 250)
      if (!naturalH) naturalH = model.height / model.scale.y   // height 含缩放，除回去才是原始高度
      model.scale.set(spriteH / naturalH)
      if (model.anchor) {
        model.anchor.set(0.5, 0.97)       // 锚点≈脚底
      } else {
        model.pivot.set(model.width / (2 * model.scale.x), naturalH * 0.97)
      }
    }

    function resize() {
      W = global.innerWidth
      H = global.innerHeight
      app.renderer.resize(W, H)
      if (model) { fit(); const s = homeSpot(); x = s.x; y = s.y; model.position.set(x, y) }
    }

    function hitTest(cx, cy) {
      if (!model) return false
      const r = model.getBounds()
      if (!r.width) return false
      const mx = r.width * 0.1, my = r.height * 0.04
      return cx >= r.left - mx && cx <= r.right + mx && cy >= r.top - my && cy <= r.bottom + my
    }

    /* ---------- 事件 ---------- */
    const onMove = (e) => {
      mouseX = e.clientX; mouseY = e.clientY; mouseSet = true
      hover = hitTest(mouseX, mouseY)
      document.body.style.cursor = hover ? 'pointer' : ''
    }
    const onTouch = (e) => {
      const t = e.touches && e.touches[0]
      if (!t) return
      mouseX = t.clientX; mouseY = t.clientY; mouseSet = true
    }
    const onDown = (e) => {
      if (e.button !== undefined && e.button !== 0) return
      if (!hitTest(e.clientX, e.clientY)) return
      e.preventDefault()
      e.stopPropagation()              // 别让她底下的按钮/卡片误触
      if (model) {
        try { model.motion('tap_body') } catch (err) { /* 忽略 */ }
      }
      opts.onClick()
    }
    const onLeave = () => { hover = false; document.body.style.cursor = '' }

    global.addEventListener('resize', resize)
    global.addEventListener('pointermove', onMove, { passive: true })
    global.addEventListener('touchmove', onTouch, { passive: true })
    global.addEventListener('pointerdown', onDown, true)
    document.addEventListener('mouseleave', onLeave)

    /* ---------- 每帧 ---------- */
    app.ticker.add(() => {
      if (dead || !model) return
      if (!host.clientWidth) return            // 登录页等隐藏状态下不动

      // 固定位置（窗口/面板开合变化时平滑贴回右下角）
      const s = homeSpot()
      const k = 1 - Math.exp(-4 * (app.ticker.deltaMS / 1000))
      x += (s.x - x) * k
      y += (s.y - y) * k
      model.position.set(x, y)

      // 视线/头部平滑追踪鼠标
      if (mouseSet) model.focus(mouseX, mouseY)

      // 头顶提示气泡
      const showTip = !opts.getPanelOpen() && (hover || performance.now() - bornAt < 6000)
      tip.classList.toggle('show', showTip)
      if (showTip) {
        const r = model.getBounds()
        tip.style.left = (r.left + r.width / 2) + 'px'
        tip.style.top = (r.top - 8) + 'px'
      }
    })

    /* ---------- 加载模型 ---------- */
    global.PIXI.live2d.Live2DModel.from(MODEL_URL, { autoInteract: false, autoUpdate: true })
      .then((m) => {
        if (dead) { m.destroy(); return }
        model = m
        m.interactive = false
        app.stage.addChild(m)
        resize()
        const s = homeSpot()
        x = s.x; y = s.y
        m.position.set(x, y)
      })
      .catch((e) => {
        console.warn('[小余] Live2D 模型加载失败', e)
        destroy()
        if (opts.onFail) opts.onFail()
      })

    function destroy() {
      if (dead) return
      dead = true
      global.removeEventListener('resize', resize)
      global.removeEventListener('pointermove', onMove)
      global.removeEventListener('touchmove', onTouch)
      global.removeEventListener('pointerdown', onDown, true)
      document.removeEventListener('mouseleave', onLeave)
      document.body.style.cursor = ''
      try { app.destroy(true, { children: true, texture: true, baseTexture: true }) } catch (e) { /* 忽略 */ }
      if (app.view && app.view.parentNode) app.view.parentNode.removeChild(app.view)
      tip.remove()
    }

    return {
      destroy,
      // 调试
      snapshot() {
        return { x: Math.round(x), y: Math.round(y), hasModel: !!model, hover, mouseSet,
                 w: model ? Math.round(model.width) : 0, h: model ? Math.round(model.height) : 0,
                 sy: model ? +model.scale.y.toFixed(4) : 0, spriteH }
      },
    }
  }

  global.AgentPet = { create }
})(window)

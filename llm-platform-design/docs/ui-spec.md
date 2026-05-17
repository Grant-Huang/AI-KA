# UI 规范

## 一、布局规范

### 三栏结构

```
┌──────────┬───────────────┬─────────────────────────────────────┐
│  左栏     │    中栏        │              右栏                    │
│ 图标菜单  │  会话历史      │           主工作区                   │
│ 126px    │  260px        │         flex: 1                     │
│ (折叠48px)│  (可隐藏)     │                                     │
└──────────┴───────────────┴─────────────────────────────────────┘
```

**左栏**（AppSidebar）
- 展开宽度：`126px`，折叠宽度：`48px`
- 过渡动画：`0.2s ease`
- 内容：App 图标导航 + 新建会话按钮 + 用户信息（底部）
- 折叠时：隐藏文字标签，仅显示图标，图标居中

**中栏**（SessionColumn）
- 固定宽度：`260px`
- 内容：当前 App 的会话历史列表，支持搜索、分组（今天/昨天/更早）
- 可通过 AppSidebar 切换 App 时切换对应会话列表

**右栏**（AppMain）
- 分屏模式（有 Artifact 时）：左 60% Chat + 右 40% Artifact，中间分隔条可拖动
- 纯聊天模式：全宽，内容最大宽度 `820px` 居中

### 分屏拖动

- 分隔条宽度：`4px`，hover 时高亮为 `#9cb8a8`，cursor: `col-resize`
- 拖动范围：左侧最小 `40%`，最大 `80%`
- 拖动时禁用 `user-select`，松开后恢复
- 记忆分割比例到 `localStorage`

---

## 二、配色系统

### 主色板

| Token | 值 | 用途 |
|-------|----|------|
| `--color-bg` | `#ecefe9` | 页面背景、侧栏背景 |
| `--color-bg-elevated` | `#f4f6f2` | 内容卡片背景 |
| `--color-bg-white` | `#ffffff` | 输入框、气泡白底 |
| `--color-bg-sidebar` | `#f7f7f3` | 会话历史栏背景 |
| `--color-text` | `#2f3a32` | 主文字 |
| `--color-text-secondary` | `rgba(47,58,50,0.6)` | 次要文字 |
| `--color-text-muted` | `rgba(47,58,50,0.4)` | 辅助文字、时间戳 |
| `--color-accent` | `#527c5e` | 强调色（激活状态、链接） |
| `--color-accent-dark` | `#2f7d4a` | 深强调色（正向操作） |
| `--color-border` | `#d9dfd7` | 边框 |
| `--color-border-light` | `rgba(47,58,50,0.1)` | 轻边框、分隔线 |

### 状态色

| Token | 值 | 用途 |
|-------|----|------|
| `--color-error` | `#c0392b` | 错误 |
| `--color-warning` | `#b45309` | 警告 |
| `--color-success` | `#2f7d4a` | 成功 |
| `--color-info` | `#527c5e` | 信息 |

### 会话激活样式

```css
/* 激活态：绿色左边框 + 浅绿背景 */
border-left: 2px solid #527c5e;
background: rgba(82, 124, 94, 0.12);
```

---

## 三、字体规范

```css
font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
```

| 场景 | font-size | font-weight | line-height |
|------|-----------|-------------|-------------|
| 页面主体 | 15px | 400 | 1.6 |
| 聊天气泡 | 14px | 400 | 1.6 |
| Markdown 正文 | 14-15px | 400 | 1.65-1.7 |
| 小标签/时间 | 11-12px | 400 | 1.35 |
| 侧栏会话标题 | 13px | 400/600(激活) | 1.4 |
| 页面标题 | 15px | 650 | — |
| Welcome 标题 | 24px | 650 | — |

---

## 四、圆角规范

| 元素 | border-radius |
|------|---------------|
| 卡片/面板 | `10px` |
| 按钮 | `8px` |
| 输入框 | `8px` |
| 会话列表项 | `6px` |
| 聊天气泡（用户） | `14px 14px 4px 14px` |
| 代码块 | `8px` |
| 弹出菜单 | `12px` |

---

## 五、关键组件规范

### Composer（输入框）

```
┌──────────────────────────────────────────────────────┐
│  TextArea（无边框，背景白，font-size: 15px）           │
├──────────────────────────────────────────────────────┤
│  [知识库] [Tools▾]  ···  [附件] [发送 ↵]             │
└──────────────────────────────────────────────────────┘
```
- 整体容器：`border: 1px solid #e0e0d8; border-radius: 10px; background: #fff`
- 最大宽度：`900px`，底部固定定位（`position: fixed`）
- 底部安全区：`env(safe-area-inset-bottom)`

### 聊天气泡

**用户消息**
- 右对齐，最大宽度 `75%`
- 背景 `#fff`，边框 `1px solid #d9dfd7`，圆角 `14px 14px 4px 14px`

**AI 回复**
- 左对齐，最大宽度 `90%`，背景透明
- Markdown 渲染，代码高亮
- Think block 可折叠（默认折叠）
- hover 时显示操作栏（复制 / 点赞 / 踩）

### Artifact 面板

```
┌─────────────────────────────────────┐
│ [tab1] [tab2] [tab3]         [⊞ 新] │
├─────────────────────────────────────┤
│                                     │
│   ArtifactRenderer                  │
│   （按类型渲染内容）                  │
│                                     │
├─────────────────────────────────────┤
│ [复制] [下载] [存入记忆] [全屏]       │
└─────────────────────────────────────┘
```

- 背景 `#f4f6f2`，左边框 `1px solid #d9dfd7`
- 代码类型：highlight.js，行号显示
- HTML 类型：沙箱 `<iframe sandbox="allow-scripts">`
- Mermaid 类型：mermaid.js 渲染为 SVG

### 阶段进度条（Stage）

```
● 召回记忆 ✓       ← done：绿点
● 检索知识 ✓
⟳ 分析中...        ← active：旋转点 + 文字
○ 生成结果          ← pending：空心灰点
```

时间轴样式：左侧 `1px` 竖线 + 节点圆点，继承自 AI-KA 的 `.milestone-timeline`。

---

## 六、Ant Design 定制

全局 ConfigProvider 覆盖 token：

```typescript
const theme = {
  token: {
    colorPrimary: '#527c5e',
    colorBgBase: '#ecefe9',
    borderRadius: 8,
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    fontSize: 14,
  },
  components: {
    Button: { borderRadius: 8 },
    Input: { borderRadius: 8 },
    Select: { borderRadius: 8 },
  },
}
```

---

## 七、响应式断点

平台面向桌面端设计，最小支持宽度 `900px`。

| 宽度 | 行为 |
|------|------|
| `≥ 1200px` | 标准三栏 |
| `900px - 1200px` | 侧栏自动折叠为 48px |
| `< 900px` | 不做特殊处理（平台定位桌面） |

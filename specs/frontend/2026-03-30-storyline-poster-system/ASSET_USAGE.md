# Storyline Poster System Asset Usage

## 母版页面

### 1. Create
- 主视觉：`skyline-sofa`
- 语义：冷静、可压标题、像在夜色里起草一份关系案卷
- 不做切换

### 2. Loading
- 主视觉：`penthouse-rainy`
- 语义：案卷编译中，雨夜、余温、等待失控
- 不做切换

### 3. Library / Archive
- 主视觉切换组：
  - `forbidden-table`
  - `lounge-obsidian`
  - `boardroom-marble`
  - `exterior-building`
- 交互：手动切换 featured dossier，不改 grid 浏览逻辑

### 4. Detail
- Hero 切换组：
  - `wealth` -> `forbidden-table / lounge-obsidian / premium-still-life`
  - `office` -> `boardroom-obsidian / boardroom-marble / evidence-dark`
  - `entertainment` -> `lounge-obsidian / lounge-amber / premium-still-life`
  - `campus` -> `skyline-sofa / corridor-shadow / premium-still-life`
  - `supernatural` -> `penthouse-rainy / corridor-shadow / evidence-dark`
- 交互：同一 story 内的 framing 切换，不切 story

## 人像使用

### 人物卡
- 女：`female-profile-reference`
- 男：`male-profile-reference`
- 危险变体：`noir-variant-reference`

### 规则
- 人物卡只放在 `Detail` 的 profile grid
- hero 不直接使用人物卡素材

## 辅助素材
- `premium-still-life`：通用证据模块
- `evidence-dark`：office / noir 证据模块
- `corridor-shadow`：过渡 / 章节 / moment
- `car-interior`：后续 play 或特殊场景模块

## 禁止直接使用
- `boardroom-intimate`
- `boardroom-rainy`
- `minimalist-vista`
- 所有带完整文案和按钮的 screenshot

## 备注
- 当前 repo 已先在前端实现 poster-switcher 和接图。
- 若后续 Figma 可写工具恢复，这份文档直接作为 4 个 desktop frame 与 asset usage sheet 的落稿依据。

# 项目暂停 Memo: 机制成立,产品需求未证明

日期: 2026-05-09 PDT

## 结论

暂停 Tiny Stories / RPG_Demo_refactor 的主动产品开发.

这个仓库应保留为一个 LLM 互动叙事工程案例:结构化 prompt contract、
scheduler-driven LLM control、有状态 turn runtime、有限结局、branch/highlight
生成、playtest/benchmark 工具.它不应被视为已经成立的消费级娱乐产品.

## 为什么停

- 技术闭环可以跑,但真实用户需求未被证明.
- 项目目前没有经过验证的真人测试数据.
- 玩家 agency 仍是最大产品风险:系统会主动驱动戏剧结构,玩家选择有时更像触发器.
- 赛道已经拥挤:开放式 AI RPG、AI DM/TTRPG、角色聊天、公版书可游玩体验都已有成熟玩家.
- 继续加 UI、美术和机制不能回答核心问题:玩家是否愿意复玩、截图、分享.

## 保留什么

- `rpg_backend/narrative/`:prompt contract、scheduler、parser、有限结局/highlight/branch 生成.
- `rpg_backend/author_v2/` 和 `rpg_backend/author_v3/`:从 seed 到 play 的规划和发布管线模式.
- `rpg_backend/play_v2/`、`tools/urban_author_play_benchmarks/`、`tests/`:runtime/评测工具思路.
- `frontend2/`:主 React/Vite 游玩界面和可工作的 UX shell.
- `frontend2/public/webtoons/`、`docs/images/`、`docs/images/style-refs/`:可复用视觉方向资产.
- `ARCHITECTURE.zh.md`、`docs/devlog/2026-05-tiny-stories-9-mechanisms.zh.md`、`specs/`:设计理由和已知限制.

## 没有新证据前不要继续

- 不继续把它做成宽泛的 AI RPG 平台.
- 不继续投入首页包装、美术、多人、流式输出、多 provider 调度等功能.
- 不把 memory、lore card、long context、UGC world 当差异化;它们已经是品类入场券.
- 不重新激活旧 `frontend/`.
- 不把失败 benchmark artifact 当成功 baseline.

## 重启门槛

只有在更窄 demo 通过真人验证后才重启:

- 5-10 个真人测试者无需解释即可完成一局.
- 至少 40% 测试者想马上重玩另一张身份卡或另一条路径.
- 至少 30% 测试者愿意分享结局截图或链接.
- 用户能说出一个具体选择如何改变了剧情.
- 随机选、全选第一个选项、强自由输入三种路径要产生肉眼可见差异.
- 下一版 prototype 必须很小:1 个题材、3 张身份卡、6-8 回合、1 个可分享结果产物.

## 当前收尾状态

最终稳定化范围:

- Provider 兼容:去掉 Beecode chat/completions 不支持的 `enable_thinking`.
- Author v3 handoff:把已接受的游玩长度 preset 和 arc template 带进管线.
- Template routing:明确不支持的 seed 标记为 out of scope,避免硬匹配.
- Narrative parsing:选项 intent tag 按模板语言归一化,并干净截断过长 option/NPC pulse 文本.
- 前端 polish:修 active card border warning,恢复 Vite dev port 到 `5173`,补 public OG image,分离玩家 label/handle.
- 测试覆盖:新增 narrative option language 测试.

## 最后收尾验证

已于 2026-05-09 PDT 验证:

```bash
python -m pytest -q
cd frontend2
npm run check
npm run build
git diff --check
```

Vite 生产构建仍会提示主 bundle 约 500 kB 的非阻断 chunk-size warning.
这是已知优化项,不是收尾阻断项.

之后如果要改动或发布这个 archive 状态,先重新跑同一组命令.

如果配置了 LLM endpoint,可以做一次 live smoke:

```bash
uvicorn rpg_backend.main:app --host 127.0.0.1 --port 8000
cd frontend2
npm run dev -- --host 127.0.0.1 --port 5173
```

然后创建一个短故事、选身份、推进至少一回合.

## 启动备注

- 后端:`uvicorn rpg_backend.main:app --reload`
- 前端:`cd frontend2 && npm run dev`
- 默认前端端口:`5173`
- 必需配置:复制 `.env.example` 到 `.env`,设置 `APP_RESPONSES_PLAY_*` LLM endpoint 变量.
- 验证后关闭本地服务;暂停项目不应留下常驻服务.

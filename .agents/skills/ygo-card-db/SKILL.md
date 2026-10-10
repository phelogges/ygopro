---
name: ygo-card-db
description: 游戏王卡片数据库查询，提供两种检索方式：(1) 根据卡片8位密码(id)精确查询，返回结构化的卡片详细信息（类型、种族、属性、攻守、效果文本、系列、灵摆刻度、连接箭头等）；(2) 根据关键字在卡片描述文本中搜索，返回匹配的卡片id列表。当用户询问某张卡片的具体信息、需要查看效果文本、攻击力守备力、种族属性、或需要根据效果关键词找出相关卡片时使用此技能。
---

# 游戏王卡片数据库

从项目或发布包主目录的 `cards.cdb`（SQLite）中检索卡片，支持两种查询模式。技能位于 `<主目录>/.agents/skills/ygo-card-db/`，默认数据库路径为 `<主目录>/cards.cdb`；缺失时查询报错，不会创建空数据库。

## 功能一：卡片ID精确检索

根据卡片8位密码查询，返回包含完整卡片信息的 JSON。

### 命令行

以下命令在 `.agents/skills/ygo-card-db/` 目录中执行，以模块方式启动，避免 `scripts/types.py` 与 Python 标准库的 `types` 模块重名。

```bash
# 单张
uv run python -m scripts.query query 31809476

# 多张
uv run python -m scripts.query query 31809476 30064423

# 简写（省略 query 子命令，向后兼容）
uv run python -m scripts.query 31809476

# 附带登场地区信息
uv run python -m scripts.query query --include-availability 31809476

# 系列名双语输出
uv run python -m scripts.query query --archetype-output 0 31809476
```

可通过 `-h` 查看完整参数：

```bash
uv run python -m scripts.query query -h
```

### Python

```python
from scripts.query import CardQuery
from scripts.types import ArchetypeOutput

cq = CardQuery(
    include_availability=False,
    archetype_output=ArchetypeOutput.CHINESE_ONLY,
)
data = cq.query_by_id(31809476)                  # 单张 → dict
results = cq.query_by_ids([31809476, 30064423])  # 多张 → list[dict]
cq.close()
```

### 输出示例

```json
{
  "id": 41546,
  "name": "DD 魔导贤者 托马斯",
  "alias": null,
  "card_type": ["怪兽卡", "效果", "灵摆"],
  "race": "恶魔",
  "attribute": "暗",
  "atk": 1800,
  "def": 2600,
  "level": 8,
  "rank": null,
  "link": null,
  "pendulum_scales": {"左": 6, "右": 6},
  "link_markers": null,
  "archetypes": ["DD", "魔导"],
  "effect_categories": ["返回手卡", "特殊召唤", "效果无效"],
  "non_effect_text": "「DD 魔导贤者 托马斯」的怪兽效果1回合只能使用1次。",
  "effect_text": "①：以自己的灵摆区域1张「DD」卡为对象才能发动。...",
  "card_text": null,
  "p_effect_text": "①：自己主要阶段才能发动。从自己的额外卡组把1只表侧表示的「DD」灵摆怪兽加入手卡。",
  "p_non_effect_text": "「DD 魔导贤者 托马斯」的灵摆效果1回合只能使用1次。"
}
```

### 输出字段

所有字段始终存在，不适用的为 null：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 卡片8位密码 |
| `name` | string | 卡片名称 |
| `alias` | int\|null | 规则同名卡密码（异画卡为 null） |
| `card_type` | array | 类型列表，如 `["效果怪兽", "同调", "灵摆"]` |
| `race` | string\|null | 种族（怪兽卡） |
| `attribute` | string\|null | 属性（怪兽卡） |
| `atk` | int\|null | 攻击力，-2 表示"?" |
| `def` | int\|null | 守备力，连接怪兽为 null |
| `level` | int\|null | 等级（普通/同调/仪式/融合） |
| `rank` | int\|null | 阶级（XYZ怪兽） |
| `link` | int\|null | 连接值（连接怪兽） |
| `pendulum_scales` | object\|null | P刻度，`{"左": N, "右": N}` |
| `link_markers` | array\|null | 连接箭头方向 |
| `archetypes` | array | 字段名（系列） |
| `effect_categories` | array | `cards.cdb` 的卡组编辑器效果筛选分类；按 `strings.conf` 中 `!system 1100`–`1131` 的位序解码，不是游戏引擎的 `effect_category`，也不是逐条效果的规则判定 |
| `availability` | array | 登场地区（需 `include_availability=True`） |
| `effect_text` | string\|null | 效果文本（新卡格式） |
| `non_effect_text` | string\|null | 效果以外文本 |
| `card_text` | string\|null | 旧卡整体文本 |
| `p_effect_text` | string\|null | P效果文本（P怪兽） |
| `p_non_effect_text` | string\|null | P效果以外文本（P怪兽） |

---

## 功能二：关键字检索

在卡片描述文本（`desc` 字段）中搜索关键字，返回匹配的卡片 ID 列表。

### 命令行

```bash
# 搜索描述中含某个关键字的卡片
uv run python -m scripts.query search "青眼"

# 查看帮助
uv run python -m scripts.query search -h
```

### Python

```python
from scripts.query import CardQuery

cq = CardQuery()
ids = cq.search_by_keyword("青眼")  # → list[int]
cq.close()
```

### 输出示例

```json
{
  "keyword": "青眼",
  "ids": [2129638, 2783661, 5405695, 8240199, 9433350, ...]
}
```

---

## 参数

### CLI

| 参数 | 可用位置 | 说明 |
|------|----------|------|
| `--include-availability` | `query` | 输出 `availability` 字段 |
| `--archetype-output {0,1,2}` | `query` | 系列名语言：0=中日双语 1=仅中文(默认) 2=仅日文 |

### Python

`CardQuery` 构造参数（仅影响 `query_by_id` / `query_by_ids`）：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `db` | CardDatabase\|None | None | 数据库实例，None 时自动创建 |
| `include_availability` | bool | False | 是否输出 `availability` 字段 |
| `archetype_output` | ArchetypeOutput | CHINESE_ONLY | 系列名语言 |

## 文件结构

```
<项目或发布包主目录>/
├── cards.cdb                 # 客户端与技能共用的卡片数据库
└── .agents/skills/ygo-card-db/
    ├── SKILL.md              # 本文件
    ├── agents/openai.yaml    # UI 元数据
    └── scripts/
    ├── __init__.py
    ├── types.py              # 枚举定义、常量、ARCHETYPES 字典
    ├── db.py                 # CardDatabase — SQLite 访问层
    ├── text.py               # CardTextParser — 卡片文本解析
    └── query.py              # CardDecoder + CardQuery + CLI
```

## 依赖

- Python >= 3.12
- 仅标准库（sqlite3）

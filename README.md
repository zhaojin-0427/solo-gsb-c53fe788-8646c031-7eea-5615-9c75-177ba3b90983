# 双层电路板网格布线服务

基于 **Python + FastAPI + OR-Tools (CP-SAT)** 的双层电路板网格布线服务。
对所有网络**联合求解**，先最小化总过孔数，再最小化同层移动总步数，
并只在证明完成后才报告 `optimal` / `infeasible`。

## 快速开始

### Docker Compose（一键启动）

```bash
docker compose up --build
```

服务监听 `http://localhost:8000`：

- `POST /route` — 布线接口（CP-SAT 联合求解）
- `POST /inspect` — 走线审查接口（只校验给定候选路径，不重新求解）
- `POST /diagnose-open` — 断路诊断接口（按实测通断记录定位候选断路边）
- `GET  /health` — 健康检查
- `GET  /docs` — Swagger UI 交互文档

### 本地开发

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

运行测试：

```bash
pip install pytest httpx
python -m pytest tests/ -q
```

## 布线规则

- 网格宽、高均为 2～20 的整数；层编号为 `0` / `1`。
- 请求含两层各自的禁布格（`blocked`）以及 1～6 条双焊盘网络（`nets`）。
- 走线只能沿**同层正交相邻格**移动；**过孔**在原坐标打通两层（占两层各一格）。
- 每条网络的路径不得重复占格。
- 不同网络在**同层**的占格不得重合，也不得正交相邻（对角相邻允许）。
- 每条网络有非负过孔上限 `via_limit`。
- 目标（字典序）：先最小化**总过孔数**，再最小化**同层移动总步数**。

## POST /route

### 请求体

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `width` | int | 网格宽，2～20 |
| `height` | int | 网格高，2～20 |
| `blocked` | array | 禁布格列表，元素为 `{"x", "y", "layer"}`，可省略 |
| `nets` | array | 1～6 条网络 |
| `nets[].name` | string | 可选名称，缺省自动命名 `N1`、`N2`… |
| `nets[].pads` | array | 恰好 2 个焊盘，各为 `{"x", "y", "layer"}` |
| `nets[].via_limit` | int | 非负整数，该网过孔数上限 |

坐标从 `0` 开始，`0 <= x < width`，`0 <= y < height`，`layer ∈ {0, 1}`。

### 响应体

| 字段 | 说明 |
| --- | --- |
| `status` | `optimal`：已证明最优；`feasible`：10 秒限时到、已有可行方案（未证明最优）；`infeasible`：已证明无解；`unknown`：10 秒限时到、尚未找到任何可行方案 |
| `solve_time_seconds` | 求解耗时（秒） |
| `total_vias` | 总过孔数（`infeasible`/`unknown` 时为 `null`） |
| `total_moves` | 同层移动总步数（`infeasible`/`unknown` 时为 `null`） |
| `nets[].path` | 该网从 `pads[0]` 到 `pads[1]` 的有序占格序列（含过孔两端的层切换） |
| `nets[].vias` | 该网过孔坐标列表（该坐标两层均被占用） |
| `nets[].via_count` / `nets[].move_count` | 该网过孔数 / 同层移动步数 |

求解时限为每次请求 **10 秒**（可用环境变量 `ROUTER_TIME_LIMIT` 覆盖，
见 `docker-compose.yml`）。只有完成证明时才返回 `optimal` 或 `infeasible`；
限时触发时按是否已找到可行方案区分 `feasible` 与 `unknown`。

### 实际请求与响应示例

下面是一个真实可复现的例子（8×8 板，第 0 层 `x=3` 整列禁布形成一堵墙，
N1 必须借道第 1 层；N2 在第 1 层直行，注意 N1 在第 1 层的走线段与 N2
保持了至少一格间距）：

```bash
curl -s -X POST http://localhost:8000/route \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 8,
  "height": 8,
  "blocked": [
    {"x": 3, "y": 0, "layer": 0}, {"x": 3, "y": 1, "layer": 0},
    {"x": 3, "y": 2, "layer": 0}, {"x": 3, "y": 3, "layer": 0},
    {"x": 3, "y": 4, "layer": 0}, {"x": 3, "y": 5, "layer": 0},
    {"x": 3, "y": 6, "layer": 0}, {"x": 3, "y": 7, "layer": 0}
  ],
  "nets": [
    {"name": "N1", "pads": [{"x": 0, "y": 3, "layer": 0}, {"x": 7, "y": 3, "layer": 0}], "via_limit": 2},
    {"name": "N2", "pads": [{"x": 0, "y": 5, "layer": 1}, {"x": 7, "y": 5, "layer": 1}], "via_limit": 0}
  ]
}'
```

实际响应（`solve_time_seconds` 随机器略有浮动）：

```json
{
  "status": "optimal",
  "solve_time_seconds": 0.234,
  "total_vias": 2,
  "total_moves": 14,
  "nets": [
    {
      "name": "N1",
      "path": [
        {"x": 0, "y": 3, "layer": 0},
        {"x": 1, "y": 3, "layer": 0},
        {"x": 2, "y": 3, "layer": 0},
        {"x": 2, "y": 3, "layer": 1},
        {"x": 3, "y": 3, "layer": 1},
        {"x": 4, "y": 3, "layer": 1},
        {"x": 5, "y": 3, "layer": 1},
        {"x": 6, "y": 3, "layer": 1},
        {"x": 7, "y": 3, "layer": 1},
        {"x": 7, "y": 3, "layer": 0}
      ],
      "vias": [
        {"x": 2, "y": 3},
        {"x": 7, "y": 3}
      ],
      "via_count": 2,
      "move_count": 7
    },
    {
      "name": "N2",
      "path": [
        {"x": 0, "y": 5, "layer": 1},
        {"x": 1, "y": 5, "layer": 1},
        {"x": 2, "y": 5, "layer": 1},
        {"x": 3, "y": 5, "layer": 1},
        {"x": 4, "y": 5, "layer": 1},
        {"x": 5, "y": 5, "layer": 1},
        {"x": 6, "y": 5, "layer": 1},
        {"x": 7, "y": 5, "layer": 1}
      ],
      "vias": [],
      "via_count": 0,
      "move_count": 7
    }
  ]
}
```

路径中相邻两格 `layer` 相同表示一次同层移动，`layer` 不同（坐标不变）
表示一次过孔。

### 无解示例

两焊盘分处不同层但 `via_limit` 为 0，可证明无解：

```bash
curl -s -X POST http://localhost:8000/route \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 4,
  "height": 4,
  "nets": [
    {"name": "N1", "pads": [{"x": 0, "y": 0, "layer": 0}, {"x": 3, "y": 3, "layer": 1}], "via_limit": 0}
  ]
}'
```

```json
{
  "status": "infeasible",
  "solve_time_seconds": 0.005,
  "total_vias": null,
  "total_moves": null,
  "nets": null
}
```

### 输入校验（HTTP 422）

以下非法请求返回 `422 Unprocessable Entity`（FastAPI/Pydantic 校验）：

- 网格宽高超出 2～20，或网络条数不在 1～6；
- 焊盘越界（`x`/`y` 超出网格或 `layer` 非 0/1）；
- 焊盘落在禁布格上；
- 重复焊盘（任意两焊盘的 `(x, y, layer)` 完全相同，含同一网内）；
- 过孔上限为负数或非整数；
- 禁布格越界。

示例（焊盘落在禁布格上）：

```bash
curl -s -X POST http://localhost:8000/route \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 4, "height": 4,
  "blocked": [{"x": 1, "y": 1, "layer": 0}],
  "nets": [{"pads": [{"x": 1, "y": 1, "layer": 0}, {"x": 3, "y": 3, "layer": 0}], "via_limit": 1}]
}'
# HTTP 422
# {"detail":[{"type":"value_error","loc":["body"],
#   "msg":"Value error, net 0 pad (1, 1, layer 0) is on a blocked cell", ...}]}
```

## POST /inspect

走线审查接口。请求体与 `/route` 的板定义完全相同（`width`、`height`、
`blocked`、`nets`，并经过同样的板面校验），另外要求一个 **`paths`** 字段：
按 `nets` 的网序排列，每条网络给出一条**有序候选路径**（从首焊盘到末焊盘
的占格序列，编号规则与 `/route` 返回的 `path` 一致）。

接口**不会重新求解**，只静态检查给定路径，并报告**全部**走线违规：一条网
出错不会中断对其他规则和其他网络的检查。越界坐标和非法层号属于**走线违规**
（仍返回 `200`），而不是请求格式错误；只有请求本身畸形时才返回 `422`。

### 审查的规则

| 规则码 | 含义 |
| --- | --- |
| `ENDPOINT_MISMATCH` | 路径首格不是 `pads[0]`，或末格不是 `pads[1]`（空路径两个端点都报） |
| `CELL_OUT_OF_BOUNDS` | 步格坐标超出板面（`x`/`y`） |
| `ILLEGAL_LAYER` | 步格 `layer` 不是 `0`/`1` |
| `BLOCKED_CELL` | 步格落在禁布格上 |
| `DUPLICATE_CELL` | 同一网重复占据同一个 `(x, y, layer)` |
| `NON_ORTHOGONAL_STEP` | 同层相邻两步不是正交单位步（对角、跳跃、原地） |
| `LAYER_CHANGE_OFFSET` | 相邻两步换了层但坐标不同（非原位换层） |
| `VIA_LIMIT` | 过孔数（同坐标两层均被占用即计一个过孔）超过 `via_limit` |
| `CROSS_NET_COINCIDE` | 两条不同网络在同层占据同一格 |
| `CROSS_NET_ADJACENT` | 两条不同网络在同层占据正交相邻格 |

细则：

- **过孔计数**：某坐标的第 0、1 两层都被同一网占用即计 1 个过孔（无论两层
  在路径中是否相邻）；过孔按同坐标占两层计数。
- **跨网比较范围**：只比较**板内合法层**的占格；越界格、非法层格不参与跨网
  比较；**禁布格仍然参与**（禁布格上的异网重合/相邻照报）。
- **三网同格**：同一格被三条网占据时报 `0-1`、`0-2`、`1-2` **三对**冲突。
- **方向无关的相邻归并**：相邻判定与网号方位无关——无论低网号在高网号的
  左/上侧还是右/下侧，同一条无向边上的同一对网只报一条（`nets` 按网序、
  小编号在前）；同一条边上的不同网对分别报告，同一网在该边两端格上重复
  访问的**全部步号**都保留。
- 步号（`steps`）从 **0** 开始，即路径数组下标。

### 响应体

| 字段 | 说明 |
| --- | --- |
| `legal` | 仅当没有任何违规时为 `true` |
| `violations` | 违规列表，按「网序 → 步号 → 规则码」排序 |
| `violations[].rule` | 上表中的规则码 |
| `violations[].nets` | 涉及网络的下标（网序）：单网规则为 `[i]`，跨网规则为 `[i, j]`（`i < j`） |
| `violations[].steps` | 与 `nets` 平行：每个网参与该违规的步号列表（已排序；空路径的端点违规为 `[]`） |
| `violations[].cells` | 涉及格：跨网规则按网序给出，其余按规范序；格为 `{"x", "y", "layer"}`（可以是越界/非法层值） |
| `violations[].via_count` / `via_limit` | 仅 `VIA_LIMIT` 违规出现：实际过孔数 / 上限 |

### 实际请求与响应示例

合法候选路径（与 `/route` 可能返回的路径格式完全相同）：

```bash
curl -s -X POST http://localhost:8000/inspect \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 3,
  "height": 3,
  "nets": [
    {"name": "N1", "pads": [{"x": 0, "y": 0, "layer": 0}, {"x": 2, "y": 2, "layer": 0}], "via_limit": 2}
  ],
  "paths": [
    [
      {"x": 0, "y": 0, "layer": 0},
      {"x": 1, "y": 0, "layer": 0},
      {"x": 1, "y": 0, "layer": 1},
      {"x": 1, "y": 1, "layer": 1},
      {"x": 1, "y": 2, "layer": 1},
      {"x": 1, "y": 2, "layer": 0},
      {"x": 2, "y": 2, "layer": 0}
    ]
  ]
}'
```

```json
{"legal": true, "violations": []}
```

含多种违规的例子（4×3 板，第 0 层 `(2,1)` 禁布；N1 直行合法，N2 斜跳、
踩禁布格并与 N1 正交相邻）：

```bash
curl -s -X POST http://localhost:8000/inspect \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 4,
  "height": 3,
  "blocked": [{"x": 2, "y": 1, "layer": 0}],
  "nets": [
    {"name": "N1", "pads": [{"x": 0, "y": 0, "layer": 0}, {"x": 3, "y": 0, "layer": 0}], "via_limit": 0},
    {"name": "N2", "pads": [{"x": 0, "y": 2, "layer": 0}, {"x": 3, "y": 2, "layer": 0}], "via_limit": 0}
  ],
  "paths": [
    [
      {"x": 0, "y": 0, "layer": 0},
      {"x": 1, "y": 0, "layer": 0},
      {"x": 2, "y": 0, "layer": 0},
      {"x": 3, "y": 0, "layer": 0}
    ],
    [
      {"x": 0, "y": 2, "layer": 0},
      {"x": 1, "y": 1, "layer": 0},
      {"x": 2, "y": 1, "layer": 0},
      {"x": 3, "y": 2, "layer": 0}
    ]
  ]
}'
```

实际响应（已按网序、步号、规则码排序；跨网违规排在 N2 自身违规之前）：

```json
{
  "legal": false,
  "violations": [
    {
      "rule": "CROSS_NET_ADJACENT",
      "nets": [0, 1],
      "steps": [[1], [1]],
      "cells": [
        {"x": 1, "y": 0, "layer": 0},
        {"x": 1, "y": 1, "layer": 0}
      ],
      "via_count": null,
      "via_limit": null
    },
    {
      "rule": "CROSS_NET_ADJACENT",
      "nets": [0, 1],
      "steps": [[2], [2]],
      "cells": [
        {"x": 2, "y": 0, "layer": 0},
        {"x": 2, "y": 1, "layer": 0}
      ],
      "via_count": null,
      "via_limit": null
    },
    {
      "rule": "NON_ORTHOGONAL_STEP",
      "nets": [1],
      "steps": [[0, 1]],
      "cells": [
        {"x": 0, "y": 2, "layer": 0},
        {"x": 1, "y": 1, "layer": 0}
      ],
      "via_count": null,
      "via_limit": null
    },
    {
      "rule": "BLOCKED_CELL",
      "nets": [1],
      "steps": [[2]],
      "cells": [{"x": 2, "y": 1, "layer": 0}],
      "via_count": null,
      "via_limit": null
    },
    {
      "rule": "NON_ORTHOGONAL_STEP",
      "nets": [1],
      "steps": [[2, 3]],
      "cells": [
        {"x": 2, "y": 1, "layer": 0},
        {"x": 3, "y": 2, "layer": 0}
      ],
      "via_count": null,
      "via_limit": null
    }
  ]
}
```

### 反向网序示例

相邻冲突的判定与网号方位无关。下例中 N1（网 0）整段位于 N2（网 1）**右侧**，
两网在无向边 `(1,1,0)-(2,1,0)` 上异网相邻：即使低网号在高网号的右侧，
`CROSS_NET_ADJACENT` 照样只报一条，`nets` 仍按网序 `[0, 1]` 给出。

```bash
curl -s -X POST http://localhost:8000/inspect \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 4,
  "height": 3,
  "nets": [
    {"name": "N1", "pads": [{"x": 2, "y": 1, "layer": 0}, {"x": 3, "y": 1, "layer": 0}], "via_limit": 0},
    {"name": "N2", "pads": [{"x": 0, "y": 1, "layer": 0}, {"x": 1, "y": 1, "layer": 0}], "via_limit": 0}
  ],
  "paths": [
    [
      {"x": 2, "y": 1, "layer": 0},
      {"x": 3, "y": 1, "layer": 0}
    ],
    [
      {"x": 0, "y": 1, "layer": 0},
      {"x": 1, "y": 1, "layer": 0}
    ]
  ]
}'
```

实际响应：

```json
{
  "legal": false,
  "violations": [
    {
      "rule": "CROSS_NET_ADJACENT",
      "nets": [0, 1],
      "steps": [[0], [1]],
      "cells": [
        {"x": 1, "y": 1, "layer": 0},
        {"x": 2, "y": 1, "layer": 0}
      ],
      "via_count": null,
      "via_limit": null
    }
  ]
}
```

### 输入校验（HTTP 422）

除继承 `/route` 的全部板面校验（尺寸、网络数、焊盘越界/落禁布格/重复等）
外，`/inspect` 另有以下 422 情形：

- 缺少 `paths` 字段；
- `paths` 条数与 `nets` 不一致；
- 路径坐标不是整数（`0.5`、`1.0`、`"1"`、`true`、`null` 均拒绝）；
- 单条路径步数超过两层板格总数 `2 × width × height`
  （空路径合法，报端点违规；长度恰好等于上限的路径可以提交审查）。

示例（坐标使用了小数）：

```bash
curl -s -X POST http://localhost:8000/inspect \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 3, "height": 3,
  "nets": [{"pads": [{"x": 0, "y": 0, "layer": 0}, {"x": 2, "y": 2, "layer": 0}], "via_limit": 0}],
  "paths": [[{"x": 0, "y": 0, "layer": 0.5}, {"x": 2, "y": 2, "layer": 0}]]
}'
# HTTP 422
# {"detail":[{"type":"int_type","loc":["body","paths",0,0,"layer"],
#   "msg":"Input should be a valid integer","input":0.5}]}
```

## POST /diagnose-open

断路（开路）诊断接口。请求体在 `/inspect` 的基础上（同样的板定义
`width`、`height`、`blocked`、`nets`，以及按网序给出的 `paths` 有序候选
路径）再增加一个 **`measurements`** 字段：每条网络至少提交一条**实测记录**。

每条记录给出所测**网号**（`nets` 下标）、两个**含层探针格** `a` / `b`
（完整的 `{x, y, layer}`），以及万用表实测结果 `result`：

- `"connected"`（连通）：两探针之间导通；
- `"open"`（断开）：两探针之间不导通。

接口先做与 `/route`、`/inspect` 完全相同的板面校验，再调用与
`POST /inspect` 完全一致的 `inspect_board` 审查；板面或路径有问题直接
`422`（路径违规会附上 `/inspect` 的违规项，见下文）。随后把每个探针按
**完整三元组 `(x, y, layer)`** 定位到该网候选路径上的步号，再做断路边
裁决。

### 故障模型与裁决规则

假设**每条网至多有一条路径边断路**，其余边全部导通。路径的第 `step` 条边
连接 `paths[k][step]` 与 `paths[k][step+1]`（同层移动边或原位换层的过孔
边）。设探针位于步号 `p < q`，两探针之间的边为第 `p … q-1` 条：

- **连通记录**排除两探针之间的**每一条边**（这些边都不可能断）；
- **断开记录**要求那条唯一的断边**落在两探针之间**（探针间任何导通路径
  都必经过它）。

同一网的多条记录**交叉合并裁决**：候选断边 =（所有断开记录区间的交集）
减去（所有连通记录排除边的并集）。

- 某网存在至少一条断开记录时才**需要断路**（`break_required: true`）；
  只有连通记录的网不需要断路。
- 所有记录全为连通且互不矛盾时，**无断路即可解释全部记录**
  （`no_break_possible: true`）。
- 断开记录区间没有公共边，或公共边全部被连通记录排除时，记录**互相
  冲突**：`consistent: false`，冲突网的候选边列表为空。
- **同坐标两层探针不得混作一格**：`(x,y,0)` 与 `(x,y,1)` 是两个不同探针，
  它们只通过原位换层的**过孔边**相连；该过孔边与普通走线段一样参与区间
  裁决，不会被当成同一个格。
- 测量是无向的：`a`、`b` 顺序可与路径方向相反，按步号自动归正。

各网独立裁决；`consistent` 为 `false` 时只影响冲突的网，其余网仍返回各自
的候选边。候选边按路径**步号升序**给出，两端格按路径顺序排列。

### 请求体

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `width` / `height` / `blocked` / `nets` | — | 与 `/route`、`/inspect` 的板定义完全相同 |
| `paths` | array | 与 `/inspect` 相同：每网一条有序候选路径 |
| `measurements` | array | 实测记录列表，至少 1 条，且**每条网至少 1 条** |
| `measurements[].net` | int | 所测网络在 `nets` 中的下标（网号） |
| `measurements[].a` / `.b` | object | 两个含层探针格 `{"x", "y", "layer"}`，严格整数 |
| `measurements[].result` | string | `"connected"`（连通）或 `"open"`（断开） |

### 响应体

| 字段 | 说明 |
| --- | --- |
| `consistent` | 全部记录在「每网至多一条断边」假设下是否自洽；`false` 时冲突网无候选边 |
| `no_break_possible` | 是否「全板无断路」即可解释全部记录（仅当所有记录均连通） |
| `nets[]` | 每条网一项，按网序排列 |
| `nets[].net` / `nets[].name` | 网下标 / 网名称（未命名时为 `N1`、`N2`…） |
| `nets[].break_required` | 该网是否有断开记录、因而必须存在一条断边 |
| `nets[].candidate_edges[]` | 能同时解释该网全部记录的候选断边；不需要断路或冲突时为空 |
| `candidate_edges[].step` | 断边在路径中的步号（连接 `path[step]` 与 `path[step+1]`） |
| `candidate_edges[].cells` | 断边两端格，按路径顺序给出的两个 `{"x","y","layer"}` |

### 实际请求与响应示例

6×3 板上 N1、N2 均在第 0 层直行。N1 的实测：`0→2` 连通、`3→4` 连通、
`4→5` 连通，但首尾 `0→5` 断开——唯一能同时解释这些记录的断边是第 `2`
条边 `(2,0,0)–(3,0,0)`；N2 全程连通，无需断路（注意
`no_break_possible` 为 `false`，因为 N1 有断开记录）：

```bash
curl -s -X POST http://localhost:8000/diagnose-open \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 6,
  "height": 3,
  "nets": [
    {"name": "N1", "pads": [{"x": 0, "y": 0, "layer": 0}, {"x": 5, "y": 0, "layer": 0}], "via_limit": 0},
    {"name": "N2", "pads": [{"x": 0, "y": 2, "layer": 0}, {"x": 5, "y": 2, "layer": 0}], "via_limit": 0}
  ],
  "paths": [
    [{"x": 0, "y": 0, "layer": 0}, {"x": 1, "y": 0, "layer": 0}, {"x": 2, "y": 0, "layer": 0}, {"x": 3, "y": 0, "layer": 0}, {"x": 4, "y": 0, "layer": 0}, {"x": 5, "y": 0, "layer": 0}],
    [{"x": 0, "y": 2, "layer": 0}, {"x": 1, "y": 2, "layer": 0}, {"x": 2, "y": 2, "layer": 0}, {"x": 3, "y": 2, "layer": 0}, {"x": 4, "y": 2, "layer": 0}, {"x": 5, "y": 2, "layer": 0}]
  ],
  "measurements": [
    {"net": 0, "a": {"x": 0, "y": 0, "layer": 0}, "b": {"x": 2, "y": 0, "layer": 0}, "result": "connected"},
    {"net": 0, "a": {"x": 3, "y": 0, "layer": 0}, "b": {"x": 4, "y": 0, "layer": 0}, "result": "connected"},
    {"net": 0, "a": {"x": 4, "y": 0, "layer": 0}, "b": {"x": 5, "y": 0, "layer": 0}, "result": "connected"},
    {"net": 0, "a": {"x": 0, "y": 0, "layer": 0}, "b": {"x": 5, "y": 0, "layer": 0}, "result": "open"},
    {"net": 1, "a": {"x": 0, "y": 2, "layer": 0}, "b": {"x": 5, "y": 2, "layer": 0}, "result": "connected"}
  ]
}'
```

实际响应：

```json
{
  "consistent": true,
  "no_break_possible": false,
  "nets": [
    {
      "net": 0,
      "name": "N1",
      "break_required": true,
      "candidate_edges": [
        {
          "step": 2,
          "cells": [
            {"x": 2, "y": 0, "layer": 0},
            {"x": 3, "y": 0, "layer": 0}
          ]
        }
      ]
    },
    {
      "net": 1,
      "name": "N2",
      "break_required": false,
      "candidate_edges": []
    }
  ]
}
```

### 换层（过孔边）诊断示例

路径在 `(1,0)` 原位换层。探针打在**同一坐标的两层**上测出断开，而第 0 层
`0→1` 连通：唯一候选是第 `1` 条边——过孔边 `(1,0,0)–(1,0,1)`，而不是把
两层混作一格：

```bash
curl -s -X POST http://localhost:8000/diagnose-open \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 3,
  "height": 3,
  "nets": [
    {"name": "N1", "pads": [{"x": 0, "y": 0, "layer": 0}, {"x": 2, "y": 0, "layer": 0}], "via_limit": 2}
  ],
  "paths": [[
    {"x": 0, "y": 0, "layer": 0},
    {"x": 1, "y": 0, "layer": 0},
    {"x": 1, "y": 0, "layer": 1},
    {"x": 2, "y": 0, "layer": 1},
    {"x": 2, "y": 0, "layer": 0}
  ]],
  "measurements": [
    {"net": 0, "a": {"x": 1, "y": 0, "layer": 0}, "b": {"x": 1, "y": 0, "layer": 1}, "result": "open"},
    {"net": 0, "a": {"x": 0, "y": 0, "layer": 0}, "b": {"x": 1, "y": 0, "layer": 0}, "result": "connected"}
  ]
}'
```

实际响应：

```json
{
  "consistent": true,
  "no_break_possible": false,
  "nets": [
    {
      "net": 0,
      "name": "N1",
      "break_required": true,
      "candidate_edges": [
        {
          "step": 1,
          "cells": [
            {"x": 1, "y": 0, "layer": 0},
            {"x": 1, "y": 0, "layer": 1}
          ]
        }
      ]
    }
  ]
}
```

### 冲突记录示例

同一条网既要断边在第 0 条边（`0→1` 断开），又要断边在第 3 条边
（`3→4` 断开），在「每网至多一条断边」假设下无法同时成立：

```bash
curl -s -X POST http://localhost:8000/diagnose-open \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 5,
  "height": 3,
  "nets": [
    {"name": "N1", "pads": [{"x": 0, "y": 0, "layer": 0}, {"x": 4, "y": 0, "layer": 0}], "via_limit": 0}
  ],
  "paths": [[{"x": 0, "y": 0, "layer": 0}, {"x": 1, "y": 0, "layer": 0}, {"x": 2, "y": 0, "layer": 0}, {"x": 3, "y": 0, "layer": 0}, {"x": 4, "y": 0, "layer": 0}]],
  "measurements": [
    {"net": 0, "a": {"x": 0, "y": 0, "layer": 0}, "b": {"x": 1, "y": 0, "layer": 0}, "result": "open"},
    {"net": 0, "a": {"x": 3, "y": 0, "layer": 0}, "b": {"x": 4, "y": 0, "layer": 0}, "result": "open"}
  ]
}'
```

```json
{
  "consistent": false,
  "no_break_possible": false,
  "nets": [
    {
      "net": 0,
      "name": "N1",
      "break_required": true,
      "candidate_edges": []
    }
  ]
}
```

### 输入校验（HTTP 422）

除继承 `/route`、`/inspect` 的全部板面与路径校验外，`/diagnose-open`
另有以下 422 情形（**路径违规优先于探针检查**）：

- **路径违规**：任一候选路径不满足 `/inspect` 的走线规则（端点不符、越界、
  非法层、踩禁布格、重复格、非正交步、非原位换层、过孔超限、跨网重合/
  相邻等）。返回 422，`detail` 为一个对象，`detail.violations` 与
  `POST /inspect` 对同一板面+路径返回的 `violations` **完全一致**；
- **非法网号**：`measurements[].net` 超出 `0 … nets.length-1`；
- **缺实测记录**：缺少 `measurements`、为空，或某条网一条记录都没有；
- **探针不在对应路径上**：探针格（按完整 `(x, y, layer)` 判定）不是所指
  网候选路径上的格（同坐标另一层不算）；
- **记录值非法**：`result` 不是 `"connected"` / `"open"`；
- 探针坐标不是严格整数（`1.0`、`"1"`、`true`、`null` 均拒绝），探针缺字段。

路径违规示例（路径第一步从 `x=0` 跳到 `x=2`，并附上 `/inspect` 违规项）：

```bash
curl -s -X POST http://localhost:8000/diagnose-open \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 5,
  "height": 3,
  "nets": [
    {"name": "N1", "pads": [{"x": 0, "y": 0, "layer": 0}, {"x": 4, "y": 0, "layer": 0}], "via_limit": 0}
  ],
  "paths": [[{"x": 0, "y": 0, "layer": 0}, {"x": 2, "y": 0, "layer": 0}, {"x": 3, "y": 0, "layer": 0}, {"x": 4, "y": 0, "layer": 0}]],
  "measurements": [
    {"net": 0, "a": {"x": 0, "y": 0, "layer": 0}, "b": {"x": 4, "y": 0, "layer": 0}, "result": "connected"}
  ]
}'
# HTTP 422
```

```json
{
  "detail": {
    "message": "candidate paths have routing violations; see `violations` (same content as POST /inspect)",
    "violations": [
      {
        "rule": "NON_ORTHOGONAL_STEP",
        "nets": [0],
        "steps": [[0, 1]],
        "cells": [
          {"x": 0, "y": 0, "layer": 0},
          {"x": 2, "y": 0, "layer": 0}
        ],
        "via_count": null,
        "via_limit": null
      }
    ]
  }
}
```

探针不在对应路径上示例：

```bash
curl -s -X POST http://localhost:8000/diagnose-open \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 5,
  "height": 3,
  "nets": [
    {"name": "N1", "pads": [{"x": 0, "y": 0, "layer": 0}, {"x": 4, "y": 0, "layer": 0}], "via_limit": 0}
  ],
  "paths": [[{"x": 0, "y": 0, "layer": 0}, {"x": 1, "y": 0, "layer": 0}, {"x": 2, "y": 0, "layer": 0}, {"x": 3, "y": 0, "layer": 0}, {"x": 4, "y": 0, "layer": 0}]],
  "measurements": [
    {"net": 0, "a": {"x": 1, "y": 2, "layer": 0}, "b": {"x": 4, "y": 0, "layer": 0}, "result": "open"}
  ]
}'
# HTTP 422
# {"detail":"probe cell (1, 2, layer 0) is not on the path of net 0"}
```

非法网号示例：

```bash
# HTTP 422
# {"detail":[{"type":"value_error","loc":["body"],
#   "msg":"Value error, measurement refers to net 3, but only 1 nets are defined (valid indices 0..0)", ...}]}
```

某条网没有任何实测记录示例：

```bash
# HTTP 422
# {"detail":[{"type":"value_error","loc":["body"],
#   "msg":"Value error, every net needs at least one measurement; missing measurement(s) for net(s) [1]", ...}]}
```

## 实现要点

- **模型**（`app/solver.py`）：每条网络建模为从 `pads[0]` 到 `pads[1]` 的
  单位流。节点为两层上的自由格；弧为同层正交移动弧与过孔弧。除源/汇外
  每个节点入度=出度≤1，保证路径不重复占格；某网在同坐标两层均占格时
  过孔变量强制为 1（过孔占两层）。异网之间对同层每格及其正交邻格加
  互斥约束。
- **目标**：`min 4795 * 总过孔数 + 总移动步数`。权重大于最大可能步数
  （6 网 × 799 步 = 4794），因此严格等价于字典序（先过孔后步数）。
- **证明速度**：每网移动步数变量定义域下界直接取两焊盘曼哈顿距离、
  过孔变量下界按焊盘是否异层取 0/1，使根节点下界立即有效；另用一个
  快速顺序 Dijkstra 启发式把可行布线作为 hint 注入加速搜索。
- **限时语义**：CP-SAT `max_time_in_seconds = 10`。返回 `OPTIMAL` /
  `INFEASIBLE` 才分别报告 `optimal` / `infeasible`；限时到时有解报
  `feasible`、无解报 `unknown`。若求解器超时但启发式已找到经独立
  校验的完整合法布线，也按 `feasible` 返回该方案。
- **解校验**：`tests/test_router.py` 内含独立校验器，对返回的每条路径
  检查端点、占格不重复、同层正交移动、过孔占两层、禁布格、过孔上限、
  异网隔离及目标值一致性。
- **走线审查**（`app/inspector.py`）：`POST /inspect` 不求解，只逐条规则
  审计候选路径。单网规则（端点、越界、非法层、禁布、重复、非正交跳步、
  非原位换层、过孔上限）逐网检查；跨网规则只对板内合法层占格建占格表，
  同格报 `CROSS_NET_COINCIDE`（每对网一条，三网同格报三对），正交邻边
  报 `CROSS_NET_ADJACENT`（每条无向边归并一次、方向无关：低网号无论在
  边的哪一端都照报，`nets` 按网序；同边多网对分别报告，重复访问的全部
  步号保留）。越界与非法层以 `200` 返回违规；请求畸形
  （缺字段、路径数不符、非整数坐标、单路径超过 `2wh` 格）由 Pydantic
  返回 `422`。`tests/test_inspect.py` 覆盖全部规则、排序语义与 422。
- **断路诊断**（`app/diagnose.py`）：`POST /diagnose-open` 先跑
  `inspect_board`，路径有任何违规即以 `422` 返回（`detail.violations`
  与 `/inspect` 完全一致）；通过后把探针按完整三元组 `(x, y, layer)`
  定位到对应网路径的步号——同坐标两层是不同探针，经原位换层过孔边相连，
  不会混作一格。在「每网至多一条断边」假设下，连通记录排除探针区间内的
  全部边，断开记录要求唯一断边落在其区间内；候选 = 断开区间交集 −
  连通排除并集，按步号升序输出两端格。仅存在连通记录的网
  `break_required=false`；全部记录连通时 `no_break_possible=true`；
  区间交集为空或被连通记录全部排除时 `consistent=false` 且候选为空。
  非法网号、缺记录、探针不在对应路径、`result` 非法等返回 `422`
  （路径违规优先于探针检查）。`tests/test_diagnose.py` 覆盖定位、区间
  合并、过孔边、冲突与全部 422 分支。

## 项目结构

```
app/
  main.py       # FastAPI 入口，POST /route、POST /inspect、
                # POST /diagnose-open、GET /health
  schemas.py    # Pydantic 请求/响应模型与 422 校验
  solver.py     # CP-SAT 联合建模、启发式 hint、结果提取
  inspector.py  # /inspect 走线规则静态审查（不求解）
  diagnose.py   # /diagnose-open 实测通断记录的单断路边定位
tests/
  test_router.py
  test_inspect.py
  test_diagnose.py
Dockerfile
docker-compose.yml
requirements.txt
```

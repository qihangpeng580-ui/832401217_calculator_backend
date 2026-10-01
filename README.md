# 前后端分离计算器 · 后端（学号 832401217）

软件工程课程「前后端分离计算器系统」作业的**后端部分**。
负责表达式解析、计算、异常处理，以及计算历史在数据库中的持久化。

> 前端仓库：[832401217_calculator_frontend](https://github.com/qihangpeng580-ui/832401217_calculator_frontend)

---

## 一、项目介绍

这是一个 HTTP 服务，为前端提供计算与历史记录接口。它承担作业要求中**全部的计算职责**：

| 本项目负责 | 不属于本项目 |
|---|---|
| 表达式词法分析与语法分析（不用 `eval`） | 界面呈现 |
| 四则运算、运算优先级、括号、一元正负号 | 按钮交互 |
| 小数精确计算（用 `Decimal`，不用浮点） | 前端输入校验（前端也做了一层，但后端必须独立再校验一次） |
| 非法表达式处理、除零处理 | — |
| 计算历史写入数据库 | — |
| 历史查询与删除 | — |

**核心设计原则**：接口是可以被直接调用的（比如用 `curl`），
所以**不能信任前端的校验**。前端拦掉的非法输入，后端必须自己再拦一遍。

## 二、技术栈

| 项目 | 选择 | 说明 |
|---|---|---|
| 语言 | Python 3.10+（开发于 3.12） | 用到 `X \| None` 类型标注，故需 3.10+ |
| HTTP 服务 | `http.server`（标准库） | 自写路由，不引入框架 |
| 数据库 | SQLite（`sqlite3`，标准库） | 单文件数据库 |
| 数值类型 | `decimal.Decimal`（标准库） | 保证 0.1+0.2 = 0.3 |
| 测试 | `unittest`（标准库） | 157 项单元测试 + 39 项黑盒验收 |
| **第三方依赖** | **无** | `requirements.txt` 为空，不需要 `pip install` |

**为什么全用标准库**：助教拿到代码后，任何装了 Python 的机器都能直接跑起来，
不需要配环境、不需要装数据库服务。这是可移植性上的取舍：
省掉了框架的便利，换来的是"打开就能跑"。

## 三、目录结构

```
832401217_calculator_backend/
├── run.py                          服务入口（命令行参数、启动 HTTP 服务）
├── init_db.py                      单独建库脚本（不启动服务时用）
├── requirements.txt                空的（无第三方依赖）
├── README.md                       本文件
├── codestyle.md                    代码规范说明
├── src/
│   ├── main.py                     模块说明与装配示例
│   ├── calculator/                 表达式处理（本项目最核心的部分）
│   │   ├── tokenizer.py            词法分析：字符串 → 记号序列
│   │   ├── parser.py               语法分析：记号序列 → 语法树（递归下降）
│   │   └── evaluator.py            求值：语法树 → 结果（后序遍历）
│   ├── service/
│   │   ├── calculator_service.py   编排"解析 → 求值 → 格式化"
│   │   └── history_service.py      编排"计算 + 写库"、历史查询与删除
│   ├── model/
│   │   └── sqlite_store.py         SQLite 读写
│   ├── controller/
│   │   └── http_controller.py      HTTP 接口层（路由、请求解析、响应输出、CORS）
│   └── common/
│       └── errors.py               统一错误定义（错误码 ↔ HTTP 状态码）
├── tests/
│   ├── test_tokenizer.py           26 项
│   ├── test_parser.py              38 项
│   ├── test_calculator.py          66 项（含安全测试）
│   └── test_store.py               27 项
├── tools/
│   ├── blackbox.py                 黑盒验收：用真实 HTTP 请求走完整流程
│   ├── push_via_api.py             通过 GitHub API 推送（本机 git push 走不通时的备用方案）
│   ├── verify_full.py              开发用：临时填上解析器以验证整条链路
│   └── verify_skeleton.py          开发用：单独验证解析器骨架
└── data/                           运行时生成 calculator.db（已 gitignore）
```

各层的调用关系（单向，不允许反向依赖）：

```
http_controller  →  history_service  →  calculator_service  →  parser / evaluator
                          ↓
                     sqlite_store
```

## 四、运行方法

```powershell
# 进入后端目录
cd "832401217_calculator_backend"

# 启动服务（默认 127.0.0.1:8000，首次运行自动建库）
py -3.12 run.py

# 换端口
py -3.12 run.py --port 8080

# 允许外部访问（配合内网穿透或部署到服务器时用）
py -3.12 run.py --host 0.0.0.0
```

启动后浏览器打开 <http://127.0.0.1:8000/api/health> 应看到：

```json
{"success": true, "data": {"status": "ok", "service": "calculator-backend", ...}}
```

**运行环境要求**

| 项 | 要求 |
|---|---|
| Python | **3.10 或更高**（用到 `X \| None` 标注） |
| 第三方包 | **无** |
| 数据库服务 | **不需要**（SQLite 是文件数据库） |
| 操作系统 | 不限（Windows / Linux / macOS 均可） |

## 五、配置说明

### 5.1 命令行参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--host` | `127.0.0.1` | 监听地址。改成 `0.0.0.0` 才能被外部访问 |
| `--port` | `8000` | 监听端口 |
| `--db` | `data/calculator.db` | SQLite 数据库文件路径 |

### 5.2 代码内可调常量

| 位置 | 常量 | 默认 | 作用 |
|---|---|---|---|
| `tokenizer.py` | `MAX_EXPRESSION_LENGTH` | 200 | 表达式长度上限 |
| `evaluator.py` | `PRECISION` | 28 | Decimal 运算精度 |
| `evaluator.py` | `MAX_RESULT_SCALE` | 12 | 结果最多保留的小数位 |
| `http_controller.py` | `DEFAULT_HISTORY_LIMIT` | 50 | 历史默认返回条数 |
| `http_controller.py` | `MAX_HISTORY_LIMIT` | 200 | 历史单次返回上限 |
| `http_controller.py` | `MAX_BODY_BYTES` | 65536 | 请求体大小上限 |

### 5.3 跨域（CORS）

当前配置为 `Access-Control-Allow-Origin: *`（允许任何来源）。
这样前端无论部署在 GitHub Pages、本机 `file://` 还是局域网，都能调用。

**这是作业场景的取舍**：地址事先不确定，所以开放。
生产环境应改为白名单，只允许前端所在域名。

## 六、数据库初始化

**不需要手动初始化** —— 服务启动时会自动建表（`CREATE TABLE IF NOT EXISTS`）。

如果想单独建库（例如部署前先准备好文件）：

```powershell
py -3.12 init_db.py
```

### 表结构

```sql
CREATE TABLE IF NOT EXISTS calculation_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    expression  TEXT    NOT NULL,   -- 用户输入的表达式，原样保存
    result      TEXT    NOT NULL,   -- 结果，存字符串以保证十进制精度
    created_at  TEXT    NOT NULL    -- ISO-8601 时间
);

CREATE INDEX IF NOT EXISTS idx_history_created_at
    ON calculation_history (created_at DESC);
```

**两个设计决定：**

| 决定 | 理由 |
|---|---|
| `result` 存 `TEXT` 而不是 `REAL` | `REAL` 是二进制浮点，`0.3` 存进去再读出来可能变成 `0.29999999999999998`。存字符串可以保持十进制精确 |
| 给 `created_at` 建索引 | "按时间倒序取最近若干条"是最高频的查询（前端一打开就要拉） |

## 七、前后端连接方式

前端通过 HTTP 调用本服务。接口一览：

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/calculate` | 计算并保存历史 |
| `GET` | `/api/history` | 查询历史（支持 `keyword`、`limit`） |
| `DELETE` | `/api/history/{id}` | 删除指定记录 |
| `DELETE` | `/api/history` | 清空全部历史（扩展） |
| `GET` | `/api/stats` | 统计信息（扩展） |
| `GET` | `/api/health` | 健康检查 |

### 请求 / 响应示例

**计算**

```http
POST /api/calculate
Content-Type: application/json

{"expression": "1+2*3"}
```

```json
{
  "success": true,
  "data": {"expression": "1+2*3", "result": "7", "resultNumber": 7}
}
```

**分页与统计**

```json
GET /api/history?limit=5{"success": true, "data": {"items": [{"id": 2, "expression": "7*6", "result": "42", "createdAt": "2026-09-29T15:20:11"}], "total": 2, "limit": 5, "keyword": ""}}
```

**统一错误格式**

```json
{
  "success": false,
  "errorCode": "DIVISION_BY_ZERO",
  "message": "除数不能为 0"
}
```

| errorCode | HTTP | 触发场景 |
|---|---|---|
| `INVALID_EXPRESSION` | 400 | 语法错误、非法字符、括号不匹配、多个小数点 |
| `DIVISION_BY_ZERO` | 422 | 除数为 0（含除数是算出来为 0 的表达式） |
| `EXPRESSION_TOO_LONG` | 413 | 超过 `MAX_EXPRESSION_LENGTH` |
| `RECORD_NOT_FOUND` | 404 | 删除的记录不存在 |
| `BAD_REQUEST` | 400 | 请求体不是合法 JSON、缺少 `expression` 字段 |
| `INTERNAL_ERROR` | 500 | 服务端非预期错误 |

> 这张表的错误码**与前端 `ui.js` 里的 `SERVER_ERROR_TEXT` 一一对应**，
> 前端据此把错误码翻译成中文提示。

### 一个便于验证的细节

所有响应都带一个自定义头：

```
X-Calculated-By: backend
```

打开浏览器 `F12` → Network → 点开任意一次 `/api/calculate` 请求，
在 Response Headers 里能看到它。这是给"结果到底是谁算的"这个问题准备的证据。

## 八、测试

### 8.1 单元测试（157 项，约 1 秒）

```powershell
py -3.12 -m unittest discover -s tests -v
```

| 文件 | 项数 | 覆盖内容 |
|---|---|---|
| `test_tokenizer.py` | 26 | 数字/运算符/括号切分、空白处理、非法字符、长度上限、代码注入拒绝 |
| `test_parser.py` | 38 | 优先级、左结合、括号、一元正负号、各种非法表达式 |
| `test_calculator.py` | 66 | 作业示例表达式、小数精度、除零、安全、结果格式化 |
| `test_store.py` | 27 | 建表、插入、查询、搜索、删除单条、清空、统计 |

### 8.2 黑盒验收（39 项，约 10 秒）

```powershell
py -3.12 tools/blackbox.py
```

这个脚本会**起一个真实的服务**，用**真实 HTTP 请求**走完作业要求的四件事：

1. 基本运算（`12+8 = 20` 等）
2. 复合表达式（优先级、括号、一元正负号、小数、非法表达式、除零）
3. 历史持久化 —— 包括**重启服务后历史依然存在**
4. 删除指定记录 —— 并验证"只删了指定的那条，其余不受影响"

**为什么除了单元测试还要有它**：单元测试是直接调函数，绕过了 HTTP 这一层。
而作业交付的是一个**能被网络访问的服务**，所以必须有一条测试是真的走网络的。
（前端项目里就吃过这个教训：函数测试全绿，但用 `file://` 打开时整个页面没有交互。）

## 九、部署

【部署后补充】需要填写：

- 后端服务公网地址
- 健康检查地址（`/api/health`）
- 启动命令与端口
- 若使用内网穿透或云服务器，说明具体方式

**当前可用的本地地址**：<http://127.0.0.1:8000/api/health>

## 十、已知取舍与限制

| 项 | 现状 | 说明 |
|---|---|---|
| CORS | 允许任何来源 | 作业场景下地址不确定；生产应改白名单 |
| 认证 | 无 | 作业未要求；任何人都能调接口 |
| 并发 | 多线程 + 每次操作新开数据库连接 | 足够应对作业规模；高并发应改用连接池 |
| 历史条数 | 无上限 | 长期运行会一直增长；生产应加清理策略 |
| 科学计算 | 未实现 | 属于扩展功能，可选 |

# 代码规范说明（后端）

> **规范出处**（作业要求：规范须源自主流官方标准或大厂/社区推荐标准，并在文档开头写明来源）：
>
> - **PEP 8 — Style Guide for Python Code** — https://peps.python.org/pep-0008/
> - **PEP 257 — Docstring Conventions** — https://peps.python.org/pep-0257/
> - **Google Python Style Guide** — https://google.github.io/styleguide/pyguide.html
>   （类型标注与 docstring 的组织方式参考此份）
>
> 本文件说明本仓库实际采用了其中哪些条款、哪些做了取舍，以及为什么。
> 只写"确实遵守的"，不抄一份用不上的清单。

---

## 1. 文件与编码

| 项 | 规定 | 依据 |
|---|---|---|
| 编码 | 一律 UTF-8（无 BOM） | PEP 8 未强制，但 Python 3 默认源码编码即 UTF-8 |
| 缩进 | **4 个空格**，禁用 Tab | PEP 8 强制 |
| 行宽 | 建议 100 字符以内 | PEP 8 规定 79，本仓库放宽到 100（理由见 §7） |
| 文件命名 | 小写 + 下划线，如 `http_controller.py` | PEP 8 |
| 包/模块结构 | `src/<层>/<模块>.py` | 本项目自定，便于分层 |

## 2. 命名（PEP 8 第 3 节）

| 类型 | 规定 | 本仓库示例 |
|---|---|---|
| 模块名 | `lower_snake_case` | `sqlite_store`、`calculator_service` |
| 类名 | `CapWords` | `CalculatorService`、`SqliteStore`、`Token` |
| 函数/方法 | `lower_snake_case` | `calculate_and_save`、`list_recent` |
| 常量（模块级） | `UPPER_SNAKE_CASE` | `MAX_EXPRESSION_LENGTH`、`DEFAULT_HISTORY_LIMIT` |
| 私有成员 | 前导单下划线 | `self._store`、`_parse_expression` |
| 枚举成员 | `UPPER_SNAKE_CASE` | `TokenType.NUMBER` |
| 布尔变量 | 用 `is` / `has` / `can` 开头 | `is_finite`、`has_alpha` |

**接口字段命名与数据库列名的分工**（本仓库特别约定）：

| 位置 | 风格 | 示例 |
|---|---|---|
| 数据库列名 | `snake_case`（SQL 习惯） | `created_at` |
| 对前端输出的 JSON 字段 | `camelCase`（JS 习惯） | `createdAt` |

转换发生在 `sqlite_store.py` 的 `_to_dict()` 里，**只此一处**。

## 3. 类型标注（参考 Google Python Style Guide）

本仓库**所有函数都写类型标注**，包括返回值：

```python
def calculate(self, expression: str) -> CalculationOutcome:
    ...
```

可空的值用 `X | None`（PEP 604 写法，需要 Python 3.10+）：

```python
def get(self, record_id: int) -> dict | None:
    ...
```

**为什么坚持写标注**：
1. 编辑器能提前发现类型错误，不用等到运行；
2. 类型标注本身就是**文档** —— 看到 `-> dict | None` 就知道"可能返回空"，
   调用方会记得判空，这类 bug 能提前避免；
3. 本项目用 `from __future__ import annotations`，让标注在旧版本 Python 上也不报错。

## 4. 文档字符串（PEP 257 + Google 风格）

**每个模块、每个公开函数都写 docstring。** 规则：

1. 第一行是**一句话概括**，以句号结尾；
2. 空一行后写详细说明（如果一句话不够）；
3. 参数、返回值、异常用 `Args:` / `Returns:` / `Raises:` 分段（Google 风格）。

```python
def insert(self, expression: str, result: str) -> dict:
    """插入一条计算记录。

    Args:
        expression: 用户输入的表达式（原样保存）
        result: 规范化后的结果字符串

    Returns:
        新插入的整条记录（含自增 id 与创建时间）
    """
```

**本仓库的特别约定：docstring 里要写"为什么"，不只是"是什么"。**

例如 `tokenizer.py` 里的：

```python
def _parse_number(raw: str, pos: int) -> Decimal:
    """把一段数字文本转成 Decimal。

    为什么用 Decimal 而不是 float：
        float 是二进制浮点数，0.1 + 0.2 会得到 0.30000000000000004。
        计算器必须给出 0.3。Decimal 是十进制浮点，能精确表示 0.1 和 0.2。
    """
```

这类说明占了不少篇幅，但它是**这份作业要考察的内容** —— 作业帖明确要求
"解释重要实现逻辑"，而不是只交一堆能跑的代码。

## 5. 分层与依赖方向

```
controller  →  service  →  calculator（纯计算，无副作用）
                    ↓
                 model（数据库）
```

**三条硬规则：**

1. **依赖只能单向**：`calculator` 层不允许 import `service` 或 `model`。
   纯计算层必须能脱离数据库和 HTTP 独立测试（`tests/test_calculator.py` 就不建库）。
2. **错误只在一处定义**：所有业务异常集中在 `common/errors.py`。
   业务代码不写 `return 400`，而是抛对应异常，由最外层翻译成状态码。
3. **数据库细节不外泄**：SQL 只出现在 `sqlite_store.py` 里。
   service 层看到的已经是 Python 字典，不知道底层是 SQLite。

## 6. 安全约定（本项目硬性要求）

| 规定 | 说明 |
|---|---|
| **禁止 `eval` / `exec` / `compile`** | 作业明确禁止把用户输入当代码执行。`tests/test_calculator.py` 里有一条**静态检查测试**，扫描全部源码，出现这些调用就测试失败 |
| **后端必须独立校验输入** | 前端虽然会拦非法输入，但接口可以被 `curl` 直接调用，不能信任前端 |
| **请求体大小上限** | `MAX_BODY_BYTES = 64KB`，防止超大请求 |
| **表达式长度上限** | `MAX_EXPRESSION_LENGTH = 200` |
| **异常不外泄细节** | 500 错误只回通用提示，堆栈打印在服务端日志里 |

## 7. 本仓库的取舍说明

| 条款 | 取舍 | 原因 |
|---|---|---|
| PEP 8 的 79 字符行宽 | 放宽到 100 | 中文注释在 79 字符内很难说清一件事 |
| Google 风格要求 100% 测试覆盖 | 未强制 | 但核心模块（tokenizer / parser / evaluator / store）都有测试，共 157 项 |
| 引入 `black` / `flake8` 等格式化工具 | 未引入 | 本机 `pip install` 不可用（网络受限）；已用统一的书写习惯代替 |
| 引入类型检查器 `mypy` | 未引入 | 同上；但类型标注是齐全的，随时可以接上 |
| 引入 Web 框架（Flask/FastAPI） | 未引入 | 见 README §2：全标准库换来"助教拿到就能跑" |
| 用 `dataclass` 而不是普通类 | 采用 | 语法树节点、结果对象都是纯数据，`@dataclass(frozen=True)` 自动生成 `__eq__` 与 `__repr__`，测试里能直接比较对象相等 |

## 8. 提交信息（Git Commit Message）

采用 Conventional Commits 的简化形式：

```
<type>: <中文简述>
```

| type | 含义 |
|---|---|
| `feat` | 新功能 |
| `fix` | 修 bug |
| `test` | 只改测试 |
| `docs` | 只改文档 |
| `refactor` | 重构，行为不变 |
| `chore` | 杂项（配置、忽略文件等） |

## 9. 自检清单（提交前逐条确认）

- [ ] `py -3.12 -m unittest discover -s tests` 全部通过
- [ ] `py -3.12 tools/blackbox.py` 全部通过
- [ ] 全仓搜索 `eval(` / `exec(` / `compile(` 无命中（排除 `re.compile`）
- [ ] 每个模块、每个公开函数都有 docstring
- [ ] 所有函数都有类型标注
- [ ] 没有 `print()` 调试残留（服务启动信息除外）
- [ ] 文件均为 UTF-8，缩进为 4 空格
- [ ] 数据库文件 `data/*.db` 未被提交（已 gitignore）

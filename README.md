# translate_cli / Transfold

translate_cli 提供面向单条文本的命令行翻译工具，而 Transfold 则面向批量文档翻译，整体围绕 OpenRouter API 构建，可用于高质量技术文档、博客或产品手册的多语言化。

## 核心能力概览

- **单次调用 CLI**：`python -m translate_cli "Hello" fr` 可直接将一条字符串翻译成法语。
- **批量翻译引擎**：`transfold` 支持递归扫描目录、拆分 Markdown 段落、并行调用 OpenRouter。
- **可配置化**：通过 `.env` 与 `transfold.config.{yaml,json,toml}` 控制模型、并发、批量大小、过滤规则等。
- **安全退避机制**：当 OpenRouter 批量响应段落数与请求不匹配时，会自动回退到逐段请求，确保文档完整译出。
- **结构保留**：默认不翻译代码块、内联代码、URL 和 front matter，可按需切换。

## 快速开始

1. 拷贝示例环境变量并填写：

   ```bash
   cp .env_example .env
   # 编辑 .env 设置 OPENROUTER_API_KEY、MODEL、可选代理配置等
   ```

2. 创建虚拟环境并安装依赖（推荐可选 YAML 支持）：

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e '.[yaml]'
   ```

3. 验证命令行：

   ```bash
   python -m translate_cli "Hello world" fr
   python -m transfold.cli --input docs --target-lang es --dry-run
   ```

### 启动 Web 应用

后端基于 FastAPI，前端使用 React + Vite，二者通过 REST API 对接批量翻译任务：

```bash
# 后端（默认读取 .env，监听 8000 端口）
python -m web.backend

# 前端（在 web/frontend 下）
cd web/frontend
npm install
npm run dev
```

> **提示**：`python -m web.backend` 会在开发模式下自动启用热重载，但仅监控
> `web/backend` 源码目录，同时忽略 `DATA_ROOT` 下的仓库与译文输出，避免出
> 现 `OS file watch limit reached` 报错。若需关闭热重载，可设置
> `UVICORN_RELOAD=0` 后再执行上述命令。

开发环境默认将 `/api` 请求代理到 `http://localhost:8000`。`DATA_ROOT` 用于指定仓库克隆、译文输出和日志存储位置，可在 `.env` 中覆盖。

## 关键环境变量

| 变量名 | 说明 |
| ------ | ---- |
| `OPENROUTER_API_KEY` | **必填**，OpenRouter 控制台生成的密钥。 |
| `MODEL` / `OPENROUTER_MODEL` | **必填**，模型标识，如 `openrouter/auto`、`openai/gpt-4o-mini`。 |
| `OPENROUTER_BASE_URL` | 可选，自建代理或中转地址。 |
| `OPENROUTER_SITE_URL`、`OPENROUTER_APP_NAME` | 可选，随请求发送的鉴别信息。 |
| `TRANSFOLD_SPLIT_THRESHOLD` | 可选，低于阈值的文件不拆分，直接作为单次翻译提交。 |
| `DATA_ROOT` | 可选，Web 后端用于克隆仓库、输出译文与存放日志的根目录，默认 `var/transfold`。 |

## Transfold 命令用法

```bash
transfold \
  --input ./docs \
  --target-lang zh \
  --ext md,txt \
  --output ./docs_zh \
  --concurrency 8
```

常用参数说明：

- `--input`：**必填**，扫描的根目录。
- `--target-lang`：**必填**，目标语言代码（如 `zh`、`en`、`fr`）。
- `--ext`：逗号分隔的文件扩展名，默认 `md`。
- `--output`：输出目录，缺省时原地覆盖并生成 `.bak` 备份。
- `--model`、`--source-lang`：指定模型与源语言（或 `auto` 自动检测）。
- `--concurrency`、`--batch-chars`、`--batch-segments`：控制并发与批量大小。
- `--dry-run`：仅统计待翻译文件与段落，不触发 API 调用。
- `--glossary`：加载 JSON 或 CSV 术语库，强制特定翻译。
- `--translate-code` / `--translate-frontmatter`：显式开启代码块或 front matter 翻译。

## Web 功能概览

- **任务提交页**：输入 GitHub HTTPS 仓库地址、选择扩展名与可选输出目录，提交后排队执行翻译并展示最近任务。
- **分支控制**：可在任务提交时指定 Git 分支（默认使用远端默认分支），后端使用 `git clone --depth 1 --single-branch` 拉取最新版本，避免下载全部历史。
- **任务详情页**：实时轮询整体百分比、ETA、失败文件与日志摘要，可一键重跑并跳转至译文预览。
- **历史记录页**：支持搜索、分页、删除记录及重新执行任务，便于长期归档与手动清理。
- **译文预览页**：左侧目录树、右侧语法高亮内容，可直接浏览输出文件，默认选中首个译文文件。

### 包含/排除规则

- `--include` 与 `--exclude` 支持 glob 相对路径模式，可重复使用。
- 例如：`transfold --input docs --target-lang zh --include "**/*.md" --exclude "**/node_modules/**"`

### 批量回退策略

OpenRouter 有时会在批量响应中遗漏或重复段落。Transfold 会检测返回段落数量：

1. 若段落数匹配，按批量顺序应用翻译并计入批量统计；
2. 若不匹配，则记录原始响应、统计 token 用量，并自动逐段重新请求；
3. 回退时仍复用同一系统提示，保证翻译风格一致；
4. 相关行为已覆盖在 `tests/test_translator.py` 中的异步单元测试。

## 配置文件示例（`transfold.config.yaml`）

```yaml
input: ./docs
output: ./docs_zh
ext: [md]
target_lang: zh
source_lang: auto
model: openrouter/auto
concurrency: 8
include:
  - "**/*.md"
exclude:
  - "**/node_modules/**"
chunk:
  strategy: markdown
  max_chars: 4000
  split_threshold: 8000
preserve_code: true
preserve_frontmatter: true
retry: 3
timeout: 60
backup: true
batch:
  chars: 16000
  segments: 6
```

## 开发与测试

- 建议使用 `python -m pytest --maxfail=1 --ff` 运行完整测试，异步用例依赖 `pytest-asyncio`。
- 重点模块：
  - `translate_cli/`：加载 `.env`、封装 OpenRouter 客户端，适合单次翻译。
  - `transfold/`：批量翻译引擎，含切片、并发调度与文件写入逻辑。
  - `tests/`：覆盖 HTTP stub、异步调度、批量解析、CLI 参数等场景。
- 如需排查具体文件，可使用 `python -m pytest -k keyword` 精准过滤。

## 常见问题

- **命令提示 `OpenRouter batch translation did not return the expected number of segments`**：新版 Transfold 会自动回退到单段请求，无需手动干预；若频繁出现，建议检查模型输出格式或缩减批量规模。
- **缺少依赖**：运行 `pip install -e .[yaml]` 或根据报错安装对应包（如 `httpx`、`pytest-asyncio`）。
- **API Key 泄露风险**：不要将 `.env` 或明文密钥提交到版本库，可通过环境变量或密钥管理服务注入。

## 许可证

本项目基于 MIT License 发布，详情见 `LICENSE` 文件。

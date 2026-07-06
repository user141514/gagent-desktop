# 🖥️ Cowork

<p align="center">
  <strong>你的桌面 AI 工作台 — 能聊天、能写代码、能操作文件。</strong><br/>
  基于 GenericAgent 内核，加上编排层、聊天界面、附件支持和记忆系统。
</p>

<p align="center">
  <img alt="ui" src="https://img.shields.io/badge/ui-Streamlit-0f9d58">
  <img alt="python" src="https://img.shields.io/badge/python-3.11+-blue">
  <img alt="status" src="https://img.shields.io/badge/status-hacking-orange">
</p>

---

## 🚀 5 分钟跑起来

```
 ┌─────────────────────────────────────────┐
 │                                         │
 │   📦 Clone          🔑 配 Key          🏃 启动      │
 │   git clone ...     copy 模板填 key    python launch │
 │                                         │
 └─────────────────────────────────────────┘
```

### 第一步：把代码拉下来

```bash
git clone https://github.com/user141514/GenericAgent-Workbench.git
cd GenericAgent-Workbench
```

### 第二步：装依赖

需要 Python 3.11+。推荐用 conda：

```bash
conda create -n rag-env python=3.11 -y
conda activate rag-env
pip install -r requirements.txt
```

### 第三步：配 API Key

```bash
copy mykey_template.py mykey.py
```

然后打开 `mykey.py`，把你自己的 API key 填进去：

```python
key1_native_oai_config = {
    'name': 'deepseek',
    'apikey': 'sk-你的key放这里',    # ← 改这里
    'apibase': 'https://api.deepseek.com',
    'model': 'deepseek-v4-pro',
    ...
}
```

> 💡 模板里所有 `REPLACE_WITH_*` 的地方都要改。不知道怎么填？往下看 [FAQ](#-常见问题)。

### 第四步：启动！

```bash
python launch.pyw
```

弹出一个桌面窗口，在输入框里打字，回车。搞定。

---

## 🎮 常用入口

| 命令 | 干嘛的 |
|---|---|
| `python launch.pyw` | 桌面窗口 + Streamlit 界面 |
| `python launch.pyw --sched` | 带定时任务的桌面版 |
| `python frontends/tgapp.py` | Telegram Bot |
| `python frontends/fsapp.py` | 飞书 Bot |
| `python frontends/wecomapp.py` | 企业微信 Bot |

---

## 🧠 它能做什么

```
你问它 "帮我写个快排"
        │
        ▼
   ┌─────────────┐
   │ task_router │  ← 判断：这是简单问题还是复杂任务？
   └──────┬──────┘
          │
    ┌─────┴─────┐
    ▼           ▼
 简单聊天    复杂任务
    │           │
    ▼           ▼
 直接回答   planner → 写代码 → 跑测试 → 验证结果
```

- **聊天**：日常问答、解释概念、写文档
- **写代码**：创建文件、修改代码、跑 shell 命令
- **操作浏览器**：自动化网页操作
- **附件上下文**：拖 PDF / DOCX / 文本进去，它自己读
- **历史恢复**：以前的对话随时捡起来继续
- **记忆系统**：重要内容不会丢，跨会话保留

---

## 📁 目录长什么样

```
GenericAgent-Workbench/
├── core/              ← 大脑（编排、路由、LLM 适配）
├── frontends/
│   ├── stapp.py       ← Streamlit 主界面
│   ├── tgapp.py       ← Telegram 入口
│   └── fsapp.py       ← 飞书入口
├── memory/            ← 跨会话记忆
├── launch.pyw         ← 双击启动
└── mykey_template.py  ← Key 模板 → 复制为 mykey.py
```

---

## ❓ 常见问题

<details>
<summary><strong>Q: 我用的是 OpenAI / 其他供应商，怎么配？</strong></summary>

改 `mykey.py` 里的 `apibase` 和 `model` 就行：

```python
key1_native_oai_config = {
    'apikey': 'sk-xxx',
    'apibase': 'https://api.openai.com/v1',   # ← OpenAI
    'model': 'gpt-4o',
}
```

DeepSeek、GLM、月之暗面……只要兼容 OpenAI Chat Completions API 的都行。
</details>

<details>
<summary><strong>Q: 我想配多个模型来回切换，怎么弄？</strong></summary>

`mykey_template.py` 里已经有 key1 / key2 / key3 三个槽位，分别填就行。Sidebar 里会显示切换按钮。
</details>

<details>
<summary><strong>Q: 和上游 GenericAgent 是什么关系？</strong></summary>

上游 [GenericAgent](https://github.com/lsdefine/GenericAgent) 是执行内核。这个项目在内核外面包了一层：
- 多智能体编排（让简单的归简单，复杂的归复杂）
- Streamlit 工作台界面
- 附件、历史、记忆

不是替代品，是工作台。
</details>

<details>
<summary><strong>Q: 支持什么文件格式？</strong></summary>

文本文件、PDF、DOCX。上传后自动抽取正文，长文会自动压缩。
</details>

<details>
<summary><strong>Q: Windows 之外能用吗？</strong></summary>

核心逻辑跨平台。桌面窗口（`launch.pyw`）依赖 `pywebview`，macOS/Linux 也能跑。部分自动化工具（ADB、uiautomator2）只在 Windows 测试过。
</details>

---

## ⚠️ 注意事项

- **不要提交 `mykey.py`** — 它已经在 `.gitignore` 里了，`git status` 看不到它就是正常的
- 前端密码锁暂时关闭（移动端还没上线），本地使用不需要密码
- 如果启动报错 "No API key"，检查 `mykey.py` 是否创建好了
- 想看更多技术细节？[workflow.md](./workflow.md) 和 [CONTRIBUTING.md](./CONTRIBUTING.md)

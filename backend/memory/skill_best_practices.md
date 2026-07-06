# Skill/Agent 最佳实践 SOP

> 来源：claude-code-best-practice 项目实例分析
> 日期：2026-04-21

## 核心架构：Skill-Agent-Command 三层分离

```
Command (用户入口/协调者) → Agent (执行者) → Skill (知识包)
```

| 层级 | 职责 | 特征 |
|------|------|------|
| Command | 协调多Agent/Skill | 用户触发(/)，model可用haiku省钱 |
| Agent | 完整工作流执行 | 预加载Skill，声明工具权限，Learnings积累 |
| Skill | 单一任务知识 | 无状态，纯指令，标准化输出 |

---

## Skill 最小可行原则

### 1. Frontmatter 三要素
```yaml
---
name: [唯一标识]
description: [何时使用 - 触发条件导向]
user-invocable: [true/false]
---
```

### 2. 内容四层结构（按复杂度递增）

#### Level 1: 简单工具型
```markdown
## Task
[一句话目标]

## Instructions
1. [步骤1 - 包含具体命令/URL/字段路径]
2. [步骤2]

## Expected Output
```
[标准输出格式模板]
```

## Notes
- [只做X]
- [不做Y]
```

#### Level 2: 参考文档型
- 主文件精简，细节外部化到 `reference.md` / `examples.md`

#### Level 3: 工作流型
- Core Workflow（所有任务遵循的模式）
- Essential Commands（命令速查表）
- Common Patterns（场景化模式）

#### Level 4: 知识库型
- 多维度知识章节
- 结构化参考表（Reference Table）

### 3. 核心设计原则
- **单一职责**：一个skill只做一件事
- **无副作用**：Notes明确边界约束
- **明确输出**：Expected Output模板化
- **触发导向**：description写何时用，非功能描述

---

## Agent 设计原则

### 1. Frontmatter 配置
```yaml
---
name: [agent-id]
description: [何时使用 - 包含PROACTIVELY等触发词]
allowedTools: [工具权限边界 - 最小权限原则]
model: [模型选择]
maxTurns: [资源限制]
skills: [预加载知识包列表]
memory: [记忆范围]
hooks: [生命周期钩子]
---
```

### 2. Self-Evolution 机制（关键发现）
```
执行任务 → 发现问题/模式 → 写入Learnings → 下次执行自动继承
                    ↓
              更新相关Skill/文档（跨文档一致性）
```

**Learnings 格式**：
```markdown
## Learnings
- 2026-04-21: [edge case/pattern发现]
- 2026-04-20: [避坑指南]
```

### 3. 执行闭环
```markdown
## Workflow
1. Read current state (先读后改)
2. Apply changes (执行变更)
3. Verify integrity (验证闭环 - 检查清单)
4. Self-evolution (自我进化)
```

---

## Command 设计原则

### 1. 协调者角色
- 用 AskUserQuestion 获取用户偏好
- 用 Task 工具调用 Agent
- 用 Skill 工具调用 Skill

### 2. 资源优化
- model 可用 haiku 省钱（仅协调）
- Sequential Flow（顺序执行）

---

## 与我的SOP系统整合

### 可直接应用
1. **Expected Output 模板化**：在 my SOPs 添加标准输出格式
2. **Learnings 积累机制**：在 Agent 类 SOP 添加 Learnings 章节
3. **Notes 边界约束**：明确"不做"什么

### 已有类似机制
- 我的SOP已有"先读后改"原则
- 我的记忆系统有跨文档同步

### 待增强
- 在 agent 类 SOP 添加 allowedTools 声明
- 在复杂 SOP 添加 Self-Evolution 章节
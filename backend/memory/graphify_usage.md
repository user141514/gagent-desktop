# graphify 知识图谱工具 - 使用备忘

**版本**: 0.4.23 (graphifyy)
**路径**: `E:\Anaconda3\envs\rag-env\Scripts\graphify.exe`
**Skill**: `C:\Users\Administrator\.claude\skills\graphify\SKILL.md`
**Python API**: `from graphify import extract, build_from_json, cluster, export, report`

## 两种使用方式

### 1. CLI (AST-only，无LLM开销)
```bash
# 重建知识图谱（仅AST结构提取，几秒完成）
graphify update <目标目录> --out <输出目录>

# 查询已有图谱
graphify query "问题" --graph graph.json

# 解释某节点
graphify explain <节点名> --graph graph.json
```

### 2. Claude Desktop Skill (完整管道，含LLM语义提取)
- 在Claude Code中触发: `/graphify <路径>`
- 自动完成: extract → build → cluster → report → export
- 输出: graph.json + graph.html + GRAPH_REPORT.md

## 已验证: 本项目已有的两个图谱
- `F:\GAgent-Multi\graphify-out/` - 主项目图 (792节点, 1824边)
- `F:\GAgent-Multi\memory\graphify-out/` - memory/ 子图 (152节点, 222边, 12社区)

## Python API 关键函数
- `extract.collect_files(target_path)` - 收集文件
- `extract.extract(files)` - 提取节点/边
- `build_from_json(extraction)` - 构建NetworkX图
- `cluster(graph)` - 社区检测
- `export.to_html(graph, path)` - 导出HTML可视化
- `report.generate(graph, path)` - 生成报告

## 最佳实践
- **日常快速更新**: 用 `graphify update` (无LLM成本，纯AST)
- **深度语义分析**: 在Claude Desktop中用 `/graphify` (需LLM tokens)
- **查询已有图**: 用 `graphify query` + `explain`
- **多目录复用**: 每个目录保留独立的 `graphify-out/` 子目录

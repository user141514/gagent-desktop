# Streamlit 避坑指南 (streamlit_pitfalls.md)

## 1. 弹窗/dialog渲染逻辑
- dialog定义应在fragment内的for循环**之前**，每个文件独立state key
- 弹窗在for循环外调用会导致fragment隔离和state同步问题
- **推荐**：用 `st.expander` 替代 `st.dialog` 可避免弹窗乱跳

## 2. turn_end_callback 时序
- `turn_end_callback` 在后端完成时**立即触发**，**不等待**前端流式输出完成
- 需要给前端缓冲时间，或改为前端触发回调

## 3. 对话删除状态清理
- 删除对话后必须清理相关 `session_state`，否则仍能继续旧对话
- 删除操作应同步清除 `st.session_state` 中的对应key

## Learnings
- 2026-04-20: `st.dialog` 必须在 `@st.fragment` 装饰的函数内、在 `for` 循环之前定义，且每个文件使用独立 `session_state` key（如 `distill_btn_<filename>` + `distill_result_<filename>`），否则 fragment 隔离机制导致 state 同步失败，弹窗不响应按钮
- 2026-04-20: 弹窗在 fragment 外调用（包括 `distill_preview` 残留值）会导致打开对话历史时自动弹出空白弹窗；解决方案：dialog 逻辑全部收敛到 fragment 内部
- 2026-04-20: 推荐用 `st.expander` 替代 `st.dialog` 展示提炼/分析结果，可彻底避免弹窗乱跳问题
- 2026-04-23: `turn_end_callback` 在后端 LLM 响应完成的瞬间立即触发，不等待前端流式渲染结束；需给前端缓冲时间或改为前端主动触发回调
- 2026-04-23: 删除对话操作必须同步清除 `st.session_state` 中该对话的所有关联 key（消息列表、状态标记、文件引用等），否则后端切换对话但前端 state 残留导致旧对话仍然可用
- 2026-04-28: 历史消息渲染不要用 `st.empty()` 动态替换，应直接渲染到稳定容器中；`st.empty()` 在每次 rerun 时重建占位符导致旧内容消失

## 验证状态 (2026-06-13, R24审查)
- **P1 st.dialog**: ~~弹窗乱跳~~ → 已修复（stapp.py全用st.expander+fragment，零st.dialog）
- **P2 turn_end_callback**: ~~不等前端~~ → 已修复（改为hook字典机制）
- **P3 删除清理**: ~~残留~~ → 已修复（delete+new均完整清理session_state）
- **P4 st.empty()**: 仍在使用(L634)但外层有`st.chat_message()`容器保护，低风险
- **R18闭环**: ✅ 已验证通过
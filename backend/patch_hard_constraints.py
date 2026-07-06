from pathlib import Path
import re

ROOT = Path(r"C:\Users\Administrator\AppData\Roaming\npm\node_modules\gagent-desktop\backend")

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="ignore")

def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")

def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        print(f"[skip] pattern not found in {path}: {old[:80]!r}")
        return
    text = text.replace(old, new, 1)
    write(path, text)
    print(f"[ok] patched {path}")

def patch_context_defaults():
    targets = [
        "core/openai_agentmain.py",
        "core/context/__init__.py",
        "core/context/project_identity.py",
        "core/context/runtime_identity.py",
        "core/context/session_store.py",
        "core/context/workspace_probe.py",
    ]
    for rel in targets:
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        original = text
        text = text.replace(
            'os.environ.get("GA_CONTEXT_RUNTIME_ENABLED", "0") == "1"',
            'os.environ.get("GA_CONTEXT_RUNTIME_ENABLED", "1").strip() != "0"',
        )
        text = text.replace(
            '_os.environ.get("GA_CONTEXT_RUNTIME_ENABLED", "0") == "1"',
            '_os.environ.get("GA_CONTEXT_RUNTIME_ENABLED", "1").strip() != "0"',
        )
        if text != original:
            p.write_text(text, encoding="utf-8")
            print(f"[ok] context runtime default enabled in {rel}")

def patch_context_budget():
    path = "core/context/context_builder.py"
    text = read(path)
    original = text

    text = text.replace(
        '    "code":            {"workspace": 100, "project": 100,  "state": 0,   "memory": 1500, "recent_turns": 800,  "working_memory": 600},',
        '    "code":            {"workspace": 150, "project": 150,  "state": 500, "memory": 1500, "recent_turns": 1200, "working_memory": 1000},',
    )
    text = text.replace(
        '    "research":        {"workspace": 100, "project": 100,  "state": 0,   "memory": 2500, "recent_turns": 800,  "working_memory": 600},',
        '    "research":        {"workspace": 150, "project": 150,  "state": 300, "memory": 2500, "recent_turns": 1200, "working_memory": 1000},',
    )

    if text != original:
        write(path, text)
        print("[ok] patched context route budgets")
    else:
        print("[skip] context budget patterns not found or already patched")

def patch_sys_prompt():
    path = "assets/sys_prompt.txt"
    text = read(path)
    marker = "## 硬系统约束：深度、工程模式、验证门"
    if marker in text:
        print("[skip] sys_prompt hard constraints already present")
        return

    block = f"""

{marker}
- 对复杂解释、决策、架构、代码任务，禁止只给单句结论。最终回答必须至少覆盖：结论、原因、边界、下一步。
- 对一句话编程任务，默认进入工程模式：先探测项目结构，再形成计划，再修改，再验证，再收尾。
- 工程模式下，未读取项目结构、入口文件、配置文件或相关上下文前，不允许声称已经完成。
- 发生 file_patch/file_write 后，最终回答前必须执行最小验证：测试、构建、静态检查、运行脚本、读取修改后文件，或明确说明无法验证的原因。
- 如果上一轮回答过短、缺少原因、缺少边界、缺少验证说明，必须自动重写深化，不要直接结束。
- 状态不是装饰信息，而是控制信号。每轮必须根据当前状态判断：目标是否明确、证据是否足够、是否允许停止。
"""
    text = text.rstrip() + block + "\n"
    write(path, text)
    print("[ok] appended hard constraints to sys_prompt")

def patch_ga_hard_gate():
    path = "core/ga.py"
    text = read(path)

    if "def _hard_constraints_task_text" not in text:
        helper = r'''
    def _hard_constraints_task_text(self):
        raw = str(
            getattr(self, "_last_user_input", "")
            or getattr(getattr(self, "parent", None), "_current_user_input", "")
            or ""
        )
        match = re.search(
            r"Original user request:\s*(.*?)\n\s*Execution plan",
            raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return match.group(1).strip() if match else raw.strip()

    def _hard_constraints_is_engineering_task(self):
        text = self._hard_constraints_task_text().lower()
        markers = (
            "写一个", "写个", "做一个", "做个", "实现", "修复", "改成", "改一下",
            "添加", "增加", "重构", "搭建", "生成代码", "写代码", "编程",
            "implement", "fix", "patch", "refactor", "build", "create", "add feature",
        )
        return any(marker in text for marker in markers)

    def _hard_constraints_needs_depth(self):
        text = self._hard_constraints_task_text().lower()
        markers = (
            "为什么", "怎么理解", "如何理解", "原理", "机制", "架构", "设计",
            "方案", "比较", "分析", "评估", "改进", "优化", "深度", "本质",
            "why", "how", "explain", "architecture", "design", "analyze",
        )
        return any(marker in text for marker in markers)

    def _hard_constraints_clean_answer(self, content):
        value = str(content or "")
        value = re.sub(r"<thinking>[\s\S]*?</thinking>", " ", value, flags=re.IGNORECASE)
        value = re.sub(r"<summary>[\s\S]*?</summary>", " ", value, flags=re.IGNORECASE)
        value = re.sub(r"```[\s\S]*?```", " ", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _hard_constraints_action_trace(self, response_text=""):
        parts = []
        try:
            state = self._build_execution_state(response_text)
            for action in list(getattr(state, "actual_actions", []) or []):
                if hasattr(action, "to_dict"):
                    parts.append(str(action.to_dict()))
                elif hasattr(action, "__dict__"):
                    parts.append(str(action.__dict__))
                else:
                    parts.append(str(action))
            delta = getattr(state, "state_delta", None)
            if delta is not None:
                if hasattr(delta, "to_dict"):
                    parts.append(str(delta.to_dict()))
                elif hasattr(delta, "__dict__"):
                    parts.append(str(delta.__dict__))
        except Exception:
            pass

        try:
            parts.extend(str(x) for x in self.history_info[-30:])
        except Exception:
            pass

        blob = "\n".join(parts).lower()
        return {
            "has_probe": any(x in blob for x in (
                "file_read", "code_run", "reading file", "executed code",
                "读取", "已读取", "运行", "测试",
            )),
            "has_write": any(x in blob for x in (
                "file_patch", "file_write", "writed_bytes", "files_changed",
                "写入", "修改", "已修改", "updated",
            )),
            "has_verify": any(x in blob for x in (
                "pytest", "npm test", "npm run build", "node --check",
                "py_compile", "unittest", "测试", "验证", "build", "test",
                "exit code: 0", "✅",
            )),
        }

    def _hard_constraints_final_block_reason(self, content):
        clean = self._hard_constraints_clean_answer(content)
        engineering = self._hard_constraints_is_engineering_task()
        deep = self._hard_constraints_needs_depth()
        trace = self._hard_constraints_action_trace(content)

        if engineering:
            if not trace["has_probe"]:
                return (
                    "工程任务最终回答被拦截：尚未看到项目探测或上下文读取证据。"
                    "请先用 file_read/code_run 探测目录、README、package/pyproject、入口文件或相关源码，"
                    "再给出计划或继续实现。"
                )
            if trace["has_write"] and not trace["has_verify"]:
                return (
                    "工程任务最终回答被拦截：检测到已有修改迹象，但尚未看到验证证据。"
                    "请运行最小验证，例如测试、构建、语法检查、关键脚本，或读取修改后文件确认。"
                    "无法验证时必须说明具体阻塞和风险。"
                )
            if len(clean) < 220 and not any(x in clean for x in ("修改", "文件", "验证", "风险", "下一步")):
                return (
                    "工程任务最终回答过浅。请重写为：目标理解、已做动作、涉及文件、验证方式、验证结果、剩余风险。"
                )

        if deep:
            sentence_count = len([x for x in re.split(r"[。！？!?]+|(?<!\.)\.(?!\.)", clean) if x.strip()])
            required_hits = sum(1 for x in ("结论", "原因", "边界", "下一步", "验证") if x in clean)
            if len(clean) < 180 or sentence_count < 3 or required_hits < 2:
                return (
                    "最终回答过浅。请重写并至少覆盖：结论、为什么、边界条件、下一步可验证动作。"
                    "不要只给单句答案。"
                )

        return ""
'''
        marker = "    def do_no_tool(self, args, response):"
        if marker not in text:
            raise RuntimeError("Cannot find do_no_tool marker in core/ga.py")
        text = text.replace(marker, helper + "\n" + marker, 1)
        print("[ok] inserted hard constraint helper methods")
    else:
        print("[skip] hard constraint helper methods already present")

    if "hard_constraint_repair_count" not in text:
        guard = r'''
        hard_block_reason = self._hard_constraints_final_block_reason(content)
        if hard_block_reason:
            repair_count = int(self.working.get("hard_constraint_repair_count", 0) or 0)
            if repair_count < 2:
                self.working["hard_constraint_repair_count"] = repair_count + 1
                yield "[Hard Constraint] Final response blocked by depth/execution gate.\n"
                return StepOutcome(
                    {},
                    next_prompt=(
                        "[System Hard Constraint]\n"
                        + hard_block_reason
                        + "\n必须继续执行或重写深化。禁止直接结束；禁止把未验证内容写成已完成。"
                    ),
                )
'''
        pattern = (
            r"(        if 'max_tokens !!!\]' in content\[-100:\]:\n"
            r"            return StepOutcome\(\{\}, next_prompt=\"\[System\] max_tokens limit reached\. Use multi small steps to do it\.\"\)\n)"
        )
        new_text, n = re.subn(pattern, r"\1" + guard, text, count=1)
        if n == 0:
            # fallback: insert before plan-mode completion gate
            fallback = "        if self._in_plan_mode() and any(kw in content for kw in ['任务完成', '全部完成', '已完成所有', '🏁']):"
            if fallback not in text:
                raise RuntimeError("Cannot find insertion point for final gate in do_no_tool")
            new_text = text.replace(fallback, guard + "\n" + fallback, 1)
        text = new_text
        print("[ok] inserted final response hard gate")
    else:
        print("[skip] final response hard gate already present")

    write(path, text)

def compile_check():
    import py_compile
    files = [
        "core/ga.py",
        "core/openai_agentmain.py",
        "core/context/context_builder.py",
        "core/context/__init__.py",
    ]
    for rel in files:
        py_compile.compile(str(ROOT / rel), doraise=True)
        print(f"[ok] py_compile {rel}")

def main():
    patch_context_defaults()
    patch_context_budget()
    patch_sys_prompt()
    patch_ga_hard_gate()
    compile_check()
    print("\n[DONE] Hard constraints installed. Restart gagent-desktop.")

if __name__ == "__main__":
    main()

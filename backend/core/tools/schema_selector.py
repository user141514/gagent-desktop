"""Rule-based tool schema selection for the classic executor."""

from __future__ import annotations

import os
import re
from typing import Any

from core.router_rules import RouterRules


SLIM_TOOLS_ENV_VAR = "GENERIC_AGENT_SLIM_TOOLS"


def slim_tools_enabled() -> bool:
    return str(os.environ.get(SLIM_TOOLS_ENV_VAR, "")).strip() == "1"


class ToolSchemaSelector:
    ALWAYS_INCLUDE = {"ask_user", "code_run"}
    BASE_READ_ONLY = {"file_read", "code_run", "ask_user"}
    FILE_DISCOVERY = {"file_read", "code_run", "ask_user"}
    WRITE_TOOLS = {"file_patch", "file_write"}
    WEB_SEARCH_TOOLS = {"web_search"}
    BROWSER_TOOLS = {"web_scan", "web_execute_js", "browser_agent"}
    WEB_TOOLS = WEB_SEARCH_TOOLS | BROWSER_TOOLS
    MEMORY_HELPERS = {"update_working_checkpoint", "start_long_term_update"}
    MEMORY_QUERY_TOOLS = {"file_read", "code_run", "ask_user"}
    REVIEW_BASE = {"file_read", "code_run", "ask_user", "update_working_checkpoint"}
    CODE_BASE = {"file_read", "code_run", "file_patch", "file_write", "ask_user", "update_working_checkpoint"}
    RESEARCH_BASE = {"file_read", "code_run", "ask_user", "web_search"}

    READ_PATTERNS = (
        r"readme",
        r"\bread\b",
        r"\btitle\b",
        r"\bfirst line\b",
        r"\blist\b",
        r"\bfind\b",
        r"\bsearch\b",
        r"\bgrep\b",
        r"\bproject\b",
        r"\bfile\b",
        r"读取",
        r"查看",
        r"第一行",
        r"标题",
        r"文件",
        r"目录",
        r"项目",
        r"查找",
        r"搜索",
        r"列出",
    )
    WRITE_PATTERNS = (
        r"\bmodify\b",
        r"\bedit\b",
        r"\bchange\b",
        r"\bpatch\b",
        r"\bwrite\b",
        r"\bupdate\b",
        r"\bcreate\b",
        r"\bimplement\b",
        r"\bfix\b",
        r"修改",
        r"编辑",
        r"更新",
        r"写入",
        r"新增",
        r"创建",
        r"实现",
        r"修复",
    )
    RUN_PATTERNS = (
        r"\brun\b",
        r"\btest\b",
        r"\bpytest\b",
        r"\binstall\b",
        r"\bstart\b",
        r"\bbuild\b",
        r"\bcompile\b",
        r"\bnpm\b",
        r"\bpip\b",
        r"\bshell\b",
        r"\bcommand\b",
        r"运行",
        r"测试",
        r"安装",
        r"启动",
        r"编译",
        r"命令",
        r"执行",
    )
    WEB_PATTERNS = (
        r"\bweb\b",
        r"\bbrowser\b",
        r"\bwebsite\b",
        r"\bsearch the web\b",
        r"网页",
        r"网站",
        r"浏览器",
        r"网页资料",
        r"上网",
    )
    MEMORY_PATTERNS = (
        r"\bmemory\b",
        r"\bhistory\b",
        r"\bprevious\b",
        r"\blast time\b",
        r"\brecall\b",
        r"记忆",
        r"历史",
        r"之前",
        r"上次",
        r"回忆",
    )
    REVIEW_PATTERNS = (
        r"\breview\b",
        r"\baudit\b",
        r"\bbug\b",
        r"\bissue\b",
        r"\bfailure\b",
        r"\btraceback\b",
        r"\bexception\b",
        r"\blint\b",
        r"\bcoverage\b",
        r"\bregression\b",
        r"审查",
        r"检查",
        r"排查",
        r"定位",
        r"漏洞",
        r"安全",
        r"报错",
        r"日志",
        r"失败",
        r"异常",
        r"回归",
    )
    RESEARCH_PATTERNS = (
        r"\bdocs?\b",
        r"\bdocumentation\b",
        r"\bapi\b",
        r"\bchangelog\b",
        r"\brelease note\b",
        r"\bexample\b",
        r"\btutorial\b",
        r"\bcompare\b",
        r"文档",
        r"教程",
        r"用法",
        r"示例",
        r"调研",
        r"对比",
        r"新特性",
        r"更新日志",
        r"官方",
    )
    FIX_PATTERNS = (
        r"\bfix\b",
        r"\bpatch\b",
        r"\brepair\b",
        r"\bresolve\b",
        r"修复",
        r"改一下",
        r"改成",
        r"处理掉",
    )
    BROWSER_PATTERNS = (
        r"\blogin\b",
        r"\bsign in\b",
        r"\bform\b",
        r"\bclick\b",
        r"\bupload\b",
        r"\bdownload\b",
        r"\bnavigate\b",
        r"\bmulti-page\b",
        r"\bworkflow\b",
        r"登录",
        r"表单",
        r"点击",
        r"上传",
        r"下载",
        r"跳转",
        r"多页面",
        r"流程",
        r"网页自动化",
    )
    REPO_WIDE_PATTERNS = (
        r"\bwhole project\b",
        r"\bentire project\b",
        r"\brepo\b",
        r"\brepository\b",
        r"\bcross-file\b",
        r"\bend-to-end\b",
        r"整个项目",
        r"整个仓库",
        r"全仓库",
        r"跨文件",
        r"端到端",
        r"系统性",
        r"全量",
    )
    COMPLEX_PATTERNS = (
        r"\bcomplex\b",
        r"\bend-to-end\b",
        r"\bmulti-step\b",
        r"\bwhole project\b",
        r"\bentire project\b",
        r"\brefactor\b",
        r"复杂",
        r"端到端",
        r"多步骤",
        r"整个项目",
        r"全量",
        r"全面",
        r"重构",
    )

    def select_tools_for_task(
        self,
        user_input: str,
        available_tools: list[dict[str, Any]],
        mode: str = "classic",
    ) -> list[dict[str, Any]]:
        if mode != "classic":
            return list(available_tools)

        if os.environ.get("GENERIC_AGENT_WEB_TOOLS_ENABLED", "0").strip() != "1":
            available_tools = [tool for tool in available_tools if self._tool_name(tool) not in self.WEB_TOOLS]

        names = [self._tool_name(tool) for tool in available_tools]
        tool_map = {name: tool for name, tool in zip(names, available_tools) if name}
        normalized = self._normalize(user_input)
        route_target = RouterRules.match(user_input).target

        read_signal = self._matches(normalized, self.READ_PATTERNS)
        write_signal = self._matches(normalized, self.WRITE_PATTERNS)
        run_signal = self._matches(normalized, self.RUN_PATTERNS)
        web_signal = self._matches(normalized, self.WEB_PATTERNS)
        memory_signal = self._matches(normalized, self.MEMORY_PATTERNS)
        review_signal = self._matches(normalized, self.REVIEW_PATTERNS)
        research_signal = self._matches(normalized, self.RESEARCH_PATTERNS)
        fix_signal = self._matches(normalized, self.FIX_PATTERNS)
        browser_signal = self._matches(normalized, self.BROWSER_PATTERNS)
        repo_wide_signal = self._matches(normalized, self.REPO_WIDE_PATTERNS)
        complex_signal = self._matches(normalized, self.COMPLEX_PATTERNS) or repo_wide_signal
        signal_count = sum(
            bool(flag)
            for flag in (
                read_signal,
                write_signal,
                run_signal,
                web_signal,
                memory_signal,
                review_signal,
                research_signal,
                browser_signal,
            )
        )

        if (
            complex_signal
            or signal_count >= 4
            or (read_signal and write_signal and run_signal)
            or (write_signal and run_signal and review_signal)
        ):
            return list(available_tools)

        selected_names = set(self.ALWAYS_INCLUDE)

        if route_target == "code":
            selected_names.update(self.CODE_BASE)
        elif route_target == "executor":
            selected_names.update(self.CODE_BASE)
        elif route_target == "review":
            selected_names.update(self.REVIEW_BASE)
        elif route_target == "research":
            selected_names.update(self.RESEARCH_BASE)

        if memory_signal:
            selected_names.update(self.MEMORY_QUERY_TOOLS)

        if web_signal:
            selected_names.update(self.WEB_SEARCH_TOOLS)
            selected_names.add("code_run")

        if browser_signal:
            selected_names.update(self.WEB_SEARCH_TOOLS)
            selected_names.update(self.BROWSER_TOOLS)
            selected_names.add("update_working_checkpoint")

        if write_signal:
            selected_names.update(self.FILE_DISCOVERY)
            selected_names.update(self.WRITE_TOOLS)
            selected_names.add("update_working_checkpoint")

        if run_signal:
            selected_names.update(self.FILE_DISCOVERY)
            selected_names.add("update_working_checkpoint")

        if read_signal:
            selected_names.update(self.FILE_DISCOVERY)

        if review_signal:
            selected_names.update(self.REVIEW_BASE)

        if research_signal:
            selected_names.update(self.RESEARCH_BASE)
            if web_signal:
                selected_names.update(self.WEB_SEARCH_TOOLS)
            if browser_signal:
                selected_names.update(self.BROWSER_TOOLS)

        if fix_signal:
            selected_names.update(self.WRITE_TOOLS)
            selected_names.add("update_working_checkpoint")

        if not selected_names or selected_names == self.ALWAYS_INCLUDE:
            selected_names.update(self.BASE_READ_ONLY)

        resolved = [tool_map[name] for name in names if name in selected_names and name in tool_map]
        if resolved:
            return resolved

        fallback_names = self.BASE_READ_ONLY if any(name in tool_map for name in self.BASE_READ_ONLY) else self.ALWAYS_INCLUDE
        return [tool_map[name] for name in names if name in fallback_names and name in tool_map]

    @staticmethod
    def _tool_name(tool: dict[str, Any]) -> str:
        if not isinstance(tool, dict):
            return ""
        function_part = tool.get("function")
        if isinstance(function_part, dict):
            return str(function_part.get("name") or "").strip()
        return str(tool.get("name") or "").strip()

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(str(text or "").lower().split())

    @staticmethod
    def _matches(text: str, patterns: tuple[str, ...]) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def select_tools_for_task(user_input: str, available_tools: list[dict[str, Any]], mode: str = "classic") -> list[dict[str, Any]]:
    return ToolSchemaSelector().select_tools_for_task(user_input, available_tools, mode=mode)

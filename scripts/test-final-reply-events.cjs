const assert = require("node:assert/strict");

const turnMarkerRe = /(\**LLM Running \(Turn (\d+)\) \.\.\.\*\*)/g;
const toolBlockRe = /^Tool:\s*`[^`]+`\s+args:\s*\n`{3,}[^\n]*\n[\s\S]*?\n`{3,}\s*/gm;
const fencedStatusRe = /^`{3,}\s*\n\[(?:Action|Status|Stdout|Stderr|Error|Path Guard|Info)\][\s\S]*?\n`{3,}\s*/gm;
const statusLineRe = /^\[(?:Action|Status|Stdout|Stderr|Error|Path Guard|Info)\].*$/gm;
const summaryRe = /<summary>[\s\S]*?<\/summary>/gi;
const internalTagRe = /<\s*(?:thinking|summary|tool_use|tool_result|tool_call)\b[^>]*>[\s\S]*?<\s*\/\s*(?:thinking|summary|tool_use|tool_result|tool_call)\s*>\s*/gi;
const functionCallLineRe = /^[a-z][a-z0-9_]*\(\{.*\}\)\s*$/;
const jsonInternalLineRe = /^\s*(?:\[\s*)?\{.*(?:['"]type['"]\s*:\s*['"](?:thinking|tool_use|tool_call)['"]).*\}\s*(?:\])?\s*$/;
const functionCallStartRe = /^[a-z][a-z0-9_]*\s*\(\s*\{/i;
const jsonInternalTypeRe = /['"]type['"]\s*:\s*['"](?:thinking|tool_use|tool_call)['"]/i;
const internalTagStartRe = /<\s*(thinking|summary|tool_use|tool_result|tool_call)\b/i;
const statusLineStartRe = /^\[(?:Action|Status|Stdout|Stderr|Error|Path Guard|Info)\]/;
const toolLineStartRe = /^Tool:\s*`[^`]+`\s+args:/;

function latestTurnText(text, latestTraceTurn = 0) {
  const value = String(text || "");
  const matches = [...value.matchAll(turnMarkerRe)];
  if (matches.length === 0) return value;
  const match = matches[matches.length - 1];
  const marker = match[1] || "";
  const turn = Number(match[2] || 0);
  if (latestTraceTurn > 0 && turn < latestTraceTurn) return "";
  return value.slice((match.index || 0) + marker.length).trimStart();
}

function skipJsonBlock(lines, start) {
  if (start >= lines.length) return start;
  const stack = [];
  let quote = "";
  let escaped = false;
  let opened = false;
  for (let index = start; index < lines.length; index += 1) {
    const line = lines[index];
    for (const char of line) {
      if (quote) {
        if (escaped) escaped = false;
        else if (char === "\\") escaped = true;
        else if (char === quote) quote = "";
        continue;
      }
      if (char === '"' || char === "'") quote = char;
      else if (char === "{" || char === "[") {
        stack.push(char === "{" ? "}" : "]");
        opened = true;
      } else if (opened && stack[stack.length - 1] === char) {
        stack.pop();
        if (stack.length === 0) return index + 1;
      }
    }
  }
  return start;
}

function skipFunctionCall(lines, start) {
  let depth = 0;
  let quote = "";
  let escaped = false;
  let opened = false;
  for (let index = start; index < lines.length; index += 1) {
    const line = lines[index];
    for (const char of line) {
      if (quote) {
        if (escaped) escaped = false;
        else if (char === "\\") escaped = true;
        else if (char === quote) quote = "";
        continue;
      }
      if (char === '"' || char === "'" || char === "`") quote = char;
      else if (char === "(") {
        depth += 1;
        opened = true;
      } else if (char === ")" && opened) {
        depth -= 1;
        if (depth <= 0) return index + 1;
      }
    }
    if (index > start && /^\s*\}\)\s*;?\s*$/.test(line)) return index + 1;
  }
  return start + 1;
}

function skipInternalTag(lines, start) {
  const first = lines[start].trim();
  const match = first.match(internalTagStartRe);
  if (!match) return start + 1;
  const closeRe = new RegExp(`<\\s*\\/\\s*${match[1]}\\s*>`, "i");
  if (closeRe.test(first)) return start + 1;
  let index = start + 1;
  for (; index < lines.length; index += 1) {
    if (closeRe.test(lines[index])) return index + 1;
  }
  return start + 1;
}

function stripLeadingRuntimeNoise(text) {
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  let index = 0;
  let removed = false;
  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }
    if (functionCallLineRe.test(line)) {
      removed = true;
      index += 1;
      continue;
    }
    if (functionCallStartRe.test(line)) {
      removed = true;
      index = skipFunctionCall(lines, index);
      continue;
    }
    const jsonEnd = skipJsonBlock(lines, index);
    if (jsonEnd > index && jsonInternalTypeRe.test(lines.slice(index, jsonEnd).join("\n"))) {
      removed = true;
      index = jsonEnd;
      continue;
    }
    if (jsonInternalLineRe.test(line)) {
      removed = true;
      index += 1;
      continue;
    }
    if (line.startsWith("<") && internalTagStartRe.test(line)) {
      removed = true;
      index = skipInternalTag(lines, index);
      continue;
    }
    if (toolLineStartRe.test(line)) {
      removed = true;
      index += 1;
      while (index < lines.length && !lines[index].trim()) index += 1;
      if (lines[index]?.trim().startsWith("```")) {
        while (index < lines.length) {
          if (index > 0 && lines[index].trim().startsWith("```")) {
            index += 1;
            break;
          }
          index += 1;
        }
      }
      continue;
    }
    if (statusLineStartRe.test(line)) {
      removed = true;
      index += 1;
      continue;
    }
    if (line === "---" && removed) {
      index += 1;
      continue;
    }
    break;
  }
  return removed ? lines.slice(index).join("\n") : text;
}

function cleanVisibleText(text, latestTraceTurn = 0) {
  return stripLeadingRuntimeNoise(latestTurnText(text, latestTraceTurn))
    .replace(internalTagRe, "")
    .replace(summaryRe, "")
    .replace(toolBlockRe, "")
    .replace(fencedStatusRe, "")
    .replace(statusLineRe, "")
    .replace(turnMarkerRe, "")
    .replace(/\r\n/g, "\n")
    .replace(/^\s*---+\s*/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function appendText(previous, next) {
  if (!previous) return next || "";
  if (!next) return previous;
  if (next.startsWith(previous)) return next;
  if (previous.endsWith(next)) return previous;
  return `${previous}${next}`;
}

function applyEvent(messages, event, previousEvents = []) {
  const result = [...messages];
  const last = result[result.length - 1];
  const terminal = event.kind === "done" || event.kind === "stopped" || event.kind === "error";
  const traceEvents = [...previousEvents, event].filter((item) => item.turn && item.kind !== "status" && item.kind !== "frontier_state");
  if (event.kind === "chunk") {
    if (!last || last.role !== "assistant" || !last.streaming) {
      result.push({ role: "assistant", text: event.text, streaming: true, traceEvents });
    } else {
      result[result.length - 1] = { ...last, text: appendText(last.text, event.text), streaming: true, traceEvents: [...(last.traceEvents || []), event] };
    }
  } else if (event.kind === "done" || event.kind === "stopped") {
    if (!last || last.role !== "assistant" || !last.streaming) {
      result.push({ role: "assistant", text: event.text, streaming: false, traceEvents });
    } else {
      result[result.length - 1] = { ...last, text: event.text, streaming: false, traceEvents: [...(last.traceEvents || []), event] };
    }
  }
  return { messages: result, status: terminal ? "idle" : "running" };
}

function renderFinalText(message) {
  const visible = cleanVisibleText(message.text);
  if (!visible && message.role === "assistant" && !message.streaming && (message.traceEvents || []).length) {
    return "未收到可见最终回复，以下为运行过程。";
  }
  return visible;
}

function detailLineText(text) {
  const cleaned = cleanVisibleText(String(text || "")).replace(/\s+/g, " ").trim();
  return cleaned ? (cleaned.length > 140 ? `${cleaned.slice(0, 140)}...` : cleaned) : "";
}

function testSummaryOnlyDoneShowsFallback() {
  const state = applyEvent([], { kind: "done", text: "<summary>xxx</summary>", turn: 1 }, []);
  const visible = renderFinalText(state.messages.at(-1));
  assert.equal(visible, "未收到可见最终回复，以下为运行过程。");
}

function testSummaryChunkIsNotDetailGarbage() {
  const text = "**LLM Running (Turn 1) ...** <summary>xxx</summary>";
  assert.equal(detailLineText(text), "");
}

function testNormalDoneStillVisible() {
  const state = applyEvent([], { kind: "done", text: "这是最终回答", turn: 1 }, []);
  assert.equal(renderFinalText(state.messages.at(-1)), "这是最终回答");
}

testSummaryOnlyDoneShowsFallback();
testSummaryChunkIsNotDetailGarbage();
testNormalDoneStillVisible();
console.log("final reply event tests passed");

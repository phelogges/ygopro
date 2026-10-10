"use strict";

const byId = (id) => document.getElementById(id);
const tokenInput = byId("token");
const duelSelect = byId("duels");
const duelSearch = byId("duel-search");
const duelSort = byId("duel-sort");
const timeline = byId("timeline");
const stateJson = byId("state-json");
const eventsJson = byId("events-json");
const recordsJson = byId("records-json");
const handNoteText = byId("hand-note-text");
const handNoteMeta = byId("hand-note-meta");
const handNoteHistory = byId("hand-note-history");
const spellNoteText = byId("spell-note-text");
const spellNoteMeta = byId("spell-note-meta");
const spellNoteHistory = byId("spell-note-history");
const tokenKey = "ygopro-agent-view-token";
const pageSize = 200;

tokenInput.value = sessionStorage.getItem(tokenKey) || "";

let selected = null;
let allDuels = [];
let generation = 0;
let streamController = null;
let cursor = 0;
let traceCount = 0;
let refreshTimer = null;
const noteCursors = { hand: 0, spell: 0 };
let confirmedEventId = null;
const turns = new Map();
const noteRevisions = { hand: new Map(), spell: new Map() };
const noteElements = {
  hand: { text: handNoteText, meta: handNoteMeta, history: handNoteHistory },
  spell: { text: spellNoteText, meta: spellNoteMeta, history: spellNoteHistory },
};
const cardNames = new Map();
const cardIdsPending = new Set();

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = String(text);
  return element;
}

for (let sequence = 0; sequence < 5; sequence += 1) {
  const key = `main_monster_${sequence}`;
  const section = node("section", "note-current");
  section.append(node("h4", "", `主怪兽区 ${sequence + 1} 号格 · 旧版 Agent 推断`));
  const text = node("p", "note-text", "选择对局后加载。");
  const meta = node("p", "note-meta");
  const history = node("div", "note-history");
  history.append(node("p", "empty", "选择对局后加载。"));
  section.append(text, meta, history);
  byId("main-monster-notes").append(section);
  noteElements[key] = {text, meta, history};
  noteCursors[key] = 0;
  noteRevisions[key] = new Map();
}

function noteRecordKind(zone) {
  return zone.startsWith("main_monster_")
    ? `main_monster_note_revision_${zone.slice("main_monster_".length)}`
    : `${zone}_note_revision`;
}

function setNotice(message, isError = false) {
  const notice = byId("notice");
  notice.textContent = message;
  notice.classList.toggle("error", isError);
}

function setConnection(message, state = "") {
  byId("connection-text").textContent = message;
  byId("connection-dot").className = state ? `dot ${state}` : "dot";
}

function redact(value, depth = 0) {
  if (depth > 20) return "[嵌套层级过深]";
  if (Array.isArray(value)) return value.map((item) => redact(item, depth + 1));
  if (value && typeof value === "object") {
    const result = {};
    for (const [key, item] of Object.entries(value)) {
      result[key] = /(?:api[_-]?key|access[_-]?token|bearer|secret|encrypted|signature|password)/i.test(key)
        ? "[已隐藏]" : redact(item, depth + 1);
    }
    return result;
  }
  return value;
}

function pretty(value) {
  return JSON.stringify(redact(value), null, 2);
}

function query(identity = selected) {
  const params = new URLSearchParams({session_id: identity.session_id, duel_id: identity.duel_id});
  return params;
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${tokenInput.value.trim()}`);
  const response = await fetch(path, {...options, headers});
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = body.error?.message || message;
    } catch (_) { /* Non-JSON error from an unavailable service. */ }
    throw new Error(message);
  }
  return response;
}

async function json(path, options = {}) {
  return (await request(path, options)).json();
}

function selectedIdentity() {
  if (!duelSelect.value) return null;
  try {
    const [session_id, duel_id] = JSON.parse(duelSelect.value);
    return {session_id, duel_id};
  } catch (_) {
    return null;
  }
}

function timeLabel(unixMs) {
  const value = Number(unixMs);
  if (!Number.isFinite(value) || value <= 0) return "";
  return new Date(value).toLocaleTimeString("zh-CN", {hour12: false});
}

function dateTimeLabel(unixMs) {
  const value = Number(unixMs);
  if (!Number.isFinite(value) || value <= 0) return "时间未知";
  return new Date(value).toLocaleString("zh-CN", {hour12: false});
}

function noteEvidence(record) {
  const ids = record.payload?.evidence_event_ids;
  return Array.isArray(ids) && ids.length
    ? `依据事件 ${ids.map((id) => `#${id}`).join("、")}`
    : "未引用具体事件";
}

function noteMetadata(record) {
  const observed = Number(record.payload?.observed_ack_event_id);
  const parts = [dateTimeLabel(record.created_unix_ms), noteEvidence(record)];
  if (Number.isSafeInteger(observed) && observed >= 0) {
    parts.push(`写入时已观察至事件 #${observed}`);
    if (confirmedEventId !== null && confirmedEventId > observed) {
      parts.push("此说明之后已有新事件，可能需要复核");
    }
  }
  return parts.join(" · ");
}

function renderZoneNotes(zone) {
  const elements = noteElements[zone];
  const revisions = [...noteRevisions[zone].values()].sort((a, b) => Number(b.id) - Number(a.id));
  const latest = revisions[0];
  elements.text.textContent = latest ? String(latest.payload?.text ?? "") : "无历史笔记。";
  elements.meta.textContent = latest ? noteMetadata(latest) : "无历史修订记录；不表示该区域为空。";
  elements.history.replaceChildren();
  if (!latest) {
    elements.history.append(node("p", "empty", "旧版 Agent 未写入说明。"));
    return;
  }
  for (const record of revisions) {
    const details = node("details", "note-revision");
    const revision = record.record_id || record.id;
    details.append(node("summary", "", `修订 ${revision} · ${dateTimeLabel(record.created_unix_ms)}`));
    const body = node("div", "note-revision-body");
    body.append(node("p", "note-text", String(record.payload?.text ?? "")));
    body.append(node("p", "note-meta", noteMetadata(record)));
    details.append(body);
    elements.history.append(details);
  }
}

async function loadZoneNotes(epoch, zone) {
  while (selected && epoch === generation) {
    const params = query();
    params.set("kind", noteRecordKind(zone));
    params.set("after_id", String(noteCursors[zone]));
    params.set("limit", String(pageSize));
    const result = await json(`/v3/view/records?${params}`);
    if (epoch !== generation) return;
    const records = result.records || [];
    for (const record of records) {
      const id = Number(record.id);
      if (!Number.isSafeInteger(id) || id <= 0) continue;
      noteRevisions[zone].set(id, record);
      noteCursors[zone] = Math.max(noteCursors[zone], id);
    }
    renderZoneNotes(zone);
    if (records.length < pageSize) break;
  }
}

function renderDuelOptions() {
  const previous = duelSelect.value;
  const term = duelSearch.value.trim().toLocaleLowerCase();
  const duels = allDuels.filter((duel) =>
    `${duel.session_id} ${duel.duel_id}`.toLocaleLowerCase().includes(term));
  const sort = duelSort.value;
  duels.sort((a, b) => {
    const field = sort === "recent" ? "last_activity_unix_ms" : "started_unix_ms";
    const direction = sort === "oldest" ? 1 : -1;
    const delta = (Number(a[field]) - Number(b[field])) * direction;
    return delta || String(a.duel_id).localeCompare(String(b.duel_id));
  });
  duelSelect.replaceChildren();
  for (const duel of duels) {
    const status = duel.status === "finished" ? "已结束" : "结束未确认";
    const label = `始 ${dateTimeLabel(duel.started_unix_ms)} · 近 ${dateTimeLabel(duel.last_activity_unix_ms)} · ${status} · ${String(duel.duel_id).slice(0, 8)}`;
    const option = node("option", "", label);
    option.value = JSON.stringify([duel.session_id, duel.duel_id]);
    option.title = `对局 ${duel.duel_id}\n会话 ${duel.session_id}\n最近活动 ${dateTimeLabel(duel.last_activity_unix_ms)}`;
    duelSelect.append(option);
  }
  if (duels.length === 0) {
    const option = node("option", "", allDuels.length ? "没有匹配的对局" : "暂无对局");
    option.value = "";
    duelSelect.append(option);
  }
  duelSelect.disabled = duels.length === 0;
  if (duels.some((duel) => JSON.stringify([duel.session_id, duel.duel_id]) === previous)) {
    duelSelect.value = previous;
  }
  return duels.length;
}

function updateDuelOptions() {
  const shown = renderDuelOptions();
  const next = selectedIdentity();
  if (next?.session_id !== selected?.session_id || next?.duel_id !== selected?.duel_id) {
    void chooseDuel();
  }
  return shown;
}

function isProviderReasoning(kind, payload) {
  const lower = String(kind).toLowerCase();
  const source = String(payload?.source || payload?.reasoning_source || "").toLowerCase();
  return lower.includes("reasoning") || source.startsWith("provider_reasoning") ||
    (lower.includes("reason") && (source.includes("provider") || source.includes("summary")));
}

function labelForKind(kind, payload) {
  const lower = String(kind).toLowerCase();
  if (isProviderReasoning(kind, payload)) {
    const source = String(payload?.source || payload?.reasoning_source || "").toLowerCase();
    return payload?.form === "summary" || source.includes("summary") || lower.includes("summary")
      ? "供应商推理摘要" : "供应商返回的推理文本";
  }
  const known = {
    prompt_received: "游戏提示",
    model_request_started: "模型请求",
    provider_request_started: "供应商请求开始",
    provider_request_finished: "供应商请求结束",
    provider_first_text: "首段可读内容",
    model_run_timing: "模型运行耗时",
    intent_validation_timing: "动作校验耗时",
    client_query_timing: "客户端查询耗时",
    decision_timing: "决策耗时",
    model_response_started: "模型响应开始",
    model_response_finished: "模型响应结束",
    content_delta: "模型输出片段",
    model_tool_call: "模型工具调用",
    tool_started: "工具执行开始",
    tool_finished: "工具执行结果",
    output_validated: "动作校验",
    model_decision: "模型决策",
    action_issued: "动作已提交客户端",
    client_query_result: "客户端查询结果",
    action_receipt: "客户端回执",
    decision_failed: "决策失败",
    decision_interrupted: "决策中断",
    duel_finished: "对局结束",
  };
  if (known[lower]) return known[lower];
  if (lower.includes("tool") && lower.includes("result")) return "工具结果";
  if (lower.includes("tool")) return "工具调用";
  if (lower.includes("query") && lower.includes("result")) return "客户端查询结果";
  if (lower.includes("query")) return "客户端查询";
  if (lower.includes("receipt") || lower.includes("action_result")) return "客户端回执";
  if (lower.includes("valid")) return "动作校验";
  if (lower.includes("action") || lower.includes("decision") || lower.includes("intent")) return "决策动作";
  if (lower.includes("reason")) return "决策理由";
  if (lower.includes("error") || lower.includes("fail")) return "错误";
  if (lower.includes("request")) return "模型请求";
  if (lower.includes("response")) return "模型响应";
  if (lower.includes("prompt")) return "游戏提示";
  return String(kind || "事件").replaceAll("_", " ");
}

function textPreview(value) {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(redact(value));
}

function payloadPreview(kind, payload) {
  if (typeof payload !== "object" || payload === null) return textPreview(payload);
  const lower = String(kind).toLowerCase();
  if (lower === "model_request_started") {
    const effort = payload.reasoning_effort_requested ?? "由模型决定";
    const summary = payload.reasoning_summary_requested;
    return `思考强度 ${effort} · 推理摘要 ${summary ?? "未知"} · 历史消息 ${payload.history_messages ?? "未知"}`;
  }
  if (lower === "provider_request_finished") {
    const usage = payload.usage || {};
    const parts = [`耗时 ${payload.duration_ms ?? "未知"} ms`, `状态 ${payload.status || "未知"}`];
    if (payload.first_event_ms != null) parts.push(`首个事件 ${payload.first_event_ms} ms`);
    if (usage.input_count != null) parts.push(`输入 ${usage.input_count} tokens`);
    if (usage.output_count != null) parts.push(`输出 ${usage.output_count} tokens`);
    if (usage.reasoning_count != null) parts.push(`推理 ${usage.reasoning_count} tokens`);
    return parts.join(" · ");
  }
  if (lower === "provider_first_text") return `${payload.source || "内容"} · ${payload.elapsed_ms} ms`;
  if (lower.endsWith("_timing")) return `耗时 ${payload.duration_ms ?? "未知"} ms`;
  const keys = isProviderReasoning(kind, payload)
    ? ["text", "summary", "reasoning", "content"]
    : lower.includes("error") || lower.includes("fail")
      ? ["message", "error", "reason"]
      : ["summary", "text", "reason", "message", "name", "tool_name", "intent", "action", "result", "status"];
  for (const key of keys) {
    if (payload[key] !== undefined && payload[key] !== null && payload[key] !== "") {
      return textPreview(payload[key]);
    }
  }
  return "点击展开原始记录";
}

function cardIdsIn(value, key = "", found = new Set(), depth = 0) {
  if (depth > 8 || found.size >= 100) return found;
  if (Array.isArray(value)) {
    for (const item of value) cardIdsIn(item, key, found, depth + 1);
  } else if (value && typeof value === "object") {
    for (const [childKey, item] of Object.entries(value)) cardIdsIn(item, childKey, found, depth + 1);
  } else if (/^(?:card_id|card_ids|card_code|card_codes|code)$/i.test(key)) {
    const id = Number(value);
    if (Number.isSafeInteger(id) && id > 0) found.add(id);
  }
  return found;
}

function addCardNames(summary, payload) {
  const names = [...cardIdsIn(payload)].filter((id) => cardNames.has(id));
  if (names.length === 0) return summary;
  return `${summary}\n卡片：${names.map((id) => `${cardNames.get(id)}（${id}）`).join("、")}`;
}

async function loadCardNames() {
  if (!selected || cardIdsPending.size === 0) return;
  const epoch = generation;
  const ids = [...cardIdsPending].slice(0, 100);
  for (const id of ids) cardIdsPending.delete(id);
  try {
    const result = await json(`/v3/view/cards?ids=${encodeURIComponent(ids.join(","))}`);
    if (epoch !== generation) return;
    for (const [rawId, name] of Object.entries(result.cards || {})) {
      if (typeof name === "string") cardNames.set(Number(rawId), name);
    }
    for (const row of timeline.querySelectorAll(".trace")) {
      const data = row._traceData;
      if (data) row.querySelector(".trace-summary").textContent = addCardNames(data.preview, data.payload);
    }
    if (cardIdsPending.size > 0) void loadCardNames();
  } catch (_) { /* Card names are display-only; IDs remain available. */ }
}

function rawDetails(data) {
  const details = node("details", "raw");
  details.append(node("summary", "", "原始记录"), node("pre", "", pretty(data)));
  return details;
}

function ensureTurn(trace) {
  const id = String(trace.turn_id ?? `ungrouped-${trace.id}`);
  let turn = turns.get(id);
  if (turn) return turn;
  const root = node("article", "turn");
  const header = node("div", "turn-header");
  const titleBox = node("div");
  titleBox.append(node("h3", "", trace.turn_id ? `游戏提示 · ${id}` : "未分组事件"));
  const status = node("p", "turn-status", "等待端点推理内容");
  const metrics = node("p", "turn-metrics", "");
  titleBox.append(status, metrics);
  header.append(titleBox, node("small", "", timeLabel(trace.created_unix_ms)));
  const body = node("div", "turn-body");
  root.append(header, body);
  timeline.append(root);
  turn = {root, body, status, metrics, requests: [], responses: new Map(), hasReasoning: false, complete: false, summaryRequested: true};
  turns.set(id, turn);
  return turn;
}

function ensureResponse(turn, responseId) {
  const id = String(responseId);
  let response = turn.responses.get(id);
  if (response) return response;
  const root = node("details", "response");
  root.open = true;
  const ordinal = turn.responses.size + 1;
  const summary = node("summary", "", `模型响应 ${ordinal}`);
  const body = node("div", "response-body");
  const status = node("div", "response-status", "等待端点推理内容");
  body.append(status);
  root.append(summary, body);
  turn.body.append(root);
  response = {root, summary, body, status, hasReasoning: false, complete: false};
  turn.responses.set(id, response);
  return response;
}

function renderTrace(trace) {
  const turn = ensureTurn(trace);
  const kind = String(trace.kind || "event");
  const lower = kind.toLowerCase();
  const payload = trace.payload ?? {};
  if (lower === "model_request_started" && payload.reasoning_summary_requested === "off") {
    turn.summaryRequested = false;
  }
  if (lower === "provider_request_finished") {
    turn.requests.push(Number(payload.duration_ms) || 0);
  }
  if (["action_issued", "decision_failed", "decision_interrupted"].includes(lower)) {
    const total = Number(payload.duration_ms);
    const slowest = turn.requests.length ? Math.max(...turn.requests) : null;
    const parts = [];
    if (typeof payload.duration_ms === "number" && Number.isFinite(total)) {
      parts.push(`总耗时 ${total.toFixed(0)} ms`);
    }
    if (slowest !== null) parts.push(`最慢模型请求 ${slowest.toFixed(0)} ms`);
    if (turn.requests.length) parts.push(`请求 ${turn.requests.length} 次`);
    turn.metrics.textContent = parts.join(" · ");
  }
  const response = trace.response_id == null || trace.response_id === ""
    ? null : ensureResponse(turn, trace.response_id);
  const target = response?.body || turn.body;
  const row = node("div", "trace");
  const heading = node("div", "trace-heading");
  const kindLabel = node("span", "trace-kind", labelForKind(kind, payload));
  if (isProviderReasoning(kind, payload)) kindLabel.classList.add("reasoning");
  if (lower.includes("error") || lower.includes("fail") || lower.includes("interrupt")) kindLabel.classList.add("error");
  if (lower.includes("action") || lower.includes("decision")) kindLabel.classList.add("action");
  heading.append(kindLabel);
  if (isProviderReasoning(kind, payload)) {
    const source = payload && typeof payload === "object" ? payload.source || payload.reasoning_source : "";
    if (source) heading.append(node("span", "trace-source", `来源：${source}${payload.form ? ` · ${payload.form}` : ""}`));
  }
  heading.append(node("span", "trace-time", timeLabel(trace.created_unix_ms)));
  const preview = payloadPreview(kind, payload);
  const summary = node("p", "trace-summary", addCardNames(preview, payload));
  row._traceData = {preview, payload};
  row.append(heading, summary, rawDetails(trace));
  target.append(row);

  for (const id of cardIdsIn(payload)) {
    if (!cardNames.has(id)) cardIdsPending.add(id);
  }
  if (isProviderReasoning(kind, payload)) {
    turn.hasReasoning = true;
    turn.status.textContent = "已收到供应商推理内容";
    if (response) {
      response.hasReasoning = true;
      response.status.textContent = "已收到供应商推理内容";
    }
  }
  if (lower === "model_response_finished" && response) {
    response.complete = true;
    if (!response.hasReasoning) response.status.textContent = turn.summaryRequested
      ? "该端点未提供推理内容" : "未请求推理摘要，且未收到推理文本";
  }
  if (["model_decision", "action_issued", "action_receipt", "decision_failed", "decision_interrupted", "duel_finished"].includes(lower)) {
    turn.complete = true;
    if (!turn.hasReasoning) turn.status.textContent = turn.summaryRequested
      ? "该端点未提供推理内容" : "未请求推理摘要，且未收到推理文本";
    if (response) {
      response.complete = true;
      if (!response.hasReasoning) response.status.textContent = turn.summaryRequested
        ? "该端点未提供推理内容" : "未请求推理摘要，且未收到推理文本";
      if ((lower === "model_decision" || lower === "action_issued") &&
          !response.summary.textContent.includes("已输出动作")) {
        response.summary.textContent += " · 已输出动作";
      }
    }
  }
}

function appendTraces(traces) {
  if (!Array.isArray(traces) || traces.length === 0) return;
  if (traceCount === 0) timeline.replaceChildren();
  for (const trace of traces) {
    const id = Number(trace.id);
    if (!Number.isSafeInteger(id) || id <= cursor) continue;
    renderTrace(trace);
    cursor = id;
    traceCount += 1;
  }
  byId("trace-count").textContent = `${traceCount} 条记录`;
  if (cardIdsPending.size > 0) void loadCardNames();
}

async function backfill(epoch) {
  while (selected && epoch === generation) {
    const params = query();
    params.set("after_id", String(cursor));
    params.set("limit", String(pageSize));
    const result = await json(`/v3/view/timeline?${params}`);
    const traces = result.traces || [];
    const previous = cursor;
    appendTraces(traces);
    if (traces.length < pageSize || cursor === previous) break;
  }
}

function processSseBlock(block) {
  let data = "";
  let eventId = null;
  for (const line of block.split("\n")) {
    if (line.startsWith("data:")) data += `${line.slice(5).trimStart()}\n`;
    else if (line.startsWith("id:")) eventId = Number(line.slice(3).trim());
  }
  if (!data) return;
  let parsed;
  try { parsed = JSON.parse(data.trimEnd()); } catch (_) { return; }
  const traces = Array.isArray(parsed) ? parsed : Array.isArray(parsed.traces) ? parsed.traces : [parsed.trace || parsed];
  if (eventId && traces.length === 1 && traces[0] && traces[0].id == null) traces[0].id = eventId;
  appendTraces(traces);
  scheduleSecondaryRefresh();
}

function scheduleSecondaryRefresh() {
  if (refreshTimer !== null) return;
  refreshTimer = setTimeout(() => {
    refreshTimer = null;
    void refreshSecondary().catch((error) => setNotice(error.message, true));
  }, 1200);
}

async function stream(epoch) {
  let retryMs = 500;
  while (selected && epoch === generation) {
    try {
      await backfill(epoch);
      if (epoch !== generation) return;
      streamController = new AbortController();
      const params = query();
      params.set("after_id", String(cursor));
      const response = await request(`/v3/view/stream?${params}`, {
        headers: {Accept: "text/event-stream"}, signal: streamController.signal,
      });
      if (!response.body) throw new Error("浏览器不支持流式读取");
      setConnection("实时连接中", "live");
      retryMs = 500;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (epoch === generation) {
        const {value, done} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true}).replaceAll("\r\n", "\n");
        let boundary;
        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
          processSseBlock(buffer.slice(0, boundary));
          buffer = buffer.slice(boundary + 2);
        }
      }
    } catch (error) {
      if (epoch !== generation || error.name === "AbortError") return;
      setConnection("连接中断，正在重连", "wait");
      setNotice(`实时流暂不可用：${error.message}`, true);
    } finally {
      streamController = null;
    }
    if (epoch !== generation) return;
    await new Promise((resolve) => setTimeout(resolve, retryMs));
    retryMs = Math.min(retryMs * 2, 10000);
  }
}

async function refreshSecondary() {
  if (!selected) return;
  const epoch = generation;
  const params = query();
  const zones = Object.keys(noteElements);
  const [state, events, records, ...notes] = await Promise.allSettled([
    json(`/v3/view/state?${params}`),
    json(`/v3/view/events?${params}&limit=100`),
    json(`/v3/view/records?${params}&limit=100`),
    ...zones.map((zone) => loadZoneNotes(epoch, zone)),
  ]);
  if (epoch !== generation) return;
  if (state.status === "fulfilled") {
    confirmedEventId = Number(state.value.ack_event_id);
    stateJson.textContent = pretty(state.value.observation);
    const updated = state.value.updated_unix_ms ? ` · 更新于 ${timeLabel(state.value.updated_unix_ms)}` : "";
    byId("state-meta").textContent = `快照版本 ${state.value.state_version} · 已确认事件 ${state.value.ack_event_id}${updated}`;
  } else {
    confirmedEventId = null;
    stateJson.textContent = `暂无已确认快照：${state.reason.message}`;
  }
  eventsJson.textContent = events.status === "fulfilled" ? pretty(events.value.events) : `加载失败：${events.reason.message}`;
  recordsJson.textContent = records.status === "fulfilled" ? pretty(records.value.records) : `加载失败：${records.reason.message}`;
  zones.forEach((zone, index) => {
    if (notes[index].status === "rejected") {
      noteElements[zone].meta.textContent = `说明加载失败：${notes[index].reason.message}`;
    } else {
      renderZoneNotes(zone);
    }
  });
}

function stopStream() {
  generation += 1;
  if (streamController) streamController.abort();
  streamController = null;
  if (refreshTimer !== null) clearTimeout(refreshTimer);
  refreshTimer = null;
}

async function chooseDuel() {
  stopStream();
  selected = selectedIdentity();
  const hasDuel = Boolean(selected);
  for (const id of ["refresh", "export"]) byId(id).disabled = !hasDuel;
  timeline.replaceChildren(node("p", "empty", hasDuel ? "正在加载时间线…" : "请选择对局。"));
  stateJson.textContent = "正在加载…";
  eventsJson.textContent = "正在加载…";
  recordsJson.textContent = "正在加载…";
  for (const elements of Object.values(noteElements)) {
    elements.text.textContent = "正在加载…";
    elements.meta.textContent = "";
    elements.history.replaceChildren(node("p", "empty", "正在加载修订历史…"));
  }
  byId("state-meta").textContent = "";
  byId("trace-count").textContent = "0 条记录";
  turns.clear();
  cardNames.clear();
  cardIdsPending.clear();
  cursor = 0;
  traceCount = 0;
  for (const zone of Object.keys(noteElements)) {
    noteCursors[zone] = 0;
    noteRevisions[zone].clear();
  }
  confirmedEventId = null;
  if (!hasDuel) { setConnection("尚未选择对局"); return; }
  setConnection("加载历史中", "wait");
  const epoch = generation;
  try {
    await Promise.all([backfill(epoch), refreshSecondary()]);
    if (epoch !== generation) return;
    if (traceCount === 0) timeline.replaceChildren(node("p", "empty", "暂无决策记录。"));
    setNotice("历史已加载，正在连接实时事件。", false);
    void stream(epoch);
  } catch (error) {
    if (epoch !== generation) return;
    setConnection("加载失败", "error");
    setNotice(error.message, true);
  }
}

async function loadDuels() {
  stopStream();
  tokenInput.value = tokenInput.value.trim();
  if (!tokenInput.value) { setNotice("请先填写只读令牌。", true); return; }
  sessionStorage.setItem(tokenKey, tokenInput.value);
  setConnection("正在加载", "wait");
  try {
    const list = await json("/v3/view/duels");
    allDuels = list.duels || [];
    duelSearch.disabled = allDuels.length === 0;
    duelSort.disabled = allDuels.length === 0;
    const shown = renderDuelOptions();
    setNotice(`${allDuels.length} 场对局已加载，当前显示 ${shown} 场。`);
    await chooseDuel();
  } catch (error) {
    setConnection("连接失败", "error");
    setNotice(error.message, true);
  }
}

async function exportDuel() {
  if (!selected) return;
  try {
    const response = await request(`/v3/view/export?${query()}`);
    const blob = await response.blob();
    const link = node("a");
    link.href = URL.createObjectURL(blob);
    link.download = `agent-duel-${selected.duel_id.replace(/[^a-zA-Z0-9_-]/g, "_")}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  } catch (error) { setNotice(`导出失败：${error.message}`, true); }
}

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => {
    for (const item of document.querySelectorAll(".tab")) {
      const active = item === tab;
      item.classList.toggle("active", active);
      item.setAttribute("aria-selected", String(active));
      byId(`tab-${item.dataset.tab}`).hidden = !active;
    }
  });
}

byId("load").addEventListener("click", () => void loadDuels());
duelSelect.addEventListener("change", () => void chooseDuel());
duelSearch.addEventListener("input", () => {
  const shown = updateDuelOptions();
  setNotice(`当前显示 ${shown} / ${allDuels.length} 场对局。`);
});
duelSort.addEventListener("change", () => {
  updateDuelOptions();
});
byId("refresh").addEventListener("click", () => {
  const epoch = generation;
  void Promise.all([backfill(epoch), refreshSecondary()]).then(() => setNotice("已刷新。"))
    .catch((error) => setNotice(error.message, true));
});
byId("export").addEventListener("click", () => void exportDuel());
tokenInput.addEventListener("keydown", (event) => { if (event.key === "Enter") void loadDuels(); });
let tokenLoadTimer = null;
tokenInput.addEventListener("input", () => {
  if (tokenLoadTimer !== null) clearTimeout(tokenLoadTimer);
  if (tokenInput.value.trim().length >= 32) {
    tokenLoadTimer = setTimeout(() => { tokenLoadTimer = null; void loadDuels(); }, 250);
  }
});

if (tokenInput.value) void loadDuels();

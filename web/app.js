"use strict";

let review = null;
let currentIndex = 0;
let context = null;
let drag = null;
let saveTimer = null;

const byId = id => document.getElementById(id);
const listEl = byId("candidateList");
const imageEl = byId("contextImage");
const stageEl = byId("imageStage");
const rectEl = byId("candidateRect");
const boundaryLayer = byId("sourceBoundaryLayer");
const scroller = byId("previewScroller");

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const error = new Error(await response.text());
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function current() { return review.items[currentIndex]; }
function statusLabel(status) { return status === "approved" ? "通过" : status === "rejected" ? "驳回" : "待审"; }

function updateCounts() {
  const counts = {pending: 0, approved: 0, rejected: 0};
  review.items.forEach(item => { counts[item.review_status] += 1; });
  byId("counts").textContent = `已审核 ${counts.approved + counts.rejected} · 待审核 ${counts.pending} · 总数 ${review.items.length} · 通过 ${counts.approved} · 驳回 ${counts.rejected}`;
}

function renderList() {
  const q = byId("filterInput").value.trim().toLowerCase();
  listEl.textContent = "";
  review.items.forEach((item, index) => {
    const haystack = `${item.provisional_id} ${item.panel_type} ${item.review_status}`.toLowerCase();
    if (q && !haystack.includes(q)) return;
    const li = document.createElement("li");
    if (index === currentIndex) li.classList.add("current");

    const number = document.createElement("span");
    number.textContent = String(index + 1);
    const details = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = item.provisional_id;
    const type = document.createElement("span");
    type.className = "item-type";
    type.textContent = item.panel_type;
    details.append(name, document.createElement("br"), type);
    const status = document.createElement("span");
    status.title = statusLabel(item.review_status);
    status.className = `status-dot ${item.review_status}`;
    li.append(number, details, status);
    li.addEventListener("click", () => selectIndex(index));
    listEl.appendChild(li);
  });
  listEl.querySelector("li.current")?.scrollIntoView({block: "nearest"});
  updateCounts();
}

function renderMetadata() {
  const item = current();
  byId("candidateTitle").textContent = `${item.provisional_id} · 顺序 ${currentIndex + 1}/${review.items.length} · ${statusLabel(item.review_status)}`;
  byId("crossBadge").classList.toggle("hidden", !item.cross_source);
  byId("typeSelect").value = item.panel_type;
  byId("noteInput").value = item.reviewer_note || "";
  byId("splitY").value = Math.floor((item.global_y0 + item.global_y1) / 2);
  byId("coordinateText").textContent = `x=[${item.x0},${item.x1})  y=[${item.global_y0},${item.global_y1})  ${item.width}×${item.height}`;
  byId("sourceText").textContent = item.source_files.length ? `来源：${item.source_files.join("、")}` : "未配置来源分段";
  byId("prevBtn").disabled = currentIndex === 0;
  byId("mergePrevBtn").disabled = currentIndex === 0;
  byId("nextBtn").disabled = currentIndex >= review.items.length - 1;
  byId("mergeNextBtn").disabled = currentIndex >= review.items.length - 1;
}

async function loadContext() {
  const item = current();
  context = await api(`/api/context?y0=${item.global_y0}&y1=${item.global_y1}`);
  await new Promise((resolve, reject) => {
    imageEl.onload = resolve;
    imageEl.onerror = reject;
    imageEl.src = `${context.url}&v=${Date.now()}`;
  });
  stageEl.style.width = `${imageEl.naturalWidth}px`;
  renderOverlay();
  scroller.scrollTop = Math.max(0, item.global_y0 - context.global_y0 - 100);
}

function renderBoundaries() {
  boundaryLayer.textContent = "";
  const scaleY = imageEl.clientHeight / (context.global_y1 - context.global_y0);
  review.source_boundaries.forEach(boundary => {
    if (boundary.global_y <= context.global_y0 || boundary.global_y >= context.global_y1) return;
    const line = document.createElement("div");
    line.className = "source-boundary";
    line.style.top = `${(boundary.global_y - context.global_y0) * scaleY}px`;
    const label = document.createElement("span");
    label.textContent = `来源接缝 Y=${boundary.global_y} · ${boundary.before} / ${boundary.after}`;
    line.appendChild(label);
    boundaryLayer.appendChild(line);
  });
}

function renderOverlay() {
  if (!context || !imageEl.naturalWidth) return;
  const item = current();
  const scaleX = imageEl.clientWidth / review.stream_width;
  const scaleY = imageEl.clientHeight / (context.global_y1 - context.global_y0);
  rectEl.style.left = `${item.x0 * scaleX}px`;
  rectEl.style.width = `${(item.x1 - item.x0) * scaleX}px`;
  rectEl.style.top = `${(item.global_y0 - context.global_y0) * scaleY}px`;
  rectEl.style.height = `${(item.global_y1 - item.global_y0) * scaleY}px`;
  renderBoundaries();
  renderMetadata();
}

async function selectIndex(index) {
  currentIndex = Math.max(0, Math.min(index, review.items.length - 1));
  review.current_index = currentIndex;
  renderList();
  renderMetadata();
  await loadContext();
  queueSave();
}

function queueSave(immediate = false) {
  clearTimeout(saveTimer);
  byId("saveState").textContent = "正在自动保存…";
  saveTimer = setTimeout(saveReview, immediate ? 0 : 350);
}

async function saveReview() {
  try {
    review = await api("/api/state", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(review),
    });
    currentIndex = Math.min(review.current_index || 0, review.items.length - 1);
    byId("saveState").textContent = `已自动保存 ${new Date().toLocaleTimeString()}`;
    renderList();
    renderMetadata();
  } catch (error) {
    byId("saveState").textContent = error.status === 409
      ? "保存冲突：其他窗口已更新，请刷新后重做当前修改"
      : `保存失败：${error.message}`;
  }
}

function setStatus(status) {
  current().review_status = status;
  renderList();
  renderMetadata();
  queueSave(true);
}

function splitCurrent() {
  const item = current();
  const splitY = Number(byId("splitY").value);
  if (!Number.isInteger(splitY) || splitY <= item.global_y0 || splitY >= item.global_y1) {
    alert(`拆分坐标必须严格位于 (${item.global_y0}, ${item.global_y1}) 内。`);
    return;
  }
  const base = item.provisional_id.replace(/[^a-zA-Z0-9_-]/g, "_");
  const first = {...item, provisional_id: `${base}_a`, global_y1: splitY, review_status: "pending", reviewer_note: `人工拆分自 ${item.provisional_id}`};
  const second = {...item, provisional_id: `${base}_b`, global_y0: splitY, review_status: "pending", reviewer_note: `人工拆分自 ${item.provisional_id}`};
  review.items.splice(currentIndex, 1, first, second);
  renderList();
  renderMetadata();
  loadContext();
  queueSave(true);
}

function mergeWith(index) {
  if (index < 0 || index >= review.items.length || index === currentIndex) return;
  const firstIndex = Math.min(index, currentIndex);
  const secondIndex = Math.max(index, currentIndex);
  const first = review.items[firstIndex];
  const second = review.items[secondIndex];
  const merged = {
    ...first,
    provisional_id: `${first.provisional_id}_plus_${second.provisional_id}`,
    x0: Math.min(first.x0, second.x0),
    x1: Math.max(first.x1, second.x1),
    global_y0: Math.min(first.global_y0, second.global_y0),
    global_y1: Math.max(first.global_y1, second.global_y1),
    panel_type: first.panel_type === second.panel_type ? first.panel_type : review.panel_types[0],
    review_status: "pending",
    reviewer_note: `人工合并 ${first.provisional_id} 与 ${second.provisional_id}`,
  };
  review.items.splice(firstIndex, 2, merged);
  currentIndex = firstIndex;
  review.current_index = currentIndex;
  renderList();
  renderMetadata();
  loadContext();
  queueSave(true);
}

function beginDrag(event) {
  event.preventDefault();
  drag = {edge: event.currentTarget.dataset.edge, pointerId: event.pointerId};
  event.currentTarget.setPointerCapture(event.pointerId);
}

function dragMove(event) {
  if (!drag) return;
  const bounds = imageEl.getBoundingClientRect();
  const item = current();
  if (drag.edge === "left" || drag.edge === "right") {
    const x = Math.round((event.clientX - bounds.left) / bounds.width * review.stream_width);
    if (drag.edge === "left") item.x0 = Math.max(0, Math.min(x, item.x1 - 1));
    else item.x1 = Math.min(review.stream_width, Math.max(x, item.x0 + 1));
  } else {
    const y = Math.round(context.global_y0 + (event.clientY - bounds.top) / bounds.height * (context.global_y1 - context.global_y0));
    if (drag.edge === "top") item.global_y0 = Math.max(0, Math.min(y, item.global_y1 - 1));
    else item.global_y1 = Math.min(review.stream_height, Math.max(y, item.global_y0 + 1));
  }
  item.review_status = "pending";
  item.width = item.x1 - item.x0;
  item.height = item.global_y1 - item.global_y0;
  renderOverlay();
}

function endDrag() {
  if (!drag) return;
  drag = null;
  renderList();
  loadContext();
  queueSave(true);
}

function bindEvents() {
  byId("prevBtn").onclick = () => selectIndex(currentIndex - 1);
  byId("nextBtn").onclick = () => selectIndex(currentIndex + 1);
  byId("approveBtn").onclick = () => setStatus("approved");
  byId("rejectBtn").onclick = () => setStatus("rejected");
  byId("pendingBtn").onclick = () => setStatus("pending");
  byId("splitBtn").onclick = splitCurrent;
  byId("mergePrevBtn").onclick = () => mergeWith(currentIndex - 1);
  byId("mergeNextBtn").onclick = () => mergeWith(currentIndex + 1);
  byId("filterInput").oninput = renderList;
  byId("typeSelect").onchange = event => { current().panel_type = event.target.value; current().review_status = "pending"; renderList(); queueSave(true); };
  byId("noteInput").oninput = event => { current().reviewer_note = event.target.value; queueSave(false); };
  document.querySelectorAll(".handle").forEach(handle => {
    handle.addEventListener("pointerdown", beginDrag);
    handle.addEventListener("pointermove", dragMove);
    handle.addEventListener("pointerup", endDrag);
    handle.addEventListener("pointercancel", endDrag);
  });
  window.addEventListener("resize", renderOverlay);
  window.addEventListener("keydown", event => {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
    const key = event.key.toLowerCase();
    if (event.key === "ArrowLeft" || key === "j") selectIndex(currentIndex - 1);
    else if (event.key === "ArrowRight" || key === "k") selectIndex(currentIndex + 1);
    else if (key === "a") setStatus("approved");
    else if (key === "r") setStatus("rejected");
    else if (key === "p") setStatus("pending");
    else if (key === "s") splitCurrent();
    else if (key === "m") mergeWith(currentIndex + 1);
  });
}

async function boot() {
  review = await api("/api/state");
  if (!review.items.length) throw new Error("候选列表为空");
  document.title = `${review.dataset_title} · 画格坐标审核`;
  byId("datasetTitle").textContent = review.dataset_title;
  const typeSelect = byId("typeSelect");
  review.panel_types.forEach(panelType => {
    const option = document.createElement("option");
    option.value = panelType;
    option.textContent = panelType;
    typeSelect.appendChild(option);
  });
  currentIndex = Math.min(review.current_index || 0, review.items.length - 1);
  bindEvents();
  renderList();
  renderMetadata();
  await loadContext();
}

boot().catch(error => {
  const fatal = document.createElement("pre");
  fatal.className = "fatal";
  fatal.textContent = `审核工具启动失败：${error.stack || error.message}`;
  document.body.replaceChildren(fatal);
});

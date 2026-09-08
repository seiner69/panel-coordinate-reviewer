"use strict";

const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function harness() {
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {value: "", style: {}, classList: {toggle() {}}, disabled: false});
    return nodes.get(id);
  };
  const listeners = {};
  const sandbox = {
    document: {getElementById: node, querySelectorAll: () => [], activeElement: {tagName: "BODY"}},
    window: {addEventListener: (name, fn) => { listeners[name] = fn; }},
    // Leave boot suspended; this unit test performs no network or browser work.
    fetch: () => new Promise(() => {}),
    setTimeout: () => { throw new Error("locked action attempted a save"); },
    clearTimeout() {},
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../web/app.js"), "utf8"), sandbox);
  const item = (id, y) => ({provisional_id: id, x0: 10, x1: 90, global_y0: y, global_y1: y + 20,
    panel_type: "single", review_status: "approved", reviewer_note: "", source_files: [], width: 80, height: 20});
  sandbox.fixture = {items: [item("locked", 20), item("editable", 80)], locked_panel_ids: ["locked"]};
  const run = code => vm.runInContext(code, sandbox);
  run("review = fixture; currentIndex = 0; bindEvents();");
  return {run, nodes, listeners, sandbox};
}

test("locked item disables controls but keeps navigation available", () => {
  const h = harness();
  h.run("renderMetadata();");
  for (const id of ["typeSelect", "noteInput", "splitBtn", "approveBtn", "mergeNextBtn"]) {
    assert.equal(h.nodes.get(id).disabled, true, id);
  }
  assert.equal(h.nodes.get("nextBtn").disabled, false);
  assert.match(h.nodes.get("candidateTitle").textContent, /只读/);
  assert.equal(h.nodes.get("candidateRect").style.pointerEvents, "none");
});

test("keyboard, direct mutators, drag and input callbacks cannot edit locked item", () => {
  const h = harness();
  const before = JSON.stringify(h.sandbox.fixture);
  h.run("setStatus('pending'); splitCurrent(); mergeWith(1); beginDrag({}); dragMove({});");
  h.nodes.get("typeSelect").onchange({target: {value: "other"}});
  h.nodes.get("noteInput").oninput({target: {value: "changed"}});
  for (const key of ["a", "r", "p", "s", "m"]) h.listeners.keydown({key});
  assert.equal(JSON.stringify(h.sandbox.fixture), before);
});

test("editable neighbor cannot merge into a locked item", () => {
  const h = harness();
  h.run("currentIndex = 1; renderMetadata();");
  assert.equal(h.nodes.get("mergePrevBtn").disabled, true);
  assert.equal(h.nodes.get("noteInput").disabled, false);
  const before = JSON.stringify(h.sandbox.fixture);
  h.run("mergeWith(0);");
  assert.equal(JSON.stringify(h.sandbox.fixture), before);
});

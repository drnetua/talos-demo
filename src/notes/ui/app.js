"use strict";

const shown = new Set();
let cursor = null;
let loading = false;

const messageEl = document.getElementById("message");
const listEl = document.getElementById("notes");
const moreEl = document.getElementById("load-more");

function renderNotes(note) {
  const li = document.createElement("li");
  li.className = "note";
  li.dataset.id = String(note.id);
  const title = document.createElement("h2");
  title.className = "note-title";
  title.textContent = note.title;
  const body = document.createElement("p");
  body.className = "note-body";
  body.textContent = note.body;
  const tags = document.createElement("div");
  tags.className = "note-tags";
  for (const tag of note.tags) {
    const chip = document.createElement("span");
    chip.className = "tag";
    chip.textContent = tag;
    tags.appendChild(chip);
  }
  li.append(title, body, tags);
  return li;
}

function appendNotes(items) {
  for (const note of items) {
    if (shown.has(note.id)) continue;
    shown.add(note.id);
    listEl.appendChild(renderNotes(note));
  }
}

function updateLoadMore() {
  moreEl.hidden = typeof cursor !== "string";
  moreEl.disabled = loading;
}

async function loadPage() {
  if (loading) return;
  loading = true;
  updateLoadMore();
  try {
    const url = cursor === null ? "/notes" : "/notes?cursor=" + encodeURIComponent(cursor);
    const response = await fetch(url);
    if (!response.ok) throw new Error("request failed");
    const page = await response.json();
    appendNotes(page.items);
    cursor = page.next_cursor;
    messageEl.textContent = shown.size === 0 ? "No notes yet" : "";
  } catch (err) {
    messageEl.textContent = "The service is unavailable";
  } finally {
    loading = false;
    updateLoadMore();
  }
}

moreEl.addEventListener("click", loadPage);
loadPage();

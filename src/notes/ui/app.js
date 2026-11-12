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

function parseTags(text) {
  return text.split(",").map((tag) => tag.trim()).filter((tag) => tag !== "");
}

const formEl = document.getElementById("create-form");
const titleEl = document.getElementById("note-title");
const bodyEl = document.getElementById("note-body");
const tagsEl = document.getElementById("note-tags");
const saveEl = document.getElementById("save");
const formMessageEl = document.getElementById("form-message");

async function createNote(event) {
  event.preventDefault();
  const title = titleEl.value.trim();
  if (title === "") {
    formMessageEl.textContent = "Please enter a title.";
    return;
  }
  saveEl.disabled = true;
  formMessageEl.textContent = "";
  try {
    const response = await fetch("/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, body: bodyEl.value, tags: parseTags(tagsEl.value) }),
    });
    if (response.status === 201) {
      appendNotes([await response.json()]);
      formEl.reset();
      messageEl.textContent = "";
    } else if (response.status === 422) {
      formMessageEl.textContent = "Please enter a title of at most 200 characters.";
    } else {
      formMessageEl.textContent = "The action did not succeed.";
    }
  } catch (err) {
    formMessageEl.textContent = "The action did not succeed.";
  } finally {
    saveEl.disabled = false;
  }
}

formEl.addEventListener("submit", createNote);
moreEl.addEventListener("click", loadPage);
loadPage();

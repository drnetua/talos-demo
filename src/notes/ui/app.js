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
  const edit = document.createElement("button");
  edit.type = "button";
  edit.className = "edit-note";
  edit.textContent = "Edit";
  edit.addEventListener("click", () => requestLeave(() => openNote(note.id)));
  li.append(title, body, tags, edit);
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

const editFormEl = document.getElementById("edit-form");
const editTitleEl = document.getElementById("edit-title");
const editBodyEl = document.getElementById("edit-body");
const editTagsEl = document.getElementById("edit-tags");
const editSaveEl = document.getElementById("edit-save");
const editMessageEl = document.getElementById("edit-message");
const discardEl = document.getElementById("discard-confirm");
let editingId = null;
let baseline = null;
let pendingAction = null;

function rowOf(id) {
  return listEl.querySelector('li[data-id="' + id + '"]');
}

function removeRow(id) {
  const row = rowOf(id);
  if (row) row.remove();
  shown.delete(id);
  if (shown.size === 0 && messageEl.textContent === "") messageEl.textContent = "No notes yet";
}

function isDirty() {
  if (editingId === null || baseline === null) return false;
  return (
    editTitleEl.value !== baseline.title ||
    editBodyEl.value !== baseline.body ||
    JSON.stringify(parseTags(editTagsEl.value)) !== JSON.stringify(baseline.tags)
  );
}

function requestLeave(action) {
  if (!isDirty()) {
    action();
    return;
  }
  pendingAction = action;
  discardEl.hidden = false;
}

function keepEditing() {
  pendingAction = null;
  discardEl.hidden = true;
  editTitleEl.focus();
}

function discardEdits() {
  const action = pendingAction;
  pendingAction = null;
  discardEl.hidden = true;
  if (action) action();
}

function closeEdit() {
  discardEl.hidden = true;
  pendingAction = null;
  baseline = null;
  editFormEl.hidden = true;
  editFormEl.reset();
  editMessageEl.textContent = "";
  editingId = null;
}

async function openNote(id) {
  try {
    const response = await fetch("/notes/" + id);
    if (response.status === 404) {
      closeEdit();
      removeRow(id);
      messageEl.textContent = "This note no longer exists";
      return;
    }
    if (!response.ok) throw new Error("request failed");
    const note = await response.json();
    editingId = note.id;
    editTitleEl.value = note.title;
    editBodyEl.value = note.body;
    editTagsEl.value = note.tags.join(", ");
    editMessageEl.textContent = "";
    baseline = { title: note.title, body: note.body, tags: parseTags(editTagsEl.value) };
    discardEl.hidden = true;
    pendingAction = null;
    editFormEl.hidden = false;
    editTitleEl.focus();
  } catch (err) {
    messageEl.textContent = "The action did not succeed.";
  }
}

async function saveEdit(event) {
  event.preventDefault();
  if (editingId === null) return;
  const id = editingId;
  const title = editTitleEl.value.trim();
  if (title === "") {
    editMessageEl.textContent = "Please enter a title.";
    return;
  }
  editSaveEl.disabled = true;
  editMessageEl.textContent = "";
  try {
    const response = await fetch("/notes/" + id, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, body: editBodyEl.value, tags: parseTags(editTagsEl.value) }),
    });
    if (response.status === 200) {
      const note = await response.json();
      const row = rowOf(id);
      if (row) row.replaceWith(renderNotes(note));
      closeEdit();
    } else if (response.status === 404) {
      closeEdit();
      removeRow(id);
      messageEl.textContent = "This note no longer exists";
    } else if (response.status === 422) {
      editMessageEl.textContent = "Please enter a title of at most 200 characters.";
    } else {
      editMessageEl.textContent = "The action did not succeed.";
    }
  } catch (err) {
    editMessageEl.textContent = "The action did not succeed.";
  } finally {
    editSaveEl.disabled = false;
  }
}

formEl.addEventListener("submit", createNote);
editFormEl.addEventListener("submit", saveEdit);
document.getElementById("edit-close").addEventListener("click", () => requestLeave(closeEdit));
document.getElementById("keep-editing").addEventListener("click", keepEditing);
document.getElementById("discard-edits").addEventListener("click", discardEdits);
window.addEventListener("beforeunload", (event) => {
  if (isDirty()) {
    event.preventDefault();
    event.returnValue = "";
  }
});
moreEl.addEventListener("click", loadPage);
loadPage();

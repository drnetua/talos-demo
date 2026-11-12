"use strict";

const shown = new Set();
let cursor = null;
let loading = false;
let activeTag = null;
let generation = 0;

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
    chip.append(tag);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-tag";
    remove.setAttribute("aria-label", "Remove tag " + tag);
    remove.addEventListener("click", () =>
      changeTags(note.id, (list) => list.filter((item) => item !== tag)),
    );
    chip.appendChild(remove);
    tags.appendChild(chip);
  }
  const addForm = document.createElement("form");
  addForm.className = "add-tag-form";
  addForm.noValidate = true;
  const addInput = document.createElement("input");
  addInput.type = "text";
  addInput.autocomplete = "off";
  addInput.setAttribute("aria-label", "New tag");
  const addButton = document.createElement("button");
  addButton.type = "submit";
  addButton.textContent = "Add tag";
  addForm.append(addInput, addButton);
  addForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const tag = addInput.value.trim();
    if (tag === "") return;
    changeTags(note.id, (list) => [...list, tag]);
  });
  const edit = document.createElement("button");
  edit.type = "button";
  edit.className = "edit-note";
  edit.textContent = "Edit";
  edit.addEventListener("click", () => requestLeave(() => openNote(note.id)));
  const del = document.createElement("button");
  del.type = "button";
  del.className = "delete-note";
  del.textContent = "Delete";
  del.addEventListener("click", () => askDelete(note.id));
  li.append(title, body, tags, addForm, edit, del);
  setTagControls(li, editingId === note.id);
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

function emptyText() {
  return activeTag === null ? "No notes yet" : "No notes with this tag";
}

async function loadPage() {
  if (loading) return;
  loading = true;
  const mine = generation;
  updateLoadMore();
  try {
    const params = [];
    if (activeTag !== null) params.push("tag=" + encodeURIComponent(activeTag));
    if (cursor !== null) params.push("cursor=" + encodeURIComponent(cursor));
    const response = await fetch(params.length ? "/notes?" + params.join("&") : "/notes");
    if (!response.ok) throw new Error("request failed");
    const page = await response.json();
    if (mine !== generation) return;
    appendNotes(page.items);
    cursor = page.next_cursor;
    messageEl.textContent = shown.size === 0 ? emptyText() : "";
  } catch (err) {
    if (mine === generation) messageEl.textContent = "The service is unavailable";
  } finally {
    if (mine === generation) {
      loading = false;
      updateLoadMore();
    }
  }
}

const tagsEl_ = document.getElementById("tags");
const tagsEmptyEl = document.getElementById("tags-empty");
const filterBarEl = document.getElementById("filter-bar");
const filterTagEl = document.getElementById("filter-tag");

function renderTags(items) {
  tagsEl_.replaceChildren();
  for (const item of items) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tag-filter";
    button.textContent = item.tag + " (" + item.count + ")";
    button.setAttribute("aria-label", "Filter by tag " + item.tag + ", " + item.count + " notes");
    button.addEventListener("click", () => selectTag(item.tag));
    li.appendChild(button);
    tagsEl_.appendChild(li);
  }
  tagsEmptyEl.hidden = items.length > 0;
}

async function loadTags() {
  try {
    const response = await fetch("/tags");
    if (!response.ok) throw new Error("request failed");
    renderTags(await response.json());
  } catch (err) {
    tagsEmptyEl.textContent = "Tags are unavailable";
    tagsEmptyEl.hidden = false;
  }
}

function resetList() {
  generation += 1;
  loading = false;
  shown.clear();
  cursor = null;
  listEl.replaceChildren();
  messageEl.textContent = "Loading notes…";
}

function applyFilter(tag) {
  activeTag = tag;
  resetList();
  filterBarEl.hidden = tag === null;
  filterTagEl.textContent = tag === null ? "" : tag;
  return loadPage();
}

function selectTag(tag) {
  return applyFilter(tag);
}

function clearFilter() {
  return applyFilter(null);
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

function setTagControls(row, disabled) {
  for (const el of row.querySelectorAll(".remove-tag, .add-tag-form input, .add-tag-form button")) {
    el.disabled = disabled;
  }
}

function syncTagControls() {
  for (const row of listEl.querySelectorAll("li.note")) {
    setTagControls(row, Number(row.dataset.id) === editingId);
  }
}

async function changeTags(id, mutate) {
  const row = rowOf(id);
  if (!row || id === editingId) return;
  setTagControls(row, true);
  try {
    const got = await fetch("/notes/" + id);
    if (got.status === 404) {
      removeRow(id);
      messageEl.textContent = "This note no longer exists";
      return;
    }
    if (!got.ok) throw new Error("request failed");
    const note = await got.json();
    const response = await fetch("/notes/" + id, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: note.title, body: note.body, tags: mutate(note.tags) }),
    });
    if (response.status === 200) {
      const current = rowOf(id);
      if (current) current.replaceWith(renderNotes(await response.json()));
      messageEl.textContent = "";
    } else if (response.status === 404) {
      removeRow(id);
      messageEl.textContent = "This note no longer exists";
    } else {
      throw new Error("request failed");
    }
  } catch (err) {
    messageEl.textContent = "The action did not succeed.";
    const current = rowOf(id);
    if (current) setTagControls(current, id === editingId);
  }
}

function removeRow(id) {
  const row = rowOf(id);
  if (row) row.remove();
  shown.delete(id);
  if (shown.size === 0 && messageEl.textContent === "") messageEl.textContent = emptyText();
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
  syncTagControls();
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
    syncTagControls();
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

const deleteEl = document.getElementById("delete-confirm");
const confirmDeleteEl = document.getElementById("confirm-delete");
let pendingDeleteId = null;

function askDelete(id) {
  pendingDeleteId = id;
  deleteEl.hidden = false;
  confirmDeleteEl.focus();
}

function cancelDelete() {
  pendingDeleteId = null;
  deleteEl.hidden = true;
}

async function confirmDelete() {
  const id = pendingDeleteId;
  if (id === null) return;
  confirmDeleteEl.disabled = true;
  try {
    const response = await fetch("/notes/" + id, { method: "DELETE" });
    if (response.status === 204 || response.status === 404) {
      if (editingId === id) closeEdit();
      removeRow(id);
      if (response.status === 404) messageEl.textContent = "This note no longer exists";
      cancelDelete();
    } else {
      cancelDelete();
      messageEl.textContent = "The action did not succeed.";
    }
  } catch (err) {
    cancelDelete();
    messageEl.textContent = "The action did not succeed.";
  } finally {
    confirmDeleteEl.disabled = false;
  }
}

formEl.addEventListener("submit", createNote);
editFormEl.addEventListener("submit", saveEdit);
document.getElementById("edit-close").addEventListener("click", () => requestLeave(closeEdit));
document.getElementById("keep-editing").addEventListener("click", keepEditing);
document.getElementById("discard-edits").addEventListener("click", discardEdits);
confirmDeleteEl.addEventListener("click", confirmDelete);
document.getElementById("cancel-delete").addEventListener("click", cancelDelete);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !deleteEl.hidden) cancelDelete();
});
window.addEventListener("beforeunload", (event) => {
  if (isDirty()) {
    event.preventDefault();
    event.returnValue = "";
  }
});
moreEl.addEventListener("click", loadPage);
document.getElementById("clear-filter").addEventListener("click", clearFilter);
loadTags();
loadPage();

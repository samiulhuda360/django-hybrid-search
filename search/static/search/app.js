// Search-as-you-type suggestions and the AI answer panel. No framework, no build step.
(function () {
  "use strict";

  function escapeHtml(text) {
    return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  function setupSuggestions(input) {
    const list = input.parentElement.querySelector(".suggestions");
    const form = input.form;
    let items = [];
    let active = -1;
    let timer = null;
    let controller = null;

    function render() {
      list.innerHTML = "";
      const typed = input.value.trim().toLowerCase();
      items.forEach((text, i) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", String(i === active));
        // Bold the part the user has not typed yet.
        li.innerHTML = text.toLowerCase().startsWith(typed)
          ? escapeHtml(text.slice(0, typed.length)) + "<b>" + escapeHtml(text.slice(typed.length)) + "</b>"
          : escapeHtml(text);
        li.addEventListener("mousedown", (e) => { e.preventDefault(); choose(text); });
        list.appendChild(li);
      });
      list.hidden = items.length === 0;
    }

    function choose(text) {
      input.value = text;
      list.hidden = true;
      form.submit();
    }

    async function fetchSuggestions() {
      const q = input.value.trim();
      if (q.length < 2) { items = []; render(); return; }
      if (controller) controller.abort();
      controller = new AbortController();
      try {
        const res = await fetch(input.dataset.suggestUrl + "?q=" + encodeURIComponent(q), { signal: controller.signal });
        items = (await res.json()).suggestions || [];
        active = -1;
        render();
      } catch (err) {
        if (err.name !== "AbortError") { items = []; render(); }
      }
    }

    input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(fetchSuggestions, 120); });
    input.addEventListener("blur", () => { list.hidden = true; });
    input.addEventListener("keydown", (e) => {
      if (list.hidden || !items.length) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        render();
      } else if (e.key === "Enter" && active >= 0) {
        e.preventDefault();
        choose(items[active]);
      } else if (e.key === "Escape") {
        list.hidden = true;
      }
    });
  }

  async function loadAnswer(section) {
    const body = section.querySelector(".answer-body");
    const mode = section.querySelector(".answer-mode");
    const sources = section.querySelector(".answer-sources");
    try {
      const res = await fetch(section.dataset.answerUrl);
      const data = await res.json();
      if (data.mode === "none" || !data.html) { section.remove(); return; }
      body.innerHTML = data.html; // escaped on the server; only citation links are added
      mode.textContent = data.mode === "ai"
        ? "Written by AI from the pages below" + (data.cached ? " (cached)" : "")
        : "Quoted from the pages below";
      sources.innerHTML = "";
      // Only list sources when the answer cites at least one of them.
      if (!data.sources.some((s) => s.cited)) sources.remove();
      data.sources.forEach((s) => {
        const li = document.createElement("li");
        li.id = "source-" + s.n;
        li.className = s.cited ? "cited" : "";
        const a = document.createElement("a");
        a.href = s.url;
        a.textContent = s.title;
        li.appendChild(a);
        sources.appendChild(li);
      });
      if (data.note) {
        const p = document.createElement("p");
        p.className = "answer-note";
        p.textContent = data.note;
        section.appendChild(p);
      }
    } catch (err) {
      section.remove();
    }
  }

  document.querySelectorAll("input[data-suggest-url]").forEach(setupSuggestions);
  document.querySelectorAll(".answer[data-answer-url]").forEach(loadAnswer);
})();

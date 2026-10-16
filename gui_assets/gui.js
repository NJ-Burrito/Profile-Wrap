"use strict";
(function () {
  var TOKEN = document.querySelector('meta[name="pw-token"]').content;
  var SCREEN = document.body.dataset.screen;
  var view = document.getElementById("view");
  var statusEl = document.getElementById("status");

  // ---- tiny DOM helper: text nodes only, so data cannot become markup
  function h(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === false || v == null) return;
      if (k === "class") el.className = v;
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
      else if (k === "value") el.value = v;
      else el.setAttribute(k, v === true ? "" : v);
    });
    function add(c) {
      if (c == null || c === false) return;
      if (Array.isArray(c)) { c.forEach(add); return; }
      el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    }
    for (var i = 2; i < arguments.length; i++) add(arguments[i]);
    return el;
  }
  function say(msg, kind) {
    statusEl.textContent = msg || "";
    statusEl.className = "status" + (kind ? " " + kind : "");
  }
  function api(path, body) {
    var opts = { headers: { "X-PW-Token": TOKEN } };
    if (body !== undefined) {
      opts.method = "POST";
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.error || ("request failed (" + r.status + ")"));
        return j;
      });
    });
  }
  function busy(btn, promise, okMsg) {
    btn.disabled = true;
    say("Working");
    return promise.then(function (r) { if (okMsg) say(okMsg, "ok"); return r; })
      .catch(function (e) { say(e.message, "bad"); throw e; })
      .then(function (r) { btn.disabled = false; return r; }, function (e) { btn.disabled = false; });
  }
  function badge(text, kind) { return h("span", { class: "badge " + (kind || "") }, text); }
  function mount(node) { view.replaceChildren(node); view.setAttribute("aria-busy", "false"); }

  // ---- shell: current page, theme, keys
  document.querySelectorAll("#nav a").forEach(function (a) {
    if (a.dataset.nav === SCREEN) a.setAttribute("aria-current", "page");
  });
  var root = document.documentElement;
  var saved = null;
  try { saved = localStorage.getItem("pw-theme"); } catch (e) { saved = null; }
  if (saved === "light" || saved === "dark") root.dataset.theme = saved;
  document.getElementById("theme").addEventListener("click", function () {
    var dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("pw-theme", root.dataset.theme); } catch (e) { /* private mode */ }
  });
  var paths = ["/", "/board", "/providers", "/build", "/settings"];
  document.addEventListener("keydown", function (e) {
    if (!e.altKey || e.ctrlKey || e.metaKey) return;
    var i = "12345".indexOf(e.key);
    if (i >= 0) { e.preventDefault(); location.href = paths[i] + "?t=" + encodeURIComponent(TOKEN); }
  });
  document.getElementById("main").focus();

  // ---- Home
  function home() {
    api("/api/home").then(function (d) {
      var sum = (d.doctor && d.doctor.summary) || {};
      var checks = (d.doctor && d.doctor.checks) || [];
      var bad = checks.filter(function (c) { return c.status === "fail" || c.status === "warn"; });
      var next = d.next_post;
      var doc = h("section", { class: "card", "aria-labelledby": "h-doc" },
        h("h2", { id: "h-doc" }, "Doctor"),
        h("p", { class: "big" }, (sum.fail ? sum.fail + " failing" : "All clear"),
          " ", badge((sum.pass || 0) + " ok", "ok"), " ", sum.warn ? badge(sum.warn + " warn", "warn") : null,
          " ", sum.fail ? badge(sum.fail + " fail", "bad") : null),
        bad.length ? h("ul", { class: "plain" }, bad.slice(0, 6).map(function (c) {
          return h("li", null, badge(c.status, c.status === "fail" ? "bad" : "warn"), " ", c.name || c.id,
            c.hint ? h("span", { class: "muted" }, " - " + c.hint) : null);
        })) : h("p", { class: "muted" }, "Nothing needs attention."),
        h("div", { class: "row" }, h("button", { type: "button", class: "ghost", onclick: function (ev) {
          busy(ev.target, api("/api/doctor", {}).then(function () { home(); }), "Checked again");
        } }, "Run the doctor again")));
      mount(h("div", { class: "grid" },
        h("section", { class: "card", "aria-labelledby": "h-st" }, h("h2", { id: "h-st" }, "Status"),
          h("p", { class: "big" }, d.workspace),
          h("p", { class: "muted small" }, d.workspace_path),
          h("p", null, "Posting mode: ", badge(d.posting_mode || "unset")),
          h("p", null, "Paused: ", d.paused.length ? badge(d.paused.join(", "), "warn") : badge("no", "ok")),
          h("p", null, "Provider: ", d.provider ? badge(d.provider + (d.model ? " / " + d.model : "")) : badge("not chosen", "warn"))),
        h("section", { class: "card", "aria-labelledby": "h-nx" }, h("h2", { id: "h-nx" }, "Next post"),
          next ? h("div", null, h("p", { class: "big" }, next.title || next.slug),
            h("p", null, badge(next.state, next.state === "queued" ? "ok" : ""), " ", next.when || ""),
            h("a", { href: "/build?t=" + encodeURIComponent(TOKEN) }, "Open in Build"))
            : h("p", { class: "muted" }, "Nothing planned. Add a day with `profile-wrap calendar add`.")),
        doc));
    }).catch(fail);
  }

  // ---- Board
  function board() {
    var link = h("p");
    function show(s) {
      link.replaceChildren(s.running ? h("a", { href: s.url, target: "_blank", rel: "noopener" }, "Open the board (" + s.url + ")")
        : h("span", { class: "muted" }, "The board is not running."));
    }
    var btn = h("button", { type: "button", onclick: function (ev) {
      busy(ev.target, api("/api/board/start", {}).then(show), "Board started on this machine");
    } }, "Start the review board");
    mount(h("section", { class: "card", "aria-labelledby": "h-b" }, h("h2", { id: "h-b" }, "Review board"),
      h("p", null, "The board is where you read, Allow, reject or improve each draft before anything is posted. It opens in its own tab or window because it keeps its own security rules."),
      h("div", { class: "row" }, btn), link));
    api("/api/board").then(show).catch(fail);
  }

  // ---- Providers
  function providers() {
    var wrap = h("div");
    var chosen = null;
    function render(d) {
      chosen = d.chosen;
      var parts = [];
      if (!d.keychain) parts.push(h("p", { class: "card" }, "No OS keychain here. Set the environment variable PROFILE_WRAP_<PROVIDER>_API_KEY instead; the app reads it."));
      parts.push(h("div", { class: "grid" }, d.providers.map(card)));
      wrap.replaceChildren.apply(wrap, parts);
    }
    function reload() { return api("/api/providers").then(render); }
    function card(p) {
      var keyId = "key-" + p.id, modelId = "model-" + p.id;
      var key = p.needs_key ? h("input", { id: keyId, type: "password", autocomplete: "off", spellcheck: "false", placeholder: p.key === "missing" ? "Paste your API key" : "Paste a new key to replace it" }) : null;
      var model = h("input", { id: modelId, value: p.model, autocomplete: "off" });
      return h("section", { class: "card", "aria-labelledby": "h-" + p.id },
        h("div", { class: "row between" }, h("h2", { id: "h-" + p.id }, p.label), p.in_use ? badge("in use", "ok") : null),
        h("p", { class: "muted small" }, p.note || (p.needs_key ? "Your own key; it never leaves this machine except to this provider." : "")),
        p.needs_key ? h("p", null, "Key: ", badge(p.key, p.key === "missing" ? "warn" : "ok"), p.source !== "-" ? " (" + p.source + ")" : "") : null,
        h("div", { class: "field" },
          p.needs_key ? h("label", { for: keyId }, "API key", key) : null,
          h("label", { for: modelId }, "Model", model),
          h("div", { class: "row" },
            p.needs_key ? h("button", { type: "button", onclick: function (ev) {
              var v = key.value; key.value = "";
              busy(ev.target, api("/api/providers/key", { provider: p.id, key: v }).then(reload), "Key saved in the OS keychain");
            } }, p.key === "missing" ? "Save key" : "Replace key") : null,
            h("button", { type: "button", class: "ghost", onclick: function (ev) {
              busy(ev.target, api("/api/providers/test", { provider: p.id }).then(function (r) {
                say((r.ok ? "Connected: " : "Not connected: ") + r.message + (r.status ? " (status " + r.status + ")" : ""), r.ok ? "ok" : "bad");
              })).catch(function () {});
            } }, "Test connection"),
            h("button", { type: "button", class: "ghost", onclick: function (ev) {
              busy(ev.target, api("/api/providers/use", { provider: p.id, model: model.value }).then(reload), "Using " + p.label);
            } }, "Use this one"),
            p.needs_key && p.source === "keychain" ? h("button", { type: "button", class: "danger", onclick: function (ev) {
              busy(ev.target, api("/api/providers/key/delete", { provider: p.id }).then(reload), "Key removed");
            } }, "Remove key") : null)));
    }
    mount(wrap);
    reload().catch(fail);
  }

  // ---- Build
  function build() {
    var sel = h("select", { id: "day" });
    var replace = h("input", { type: "checkbox", id: "replace" });
    var out = h("div");
    var rows = [];
    function current() { return sel.value; }
    function showGate(g) {
      out.appendChild(h("section", { class: "card", "aria-labelledby": "h-g" }, h("h2", { id: "h-g" }, "Gate"),
        h("p", { class: "big" }, badge(g.summary, g.summary === "PASS" ? "ok" : "bad")),
        g.fails.length ? h("ul", { class: "plain" }, g.fails.map(function (f) { return h("li", null, badge("fail", "bad"), " ", f); })) : null,
        g.warnings.length ? h("ul", { class: "plain" }, g.warnings.map(function (f) { return h("li", null, badge("warn", "warn"), " ", f); })) : null,
        h("ul", { class: "plain" }, Object.keys(g.checks).map(function (k) {
          return h("li", { class: "muted small" }, (g.checks[k].ok ? "ok  " : "FAIL ") + k + ": " + g.checks[k].detail);
        }))));
    }
    function showDraft(d) {
      out.replaceChildren(h("section", { class: "card", "aria-labelledby": "h-d" }, h("h2", { id: "h-d" }, "Draft"),
        h("p", { class: "draft", dir: "auto" }, d.caption || "(no caption yet)"),
        d.alt ? h("p", { class: "muted small", dir: "auto" }, "Alt text: " + d.alt) : null));
    }
    function runGate(btn) {
      return busy(btn, api("/api/build/gate", { slug: current() }).then(function (g) { showGate(g); return g; }));
    }
    api("/api/calendar").then(function (d) {
      rows = d.entries;
      if (!rows.length) { mount(h("p", { class: "card" }, "The calendar has no planned days. Add one with `profile-wrap calendar add`.")); return; }
      rows.forEach(function (r) {
        sel.appendChild(h("option", { value: r.slug }, r.date + "  " + (r.title || r.slug) + "  [" + r.format + ", " + r.lang + "]" + (r.has_draft ? "  - has draft" : "")));
      });
      var gen = h("button", { type: "button", onclick: function (ev) {
        busy(ev.target, api("/api/build/draft", { slug: current(), overwrite: replace.checked }).then(function (d2) {
          showDraft(d2); return runGate(ev.target);
        }), "Draft written to drafts/" + current()).catch(function () {});
      } }, "Generate draft");
      var gate = h("button", { type: "button", class: "ghost", onclick: function (ev) {
        api("/api/build/text", { slug: current() }).then(showDraft).then(function () { return runGate(ev.target); }).catch(function (e) { say(e.message, "bad"); });
      } }, "Run the gate on the saved draft");
      mount(h("div", null,
        h("section", { class: "card", "aria-labelledby": "h-p" }, h("h2", { id: "h-p" }, "Pick a day"),
          h("div", { class: "field" }, h("label", { for: "day" }, "Calendar day", sel),
            h("label", { class: "inline", for: "replace" }, replace, "Replace an existing caption"),
            h("div", { class: "row" }, gen, gate)),
          h("p", { class: "muted small" }, "Uses the provider chosen on the Providers screen. The app writes drafts only; nothing is posted from here.")),
        out));
    }).catch(fail);
  }

  // ---- Settings
  function settings() {
    var wrap = h("div");
    function render(s) {
      var mode = h("select", { id: "mode" }, s.posting_modes.map(function (m) { return h("option", { value: m, selected: m === s.posting_mode }, m); }));
      var path = h("input", { id: "ws", value: s.workspace_path, autocomplete: "off" });
      wrap.replaceChildren(
        h("section", { class: "card", "aria-labelledby": "h-w" }, h("h2", { id: "h-w" }, "Workspace folder"),
          h("div", { class: "field" }, h("label", { for: "ws" }, "Folder", path),
            h("div", { class: "row" }, h("button", { type: "button", onclick: function (ev) {
              busy(ev.target, api("/api/settings/workspace", { path: path.value }).then(render), "Workspace changed for this session");
            } }, "Use this folder"))),
          h("p", { class: "muted small" }, "It must hold config/profile-wrap.json (made by `profile-wrap init`).")),
        h("section", { class: "card", "aria-labelledby": "h-m" }, h("h2", { id: "h-m" }, "Posting mode"),
          h("div", { class: "field" }, h("label", { for: "mode" }, "Mode", mode),
            h("div", { class: "row" }, h("button", { type: "button", onclick: function (ev) {
              busy(ev.target, api("/api/settings/posting-mode", { mode: mode.value }).then(render), "Posting mode saved");
            } }, "Save mode"))),
          h("p", { class: "muted small" }, "api_scheduled also needs its written acknowledgement (`profile-wrap config ack`).")),
        h("section", { class: "card", "aria-labelledby": "h-s" }, h("h2", { id: "h-s" }, "Schedule"),
          h("p", { class: "muted small" }, s.note),
          h("ul", { class: "plain" }, s.jobs.map(function (j) {
            var cb = h("input", { type: "checkbox", id: "job-" + j.name, checked: j.enabled });
            cb.addEventListener("change", function () {
              api("/api/settings/job", { name: j.name, enabled: cb.checked }).then(function () { say(j.name + (cb.checked ? " on" : " off"), "ok"); })
                .catch(function (e) { cb.checked = !cb.checked; say(e.message, "bad"); });
            });
            return h("li", null, h("label", { class: "inline", for: "job-" + j.name }, cb, j.name));
          }))),
        h("section", { class: "card" }, h("h2", null, "Session"),
          h("button", { type: "button", class: "ghost", onclick: function () { api("/api/quit", {}).then(function () { say("Server stopping. You can close this tab.", "ok"); }); } }, "Quit the app server")));
    }
    mount(wrap);
    api("/api/settings").then(render).catch(fail);
  }

  function fail(e) { mount(h("p", { class: "card" }, "Could not load this screen: " + e.message)); say(e.message, "bad"); }

  ({ home: home, board: board, providers: providers, build: build, settings: settings })[SCREEN]();
})();

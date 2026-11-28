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
  // inline icons: built with createElementNS from fixed path data, never from markup strings
  var ICONS = {
    calendar: ["M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z", "M4 10h16M8 3v4M16 3v4"],
    board: ["M4 7a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3z", "m8.5 12.3 2.5 2.5 4.5-5"],
    pass: ["M5 12.5l4.2 4.2L19 7"],
    stop: ["M6 6l12 12M18 6 6 18"]
  };
  function icon(name) {
    var ns = "http://www.w3.org/2000/svg";
    var s = document.createElementNS(ns, "svg");
    s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("class", "ico"); s.setAttribute("aria-hidden", "true");
    ICONS[name].forEach(function (d) { var p = document.createElementNS(ns, "path"); p.setAttribute("d", d); s.appendChild(p); });
    return s;
  }
  function arrow() { return h("span", { class: "arrow", "aria-hidden": "true" }, "→"); }
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
        if (!r.ok) {
          var err = new Error(j.error || ("request failed (" + r.status + ")"));
          err.code = j.code || null; err.params = j.params || {};
          throw err;
        }
        return j;
      });
    });
  }
  function busy(btn, promise, okMsg) {
    btn.disabled = true;
    say(t("ui.working"));
    return promise.then(function (r) { say(okMsg || "", okMsg ? "ok" : ""); return r; })
      .catch(function (e) { say(errMsg(e), "bad"); throw e; })
      .then(function (r) { btn.disabled = false; return r; }, function (e) { btn.disabled = false; });
  }
  function errMsg(e) { return e && e.code ? t(e.code, e.params) : (e && e.message) || ""; }
  function badge(text, kind) { return h("span", { class: "badge " + (kind || "") }, text); }
  function mount(node) { view.replaceChildren(node); view.setAttribute("aria-busy", "false"); }
  function cmd(text) { return h("code", { class: "cmd", dir: "ltr" }, text); }

  // ---- i18n: the same two JSON files the terminal flows read (gui_assets/i18n/en.json and ar.json)
  var LANG = document.documentElement.lang === "ar" ? "ar" : "en";
  var STR = { en: {}, ar: {} };
  function has(key) { return STR[LANG][key] !== undefined || STR.en[key] !== undefined; }
  function t(key, params) {
    var s = STR[LANG][key];
    if (s === undefined) s = STR.en[key];
    if (s === undefined) return key;
    return s.replace(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g, function (m, name) {
      return params && params[name] !== undefined ? String(params[name]) : m;
    });
  }
  // a value the server sends (a mode, a state): its translated label when there is one, else the value itself
  function tv(prefix, value) { return value != null && has(prefix + value) ? t(prefix + value) : String(value); }
  // text with a built-in English fallback, for the strings the update banner must keep even before the table loads
  function tf(key, fallback, params) { return has(key) ? t(key, params) : fallback; }
  function loadStrings() {
    function get(l) { return fetch("/assets/i18n/" + l + ".json").then(function (r) { return r.json(); }).catch(function () { return {}; }); }
    return Promise.all([get("en"), LANG === "ar" ? get("ar") : Promise.resolve({})]).then(function (r) { STR.en = r[0]; STR.ar = r[1]; });
  }
  function applyI18n() {
    document.querySelectorAll("[data-i18n]").forEach(function (el) { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll("[data-i18n-fmt]").forEach(function (el) { el.textContent = t(el.dataset.i18nFmt, { v: el.dataset.v }); });
    document.querySelectorAll("[data-i18n-label]").forEach(function (el) { el.setAttribute("aria-label", t(el.dataset.i18nLabel)); });
  }

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
  document.getElementById("lang").addEventListener("click", function (ev) {
    var next = LANG === "ar" ? "en" : "ar";
    busy(ev.target, api("/api/settings/language", { lang: next }).then(function () { location.reload(); })).catch(function () {});
  });
  var paths = ["/", "/board", "/providers", "/build", "/settings", "/connect"];
  document.addEventListener("keydown", function (e) {
    if (!e.altKey || e.ctrlKey || e.metaKey) return;
    var i = "123456".indexOf(e.key);
    if (i >= 0) { e.preventDefault(); location.href = paths[i] + "?t=" + encodeURIComponent(TOKEN); }
  });
  document.getElementById("main").focus();
  function link(path) { return path + "?t=" + encodeURIComponent(TOKEN); }

  function when(v) {
    var d = new Date(v);
    if (isNaN(d.getTime())) return String(v);
    try { return d.toLocaleString(LANG === "ar" ? "ar" : "en-GB", { dateStyle: "medium", timeStyle: "short" }); } catch (e) { return String(v); }
  }

  // ---- Home
  function home() {
    api("/api/home").then(function (d) {
      var sum = (d.doctor && d.doctor.summary) || {};
      var checks = (d.doctor && d.doctor.checks) || [];
      var bad = checks.filter(function (c) { return c.status === "fail" || c.status === "warn"; });
      var next = d.next_post;
      function tile(label, body, extra) {
        return h("div", { class: "tile" }, h("p", { class: "eyebrow" }, label), body, extra || null);
      }
      var tiles = h("div", { class: "tiles" },
        tile(t("home.status.title"), h("div", { class: "val" }, d.workspace), h("p", { class: "path", dir: "ltr" }, d.workspace_path)),
        tile(t("home.mode"), h("div", { class: "val" }, h("span", { class: "dot " + (d.posting_mode === "copy" ? "ok" : "warn") }),
          d.posting_mode ? tv("mode.", d.posting_mode) : t("home.mode_unset"))),
        tile(t("home.provider"), h("div", { class: "val" }, h("span", { class: "dot " + (d.provider ? "ok" : "warn") }),
          d.provider ? d.provider + (d.model ? " / " + d.model : "") : t("home.provider_none"))),
        tile(t("home.paused"), h("div", { class: "val" }, h("span", { class: "dot " + (d.paused.length ? "warn" : "ok") }),
          d.paused.length ? d.paused.join(", ") : t("home.paused_none"))));

      var nextCard = h("section", { class: "card hero", "aria-labelledby": "h-nx" }, h("h2", { id: "h-nx" }, t("home.next.title")),
        next ? h("div", null, h("p", { class: "big" }, next.title || next.slug),
          h("p", { class: "row" }, badge(tv("post.", next.state), next.state === "queued" ? "ok" : ""), next.when ? h("span", { class: "muted" }, when(next.when)) : null),
          h("a", { href: link("/build") }, t("home.next.open"), " ", arrow()))
          : h("div", null, h("p", { class: "big" }, t("home.next.empty")), h("p", { class: "muted" }, t("home.next.empty_hint")), cmd("profile-wrap calendar add")));

      var failing = sum.fail || 0, warns = sum.warn || 0;
      var doc = h("section", { class: "card", "aria-labelledby": "h-doc" },
        h("div", { class: "card-h" }, h("h2", { id: "h-doc" }, t("home.doctor.title")),
          h("span", { class: "row" }, badge(t("home.doctor.ok", { n: sum.pass || 0 }), "ok"),
            warns ? badge(t("home.doctor.warn", { n: warns }), "warn") : null,
            failing ? badge(t("home.doctor.failing", { n: failing }), "bad") : null)),
        bad.length ? h("ul", { class: "items" }, bad.slice(0, 6).map(function (c) {
          return h("li", null, h("span", { class: "dot " + (c.status === "fail" ? "bad" : "warn") }),
            h("span", { class: "grow" }, h("span", { class: "name" }, c.name || c.id), c.hint ? h("span", { class: "hint" }, c.hint) : null));
        })) : h("p", { class: "big" }, h("span", { class: "dot ok" }), " ", failing ? t("home.doctor.failing", { n: failing }) : t("home.doctor.clear")),
        bad.length ? null : h("p", { class: "muted" }, t("home.doctor.nothing")),
        h("div", { class: "row" }, h("button", { type: "button", class: "ghost", onclick: function (ev) {
          busy(ev.target, api("/api/doctor", {}).then(function () { home(); }), t("home.doctor.rerun_done"));
        } }, t("home.doctor.rerun"))));

      var first = d.posting_mode === "copy" ? h("section", { class: "card span", "aria-labelledby": "h-cm" },
        h("div", { class: "card-h" }, h("h2", { id: "h-cm" }, t("home.copy.title"))),
        h("ol", { class: "steps-list" }, h("li", null, h("span", null, t("home.copy.s1"))), h("li", null, h("span", null, t("home.copy.s2"))),
          h("li", null, h("span", null, t("home.copy.s3"))), h("li", null, h("span", null, t("home.copy.s4")))),
        h("p", { class: "muted small" }, t("home.copy.noapp")),
        h("div", { class: "row" },
          h("a", { href: link("/build") }, t("home.copy.link_build"), " ", arrow()),
          h("a", { href: link("/connect") }, t("home.copy.link_connect"), " ", arrow()))) : null;
      mount(h("div", { class: "stack" }, tiles, h("div", { class: "grid two" }, nextCard, doc), first));
    }).catch(fail);
  }

  // ---- Board
  function board() {
    var chip = h("span");
    var link2 = h("p");
    function show(s) {
      chip.replaceChildren(badge(s.running ? t("board.running") : t("board.stopped"), s.running ? "ok" : ""));
      link2.replaceChildren(s.running ? h("a", { href: s.url, target: "_blank", rel: "noopener" }, t("board.open"), " ", arrow(), " ", h("span", { class: "ltr small muted", dir: "ltr" }, s.url))
        : h("span", { class: "muted" }, t("board.off")));
    }
    var btn = h("button", { type: "button", onclick: function (ev) {
      busy(ev.target, api("/api/board/start", {}).then(show), t("board.started"));
    } }, t("board.start"));
    mount(h("section", { class: "card hero", "aria-labelledby": "h-b" },
      h("div", { class: "card-h" }, h("h2", { id: "h-b" }, t("board.card")), chip),
      h("p", { class: "big" }, t("title.board")),
      h("p", { class: "muted" }, t("board.text")),
      h("div", { class: "row" }, btn), h("div", { class: "row" }, link2)));
    api("/api/board").then(show).catch(fail);
  }

  // ---- Providers
  function providers() {
    var wrap = h("div", { class: "stack" });
    function render(d) {
      var parts = [];
      if (!d.keychain) parts.push(h("p", { class: "card" }, t("prov.nokeychain")));
      parts.push(h("div", { class: "grid" }, d.providers.map(card)));
      wrap.replaceChildren.apply(wrap, parts);
    }
    function reload() { return api("/api/providers").then(render); }
    function card(p) {
      var keyId = "key-" + p.id, modelId = "model-" + p.id;
      var key = p.needs_key ? h("input", { id: keyId, type: "password", autocomplete: "off", spellcheck: "false", placeholder: p.key === "missing" ? t("prov.ph_new") : t("prov.ph_replace") }) : null;
      var model = h("input", { id: modelId, value: p.model, autocomplete: "off", dir: "ltr" });
      var keyText = p.key === "missing" ? t("prov.key_missing") : (p.key === "not needed" ? t("prov.key_none") : p.key);
      return h("section", { class: "card" + (p.in_use ? " use" : ""), "aria-labelledby": "h-" + p.id },
        h("div", { class: "card-h" }, h("h2", { id: "h-" + p.id }, p.label), p.in_use ? badge(t("prov.in_use"), "ok") : null),
        h("p", { class: "muted small" }, p.note || (p.needs_key ? t("prov.note") : "")),
        p.needs_key ? h("p", { class: "row" }, h("span", { class: "muted" }, t("prov.key")), badge(keyText, p.key === "missing" ? "warn" : "ok"),
          p.source !== "-" ? h("span", { class: "muted small" }, p.source) : null) : null,
        h("div", { class: "field wide" },
          p.needs_key ? h("label", { for: keyId }, t("prov.key_label"), key) : null,
          h("label", { for: modelId }, t("prov.model"), model),
          h("div", { class: "row" },
            p.needs_key ? h("button", { type: "button", onclick: function (ev) {
              var v = key.value; key.value = "";
              busy(ev.target, api("/api/providers/key", { provider: p.id, key: v }).then(reload), t("prov.saved"));
            } }, p.key === "missing" ? t("prov.save") : t("prov.replace")) : null,
            h("button", { type: "button", class: "ghost", onclick: function (ev) {
              busy(ev.target, api("/api/providers/test", { provider: p.id }).then(function (r) {
                say(t(r.ok ? "prov.connected" : "prov.not_connected", { msg: r.message + (r.status ? " (" + r.status + ")" : "") }), r.ok ? "ok" : "bad");
              })).catch(function () {});
            } }, t("prov.test")),
            h("button", { type: "button", class: "ghost", onclick: function (ev) {
              busy(ev.target, api("/api/providers/use", { provider: p.id, model: model.value }).then(reload), t("prov.using", { name: p.label }));
            } }, t("prov.use")),
            p.needs_key && p.source === "keychain" ? h("button", { type: "button", class: "danger", onclick: function (ev) {
              busy(ev.target, api("/api/providers/key/delete", { provider: p.id }).then(reload), t("prov.removed"));
            } }, t("prov.remove")) : null)));
    }
    mount(wrap);
    reload().catch(fail);
  }

  // ---- Build
  function build() {
    var sel = h("select", { id: "day" });
    var replace = h("input", { type: "checkbox", id: "replace" });
    var out = h("div", { class: "stack" });
    var rows = [];
    function current() { return sel.value; }
    function showGate(g) {
      var pass = g.summary === "PASS";
      out.appendChild(h("section", { class: "card", "aria-labelledby": "h-g" },
        h("div", { class: "card-h" }, h("h2", { id: "h-g" }, t("build.gate")), badge(g.summary, pass ? "ok" : "bad")),
        h("p", { class: "verdict " + (pass ? "ok" : "bad gate-fail") }, icon(pass ? "pass" : "stop"), pass ? t("build.passed") : t("build.failed")),
        g.fails.length || g.warnings.length ? h("ul", { class: "items" },
          g.fails.map(function (f) { return h("li", null, h("span", { class: "dot bad" }), h("span", { class: "grow" }, badge(t("badge.fail"), "bad"), " ", f)); }),
          g.warnings.map(function (f) { return h("li", null, h("span", { class: "dot warn" }), h("span", { class: "grow" }, badge(t("badge.warn"), "warn"), " ", f)); })) : null,
        h("ul", { class: "plain checks" }, Object.keys(g.checks).map(function (k) {
          return h("li", { class: g.checks[k].ok ? "" : "no" }, h("span", null, h("b", null, k), ": " + g.checks[k].detail));
        }))));
    }
    function showDraft(d) {
      out.replaceChildren(h("section", { class: "card", "aria-labelledby": "h-d" }, h("div", { class: "card-h" }, h("h2", { id: "h-d" }, t("build.draft"))),
        h("p", { class: "draft", dir: "auto" }, d.caption || t("build.nocaption")),
        d.alt ? h("p", { class: "muted small", dir: "auto" }, t("build.alt") + ": " + d.alt) : null));
    }
    function copyBtn(label, text) {
      return h("button", { type: "button", class: "ghost", onclick: function () {
        if (!navigator.clipboard) { say(t("copy.failed"), "bad"); return; }
        navigator.clipboard.writeText(text).then(function () { say(t("copy.copied"), "ok"); },
          function () { say(t("copy.failed"), "bad"); });
      } }, label);
    }
    function showCopy(c) {
      out.appendChild(h("section", { class: "card hero", "aria-labelledby": "h-c" }, h("div", { class: "card-h" }, h("h2", { id: "h-c" }, t("copy.title"))),
        h("p", { class: "muted" }, t("copy.intro")),
        h("p", { class: "copybox", dir: "auto" }, c.caption),
        h("div", { class: "row" },
          copyBtn(t("copy.caption"), c.caption),
          c.first_comment ? copyBtn(t("copy.first_comment"), c.first_comment) : null,
          c.alt ? copyBtn(t("copy.alt"), c.alt) : null,
          h("a", { href: c.open_url, target: "_blank", rel: "noopener noreferrer" }, t("copy.open"), " ", arrow())),
        c.asset_names.length ? h("p", { class: "muted small" }, t("copy.media", { files: c.assets.join(", ") })) : null,
        h("p", { class: "muted small" }, t("copy.after"))));
    }
    function offerCopy(g) {
      if (g.summary !== "PASS") {
        out.appendChild(h("p", { class: "card muted" }, t("copy.blocked")));
        return;
      }
      api("/api/build/copy", { slug: current() }).then(showCopy).catch(function (e) { say(errMsg(e), "bad"); });
    }
    function runGate(btn) {
      return busy(btn, api("/api/build/gate", { slug: current() }).then(function (g) { showGate(g); offerCopy(g); return g; }));
    }
    api("/api/calendar").then(function (d) {
      rows = d.entries;
      if (!rows.length) {
        mount(h("div", { class: "empty" }, icon("calendar"), h("p", { class: "title" }, t("build.empty")), h("p", { class: "muted" }, t("build.empty_hint")), cmd("profile-wrap calendar add")));
        return;
      }
      rows.forEach(function (r) {
        sel.appendChild(h("option", { value: r.slug }, r.date + "  " + (r.title || r.slug) + "  [" + r.format + ", " + r.lang + "]" + (r.has_draft ? "  - " + t("build.has_draft") : "")));
      });
      var gen = h("button", { type: "button", id: "gen-btn", onclick: function (ev) {
        busy(ev.target, api("/api/build/draft", { slug: current(), overwrite: replace.checked }).then(function (d2) {
          showDraft(d2); return runGate(ev.target);
        }), t("build.written", { slug: current() })).catch(function () {});
      } }, t("build.generate"));
      var gate = h("button", { type: "button", class: "ghost", id: "gate-btn", onclick: function (ev) {
        out.replaceChildren();
        api("/api/build/text", { slug: current() }).then(showDraft).then(function () { return runGate(ev.target); }).catch(function (e) { say(e.message, "bad"); });
      } }, t("build.gate_saved"));
      mount(h("div", { class: "stack" },
        h("section", { class: "card", "aria-labelledby": "h-p" }, h("div", { class: "card-h" }, h("h2", { id: "h-p" }, t("build.pick"))),
          h("div", { class: "pick" },
            h("div", { class: "field wide" }, h("label", { for: "day" }, t("build.day"), sel),
              h("label", { class: "inline", for: "replace" }, replace, t("build.replace"))),
            h("div", { class: "row" }, gen, gate)),
          h("p", { class: "muted small" }, t("build.note"))),
        out));
    }).catch(fail);
  }

  // ---- Settings
  function settings() {
    var wrap = h("div", { class: "stack" });
    function render(s) {
      var mode = h("select", { id: "mode" }, s.posting_modes.map(function (m) { return h("option", { value: m, selected: m === s.posting_mode }, tv("mode.", m)); }));
      var path = h("input", { id: "ws", value: s.workspace_path, autocomplete: "off", dir: "ltr" });
      wrap.replaceChildren(
        h("div", { class: "grid two" },
          h("section", { class: "card", "aria-labelledby": "h-w" }, h("div", { class: "card-h" }, h("h2", { id: "h-w" }, t("set.ws.title"))),
            h("div", { class: "field wide" }, h("label", { for: "ws" }, t("set.ws.label"), path),
              h("div", { class: "row" }, h("button", { type: "button", onclick: function (ev) {
                busy(ev.target, api("/api/settings/workspace", { path: path.value }).then(render), t("set.ws.changed"));
              } }, t("set.ws.use")))),
            h("p", { class: "muted small" }, t("set.ws.hint"))),
          h("section", { class: "card", "aria-labelledby": "h-m" }, h("div", { class: "card-h" }, h("h2", { id: "h-m" }, t("set.mode.title"))),
            h("div", { class: "field wide" }, h("label", { for: "mode" }, t("set.mode.label"), mode),
              h("div", { class: "row" }, h("button", { type: "button", onclick: function (ev) {
                busy(ev.target, api("/api/settings/posting-mode", { mode: mode.value }).then(render), t("set.mode.saved"));
              } }, t("set.mode.save")))),
            h("p", { class: "muted small" }, t("set.mode.hint")))),
        h("section", { class: "card", "aria-labelledby": "h-s" }, h("div", { class: "card-h" }, h("h2", { id: "h-s" }, t("set.sched.title"))),
          h("p", { class: "muted small" }, t("set.sched.note")),
          h("ul", { class: "set" }, s.jobs.map(function (j) {
            var cb = h("input", { type: "checkbox", class: "switch", id: "job-" + j.name, checked: j.enabled });
            cb.addEventListener("change", function () {
              api("/api/settings/job", { name: j.name, enabled: cb.checked }).then(function () { say(t(cb.checked ? "set.job.on" : "set.job.off", { name: j.name }), "ok"); })
                .catch(function (e) { cb.checked = !cb.checked; say(e.message, "bad"); });
            });
            return h("li", null, h("label", { class: "inline", for: "job-" + j.name }, h("span", { class: "ltr", dir: "ltr" }, j.name), cb));
          }))),
        h("section", { class: "card", "aria-labelledby": "h-se" }, h("div", { class: "card-h" }, h("h2", { id: "h-se" }, t("set.session.title"))),
          h("div", { class: "row" }, h("button", { type: "button", class: "danger", onclick: function () { api("/api/quit", {}).then(function () { say(t("set.session.stopping"), "ok"); }); } }, t("set.session.quit")))));
    }
    mount(wrap);
    api("/api/settings").then(render).catch(fail);
  }

  // ---- Connect screen (optional): five steps, each with its own check
  function connect() {
    var wrap = h("div", { class: "stack" });
    var timer = null;
    function stateBadge(s) { return badge(t("state." + s), s === "done" ? "ok" : (s === "fix" ? "bad" : (s === "wait" ? "" : "warn"))); }
    function clip(text) {
      if (!navigator.clipboard) { say(t("copy.failed"), "bad"); return; }
      navigator.clipboard.writeText(text).then(function () { say(t("copy.copied"), "ok"); }, function () { say(t("copy.failed"), "bad"); });
    }
    function reload() { return api("/api/connect").then(render); }
    function poll() {
      clearTimeout(timer);
      api("/api/connect/signin").then(function (s) {
        if (s.state === "waiting") { timer = setTimeout(poll, 1500); return; }
        reload().then(function () {
          if (s.state === "done") say(t(s.code, s.params), "ok");
          else if (s.state === "error") say(t(s.code, s.params), "bad");
        });
      }).catch(function (e) { say(errMsg(e), "bad"); });
    }
    function render(d) {
      var rows = {};
      d.steps.forEach(function (r) { rows[r.id] = r; });
      function result(id) {
        var r = rows[id];
        return h("p", { class: "step-result", role: "status" }, stateBadge(r.state), h("span", null, t(r.code, r.params)));
      }
      function card(n, id, body) {
        return h("div", { class: "step " + rows[id].state },
          h("div", { class: "rail" }, h("span", { class: "num", "aria-hidden": "true" }, rows[id].state === "done" ? "✓" : String(n)), h("span", { class: "line" })),
          h("section", { class: "card", "aria-labelledby": "h-s-" + id },
            h("p", { class: "eyebrow" }, t("connect.step_n", { n: n, total: 5 })),
            h("h2", { id: "h-s-" + id }, t("step." + id + ".title")),
            h("p", { class: "muted" }, t("step." + id + ".how")), body, result(id)));
      }
      var cid = h("input", { id: "cid", autocomplete: "off", spellcheck: "false", inputmode: "text" });
      var sec = h("input", { id: "csec", type: "password", autocomplete: "off", spellcheck: "false" });
      var s = d.signin || { state: "idle" };
      var waiting = s.state === "waiting";
      var signBtn = h("button", { type: "button", disabled: waiting || rows.credentials.state !== "done", onclick: function (ev) {
        busy(ev.target, api("/api/connect/signin/start", {}).then(function (snap) { render(Object.assign({}, d, { signin: snap })); poll(); })).catch(function () {});
      } }, t("connect.signin"));
      var enabled = d.posting_mode !== "copy";
      var canEnable = rows.signin.state === "done" || rows.signin.code === "res.signin.soon";
      var reauth = d.reauth && d.reauth.expires_on
        ? t("reauth.text", { date: d.reauth.expires_on, warn: d.reauth.warn_from }) : t("reauth.none");
      wrap.replaceChildren(
        h("section", { class: "card hero intro" },
          h("p", null, t("connect.intro")),
          h("p", { class: "muted" }, t("connect.nopassword")),
          h("p", { class: "muted small" }, t("connect.copy_first"))),
        h("div", { class: "steps" },
          card(1, "app", h("div", { class: "row" },
            h("a", { href: d.portal_url, target: "_blank", rel: "noopener noreferrer" }, t("connect.open_portal"), " ", arrow()))),
          card(2, "products", h("ul", { class: "pill-list" }, d.products.map(function (p) { return h("li", { dir: "ltr" }, p); }))),
          card(3, "redirect", h("div", { class: "row" },
            h("code", { class: "redirect", dir: "ltr" }, d.redirect_uri),
            h("button", { type: "button", class: "ghost", onclick: function () { clip(d.redirect_uri); } }, t("connect.copy_address")))),
          card(4, "credentials", h("div", { class: "field" },
            h("label", { for: "cid" }, t("connect.field_id"), cid),
            h("label", { for: "csec" }, t("connect.field_secret"), sec),
            h("div", { class: "row" }, h("button", { type: "button", onclick: function (ev) {
              var id = cid.value, key = sec.value; sec.value = "";
              busy(ev.target, api("/api/connect/credentials", { client_id: id, key: key }).then(render), t("connect.saved")).catch(function () {});
            } }, t("connect.save"))))),
          card(5, "signin", h("div", null,
            h("div", { class: "row" }, signBtn,
              h("button", { type: "button", class: "ghost", onclick: function () { reload().catch(function (e) { say(errMsg(e), "bad"); }); } }, t("connect.recheck"))),
            waiting ? h("p", { class: "muted" }, t(s.code, s.params), " ",
              s.url ? h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer" }, t("connect.open_signin")) : null) : null,
            s.state === "error" ? h("p", { class: "status bad" }, t(s.code, s.params)) : null))),
        h("div", { class: "grid two" },
          h("section", { class: "card", "aria-labelledby": "h-re" }, h("div", { class: "card-h" }, h("h2", { id: "h-re" }, t("reauth.title"))),
            h("p", null, reauth)),
          h("section", { class: "card", "aria-labelledby": "h-api" }, h("div", { class: "card-h" }, h("h2", { id: "h-api" }, t("api.title")),
            badge(tv("mode.", d.posting_mode), enabled ? "ok" : "")),
            h("p", { class: "muted small" }, t("api.text")),
            h("div", { class: "row" },
              !enabled ? h("button", { type: "button", disabled: !canEnable, onclick: function (ev) {
                busy(ev.target, api("/api/connect/enable-api", {}).then(render), t("api.done")).catch(function () {});
              } }, t("api.enable")) : null,
              enabled ? h("button", { type: "button", class: "ghost", onclick: function (ev) {
                busy(ev.target, api("/api/connect/copy-mode", {}).then(render), t("api.back_done")).catch(function () {});
              } }, t("api.back")) : null),
            !enabled && !canEnable ? h("p", { class: "muted small" }, t("api.needs_signin")) : null)));
      if (waiting) { clearTimeout(timer); timer = setTimeout(poll, 1500); }
    }
    mount(wrap);
    reload().catch(fail);
  }

  function fail(e) { mount(h("p", { class: "card" }, t("fail.load") + " " + errMsg(e))); say(errMsg(e), "bad"); }

  // ---- Optional update notice: asked first thing on load; never installs anything by itself
  function updateBanner() {
    var box = document.getElementById("update");
    api("/api/update").then(function (u) {
      if (!u || !u.notify) return;
      var news = h("div", { class: "update-news", hidden: true }, (u.news || []).map(function (r) {
        return h("div", null, h("h3", null, r.tag), h("pre", null, (r.body || "").trim() || t("upd.nonotes")));
      }));
      var how = h("div", { class: "update-how", hidden: true },
        h("p", null, t("upd.method", { label: u.method.label })),
        u.method.command ? h("p", null, t("upd.run"), " ", h("code", null, u.method.command)) : null,
        u.method.note ? h("p", null, u.method.note) : null,
        u.method.id === "desktop" ? h("a", { href: u.url, target: "_blank", rel: "noopener noreferrer" }, t("upd.download")) : null);
      function toggle(el) { el.hidden = !el.hidden; }
      function dismiss(kind, msg) {
        api("/api/update/" + kind, {}).then(function () { box.hidden = true; say(msg, "ok"); }).catch(function (e) { say(e.message, "bad"); });
      }
      box.replaceChildren(
        h("p", null, h("strong", null, t("upd.available", { latest: u.latest })), " ", h("span", { class: "muted" }, t("upd.have", { current: u.current }))),
        h("div", { class: "row" },
          h("button", { type: "button", class: "ghost", id: "upd-news", onclick: function () { toggle(news); } }, tf("upd.news", "What's new")),
          h("button", { type: "button", id: "upd-how", onclick: function () { toggle(how); } }, tf("upd.update", "Update")),
          h("button", { type: "button", class: "ghost", onclick: function () { dismiss("skip", t("upd.skipped")); } }, tf("upd.skip", "Skip this version")),
          h("button", { type: "button", class: "ghost", onclick: function () { dismiss("later", t("upd.remind")); } }, tf("upd.later", "Later"))),
        news, how);
      box.hidden = false;
    }).catch(function () { /* offline or off: no banner, nothing to say */ });
  }
  loadStrings().then(function () {
    applyI18n();
    var title = SCREEN === "connect" ? t("connect.title") : t("title." + SCREEN);
    document.getElementById("title").textContent = title;
    document.getElementById("subtitle").textContent = t("sub." + SCREEN);
    document.title = title + " - Profile-Wrap";
    updateBanner();
    ({ home: home, board: board, providers: providers, build: build, settings: settings, connect: connect })[SCREEN]();
  });
})();

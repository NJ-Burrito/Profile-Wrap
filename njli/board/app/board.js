"use strict";
/* Review board UI. Every string from the server is added as a text node, never parsed as markup. */
(function () {
  const TOKEN = document.querySelector('meta[name="njli-token"]').content;
  const TABS = ["posts", "comments", "connect", "profile", "metrics", "settings"];
  const S = {
    tab: location.hash.slice(1) || "posts", lang: localStorage.getItem("njliLang") || "", strings: {}, fallback: {},
    state: null, etag: null, filter: "all", slug: null, detail: null, detailKey: "", data: {}, notes: {},
    stale: false, offline: false, rejectArmed: null, busy: new Set(),
  };
  if (!TABS.includes(S.tab)) S.tab = "posts";

  // ------------------------------------------------------------ helpers
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "value") el.value = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return el;
  }
  function t(key, vars) {
    let s = S.strings[key] ?? S.fallback[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace("{" + k + "}", v);
    return s;
  }
  function when(iso) {
    if (!iso) return t("time.none");
    const d = new Date(iso);
    return isNaN(d) ? iso : new Intl.DateTimeFormat(S.lang || "en", { dateStyle: "medium", timeStyle: "short" }).format(d);
  }
  function toast(msg) {
    const el = document.getElementById("toast");
    el.textContent = msg; el.classList.add("show");
    clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.remove("show"), 4200);
  }
  function apiError(code, body) {
    const key = "err." + (body && body.error);
    const known = S.strings[key] || S.fallback[key];
    return known ? t(key) : (body && body.message) || t("err.generic", { code });
  }

  async function api(path, opts) {
    opts = opts || {};
    const headers = {};
    let init = { method: opts.method || "GET", headers, cache: "no-store" };
    if (init.method === "POST") {
      headers["Content-Type"] = "application/json";
      headers["X-Review-Token"] = TOKEN;
      init.body = JSON.stringify(opts.body || {});
    }
    if (opts.etag) headers["If-None-Match"] = opts.etag;
    let res;
    try { res = await fetch(path, init); } catch (e) { S.offline = true; renderBanners(); throw e; }
    S.offline = false;
    if (res.status === 403 && init.method === "POST") { S.stale = true; renderBanners(); }
    if (res.status === 304) return { code: 304, body: null, etag: opts.etag };
    let body = null;
    try { body = await res.json(); } catch (e) { body = null; }
    return { code: res.status, body, etag: res.headers.get("ETag") };
  }
  async function post(path, body, okMsg) {
    const r = await api(path, { method: "POST", body });
    if (r.code === 200) {
      if (okMsg) toast(t(okMsg));
      (r.body.warnings || []).forEach((w) => toast(t("warn." + w.code) !== "warn." + w.code ? t("warn." + w.code) : w.message));
    } else toast(apiError(r.code, r.body));
    await refresh(true);
    return r;
  }

  // ------------------------------------------------------------ i18n
  async function loadStrings(lang) {
    const get = async (l) => { try { return await (await fetch("/i18n/" + l + ".json")).json(); } catch (e) { return {}; } };
    S.fallback = await get("en");
    S.strings = lang === "en" ? S.fallback : await get(lang);
    S.lang = lang;
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    document.getElementById("app-title").textContent = t("app.title");
    document.title = t("app.title");
    document.getElementById("lang").value = lang;
  }

  // ------------------------------------------------------------ chrome
  function renderTabs() {
    const nav = document.getElementById("tabs");
    nav.replaceChildren(...TABS.map((id) => {
      const n = id === "posts" && S.state ? S.state.total : (id === "comments" && S.data.pending) ? S.data.pending.pending.length : (id === "connect" && S.data.connect) ? S.data.connect.connect.length : null;
      return h("button", { class: "tab", role: "tab", "aria-selected": String(S.tab === id), onclick: () => switchTab(id) },
        t("tab." + id), n !== null ? h("span", { class: "count", text: String(n) }) : null);
    }));
  }
  function renderBanners() {
    const box = document.getElementById("banners");
    const items = [];
    if (S.stale) items.push(h("div", { class: "banner stale", role: "alert" }, t("banner.stale"), h("button", { class: "btn primary", onclick: () => location.reload() }, t("banner.reload"))));
    if (S.state && S.state.pause && S.state.pause.length) items.push(h("div", { class: "banner bad" }, t("banner.paused", { kinds: S.state.pause.join(", ") })));
    if (S.state && S.state.degraded) items.push(h("div", { class: "banner warn" }, t("banner.degraded", { n: S.state.problems.length })));
    if (S.state && S.state.config_problem) items.push(h("div", { class: "banner warn" }, t("banner.config", { problem: S.state.config_problem })));
    const tk = S.data.settings && S.data.settings.token;
    if (tk && (tk.status === "warn" || tk.status === "fail")) items.push(h("div", { class: "banner " + (tk.status === "fail" ? "bad" : "warn") }, t("banner.token", { detail: tk.detail }), tk.hint ? h("code", { text: tk.hint }) : null));
    for (const n of (S.state && S.state.notifications || []).slice(0, 1)) items.push(h("div", { class: "banner" }, h("strong", { text: n.title }), " ", n.message));
    box.replaceChildren(...items);
    const live = document.getElementById("live");
    live.textContent = S.offline ? t("live.offline") : t("live.on");
    live.className = "live" + (S.offline ? " bad" : "");
  }
  function switchTab(id) { S.tab = id; location.hash = id; render(); loadTab(); }

  // ------------------------------------------------------------ posts tab
  function badge(kind, text) { return h("span", { class: "badge " + kind, text: text ?? kind }); }
  function postsView() {
    const st = S.state;
    if (!st) return h("div", { class: "empty" }, t("loading"));
    if (!st.total) return h("div", { class: "empty" }, h("h2", { text: t("posts.empty.title") }), h("p", { text: t("posts.empty.body") }));
    const statuses = ["all", ...Object.keys(st.counts)];
    const chips = h("div", { class: "chips", role: "group", "aria-label": t("posts.filter") }, statuses.map((s) =>
      h("button", { class: "chip", "aria-pressed": String(S.filter === s), onclick: () => { S.filter = s; render(); } },
        s === "all" ? t("posts.all", { n: st.total }) : t("status." + s) + " " + st.counts[s])));
    const posts = st.posts.filter((p) => S.filter === "all" || p.status === S.filter);
    const list = h("div", { class: "list" }, posts.map((p) => h("button", { class: "row", "aria-current": String(p.slug === S.slug), onclick: () => openPost(p.slug) },
      h("span", { class: "title", text: p.title }),
      h("span", { class: "meta" }, badge(p.status, t("status." + p.status)), p.gate ? badge(p.gate.toLowerCase(), t("gate." + p.gate.toLowerCase())) : null, h("span", { text: when(p.scheduled_at) }), p.format ? h("span", { text: p.format }) : null))));
    return h("div", { class: "split" }, h("div", {}, chips, list), h("div", { id: "detail" }, detailView()));
  }
  async function openPost(slug) {
    S.slug = slug; S.rejectArmed = null; S.detail = null; S.detailKey = "";
    render();
    await loadDetail();
  }
  async function loadDetail() {
    if (!S.slug) return;
    const r = await api("/api/draft/" + encodeURIComponent(S.slug));
    if (r.code === 200) {
      const key = JSON.stringify(r.body);
      if (key !== S.detailKey) { S.detail = r.body; S.detailKey = key; const box = document.getElementById("detail"); if (box && !isTyping(box)) box.replaceChildren(detailView()); }
    } else { S.detail = null; }
  }
  function isTyping(box) { return box.contains(document.activeElement) && document.activeElement.tagName === "TEXTAREA"; }
  function detailView() {
    const d = S.detail;
    if (!S.slug) return h("div", { class: "empty" }, t("posts.pick"));
    if (!d) return h("div", { class: "empty" }, t("loading"));
    const persona = (S.state && S.state.persona) || {};
    const dir = d.rtl ? "rtl" : "ltr";
    const initials = (persona.name || "?").split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
    const avatar = h("div", { class: "avatar" }, h("span", { text: initials }));
    const img = h("img", { src: "/avatar", alt: "", onerror: () => img.remove() });
    avatar.prepend(img);
    const preview = h("section", { class: "card", "aria-label": t("posts.preview") },
      h("div", { class: "post-head" }, avatar, h("div", {}, h("div", { class: "who", text: persona.name || t("posts.you") }), h("div", { class: "sub", text: [persona.role, when(d.scheduled_at)].filter(Boolean).join(" · ") }))),
      h("div", { class: "caption", dir, lang: d.lang, text: d.caption || t("posts.nocaption") }),
      d.media.length ? h("div", { class: "media" }, d.media.map((u) => h("img", { src: u, alt: d.alt || d.title, loading: "lazy" }))) : null,
      h("div", { class: "reactions", "aria-hidden": "true" }, h("span", { text: t("li.like") }), h("span", { text: t("li.comment") }), h("span", { text: t("li.repost") }), h("span", { text: t("li.send") })),
      d.first_comment ? h("div", { class: "fc", dir }, h("div", { class: "sub", text: t("posts.firstcomment") }), h("div", { class: "caption", text: d.first_comment })) : null,
      d.alt ? h("div", { class: "sub" }, h("strong", { text: t("posts.alt") + ": " }), d.alt) : null);

    const g = d.gates;
    const gatePanel = h("section", { class: "card" }, h("h3", { text: t("gate.title") }),
      g ? h("div", {}, badge((g.summary || "").toLowerCase(), t("gate." + (g.summary || "").toLowerCase())), " ", h("span", { class: "sub", text: when(g.checked_at) }),
        g.fails.length ? h("ul", { class: "plain" }, g.fails.map((x) => h("li", { class: "fail", text: x }))) : null,
        g.warnings.length ? h("ul", { class: "plain" }, g.warnings.map((x) => h("li", { class: "warn", text: x }))) : null,
        g.overrides.length ? h("div", {}, h("div", { class: "sub", text: t("gate.overrides") }), h("ul", { class: "plain" }, g.overrides.map((o) => h("li", { text: [o.check, o.token, o.reason].filter(Boolean).join(": ") })))) : null)
        : h("div", { class: "sub", text: t("gate.none") }),
      d.degraded ? h("div", { class: "sub", text: t("detail.degraded") }) : null);

    const councilPanel = d.seats.length ? h("section", { class: "card" }, h("h3", { text: t("council.title") }),
      h("ul", { class: "plain" }, d.seats.map((s) => h("li", {}, badge(s.verdict, t("verdict." + s.verdict)), " ", s.seat,
        s.blockers.length ? h("ul", { class: "plain" }, s.blockers.map((b) => h("li", { class: "fail", text: [b.where, b.quote, b.fix].filter(Boolean).join(" | ") }))) : null)))) : null;

    const histPanel = d.history.length ? h("section", { class: "card" }, h("h3", { text: t("history.title") }),
      h("ul", { class: "plain" }, d.history.slice().reverse().map((x) => h("li", { class: "sub", text: [when(x.at), x.action, x.to ? "→ " + x.to : "", x.gates || "", x.note || "", x.error || ""].filter(Boolean).join("  ") })))) : null;
    const revision = d.revision_note ? h("div", { class: "banner" }, h("strong", { text: t("detail.revnote") + ": " }), d.revision_note) : null;
    return h("div", {}, revision, preview, gatePanel, councilPanel, actionsView(d), histPanel);
  }
  function actionsView(d) {
    if (d.read_only) return h("section", { class: "card" }, h("div", { class: "sub", text: t("actions.readonly", { status: t("status." + d.status) }) }));
    const note = h("textarea", { "aria-label": t("actions.note"), placeholder: t("actions.note.ph"), value: S.notes[d.slug] || "", oninput: (e) => { S.notes[d.slug] = e.target.value; } });
    const armed = S.rejectArmed === d.slug;
    const allow = h("button", { class: "btn primary", disabled: !d.can.allow || S.busy.has("allow"), title: d.can.allow ? "" : t("actions.allow.no", { status: t("status." + d.status) }), onclick: () => act(d, "allow") }, t("actions.allow"));
    const reject = h("button", { class: "btn danger" + (armed ? " on" : ""), disabled: !d.can.reject, onclick: () => { if (!armed) { S.rejectArmed = d.slug; refreshDetailBox(); } else act(d, "reject"); } }, armed ? t("actions.reject.confirm") : t("actions.reject"));
    const improve = h("button", { class: "btn", disabled: !d.can.improve || !state_worker(), title: state_worker() ? "" : t("actions.improve.noworker"), onclick: () => act(d, "improve") }, t("actions.improve"));
    return h("section", { class: "card" }, h("h3", { text: t("actions.title") }), note, h("div", { class: "actions" }, allow, reject, improve),
      armed ? h("div", { class: "sub", text: t("actions.reject.hint") }) : null);
  }
  function state_worker() { return !(S.state && S.state.worker === false); }
  function refreshDetailBox() { const box = document.getElementById("detail"); if (box) box.replaceChildren(detailView()); }
  async function act(d, action) {
    const note = (S.notes[d.slug] || "").trim();
    if (action === "improve" && !note) { toast(t("err.note_required")); return; }
    S.busy.add(action);
    const r = await post("/api/decision", { slug: d.slug, action, note, confirm: action === "reject" }, "msg." + action);
    S.busy.delete(action);
    if (r.code === 200) { delete S.notes[d.slug]; S.rejectArmed = null; }
    if (r.code === 422 && r.body.fails) toast(r.body.fails[0]);
    await loadDetail(); refreshDetailBox();
  }

  // ------------------------------------------------------------ other tabs
  function copyBtn(text) { return h("button", { class: "btn", onclick: async () => { try { await navigator.clipboard.writeText(text); toast(t("copied")); } catch (e) { toast(t("copy.failed")); } } }, t("copy")); }
  function link(url, label) { return url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, label) : null; }

  function commentsView() {
    const p = S.data.pending;
    if (!p) return h("div", { class: "empty" }, t("loading"));
    if (!p.pending.length) return h("div", { class: "empty" }, h("h2", { text: t("comments.empty.title") }), h("p", { text: t("comments.empty.body") }));
    return h("div", {}, p.pending.map((c) => h("section", { class: "card" },
      h("div", { class: "sub", text: [t("kind." + c.kind), c.author, when(c.at)].filter(Boolean).join(" · ") }),
      h("div", { class: "copybox", dir: /^[؀-ۿ]/.test(c.text) ? "rtl" : "ltr", text: c.text }),
      c.gate ? h("div", { class: "sub", text: t("gate.title") + ": " + (c.gate.summary || "") }) : null,
      h("div", { class: "actions" }, copyBtn(c.text), link(c.url, t("open")), h("button", { class: "btn primary", onclick: () => post("/api/pending-done", { id: c.id, action: "done" }, "msg.done") }, t("done")), h("button", { class: "btn", onclick: () => post("/api/pending-done", { id: c.id, action: "skip" }, "msg.skipped") }, t("skip"))))));
  }
  function connectView() {
    const c = S.data.connect;
    if (!c) return h("div", { class: "empty" }, t("loading"));
    if (!c.connect.length) return h("div", { class: "empty" }, h("h2", { text: t("connect.empty.title") }), h("p", { text: t("connect.empty.body", { n: c.slots_max }) }));
    return h("div", {}, c.connect.map((r) => h("section", { class: "card" },
      h("h3", { text: r.name }), h("div", { class: "sub", text: [t("connect.action." + r.action), r.score ? t("connect.score", { n: r.score }) : "", r.why].filter(Boolean).join(" · ") }),
      r.note ? h("div", { class: "copybox", text: r.note }) : null,
      h("div", { class: "actions" }, r.note ? copyBtn(r.note) : null, link(r.profile_url, t("connect.open")), link(r.post_url, t("connect.post")),
        h("button", { class: "btn primary", onclick: () => post("/api/connect-done", { id: r.id, action: "done" }, "msg.sent") }, t("connect.sent")),
        h("button", { class: "btn", onclick: () => post("/api/connect-done", { id: r.id, action: "skip" }, "msg.skipped") }, t("skip"))))));
  }
  function profileView() {
    const p = S.data.profile;
    if (!p) return h("div", { class: "empty" }, t("loading"));
    if (p.empty) return h("div", { class: "empty" }, h("h2", { text: t("profile.empty.title") }), h("p", { text: t("profile.empty.body") }), h("p", {}, h("code", { text: "njli profile ingest --paste" }), " → ", h("code", { text: "njli profile score" }), " → ", h("code", { text: "njli profile steps build" })), p.degraded ? h("p", { class: "sub", text: p.problem }) : null);
    const sections = [...new Set(p.steps.map((s) => s.section))];
    return h("div", {}, h("div", { class: "banner" }, t("profile.progress", { done: p.done, total: p.total })),
      sections.map((sec) => h("div", {}, sec ? h("h3", { text: sec }) : null, p.steps.filter((s) => s.section === sec).map((s) => h("section", { class: "card step" + (s.done ? " done" : "") },
        h("h3", { text: s.title }), s.action ? h("div", { class: "sub", text: s.action }) : null, s.text ? h("div", { class: "copybox", text: s.text }) : null,
        s.open_refused ? h("div", { class: "sub", text: t("profile.open.refused") }) : null,
        h("div", { class: "actions" }, s.text ? copyBtn(s.text) : null, link(s.open, t("open")),
          h("button", { class: "btn" + (s.done ? "" : " primary"), onclick: () => post("/api/profile-done", { id: s.id, done: !s.done }) }, s.done ? t("profile.undo") : t("done"))))))));
  }
  function metricsView() {
    const m = S.data.metrics;
    if (!m) return h("div", { class: "empty" }, t("loading"));
    const snap = m.snapshots.length ? m.snapshots[m.snapshots.length - 1] : null;
    const nums = snap ? Object.entries(snap).filter(([, v]) => typeof v === "number" || typeof v === "string") : [];
    return h("div", { class: "grid2" },
      h("section", { class: "card" }, h("h3", { text: t("metrics.queue") }), m.queued.length ? h("ul", { class: "plain" }, m.queued.map((q) => h("li", { text: when(q.scheduled_at) + " · " + q.title }))) : h("div", { class: "sub", text: t("metrics.queue.none") })),
      h("section", { class: "card" }, h("h3", { text: t("metrics.latest") }), nums.length ? h("table", {}, nums.map(([k, v]) => h("tr", {}, h("th", { text: k }), h("td", { text: String(v) })))) : h("div", { class: "sub", text: t("metrics.none") }),
        h("div", { class: "sub", text: t("metrics.comments", { n: m.comments_total }) })),
      h("section", { class: "card" }, h("h3", { text: t("metrics.posted") }), m.posts.length ? h("table", {}, h("tr", {}, [t("metrics.col.title"), t("metrics.col.state"), t("metrics.col.when"), ""].map((x) => h("th", { text: x }))),
        m.posts.slice().reverse().map((p) => h("tr", {}, h("td", { text: p.title || p.slug }), h("td", { text: p.state || "" }), h("td", { text: when(p.posted_at) }), h("td", {}, link(p.url, t("open")))))) : h("div", { class: "sub", text: t("metrics.posted.none") })));
  }
  function settingsView() {
    const s = S.data.settings;
    if (!s) return h("div", { class: "empty" }, t("loading"));
    const all = s.pause.includes("all");
    const kindBtn = (kind) => h("button", { class: "btn", onclick: () => post("/api/pause", { kind, paused: !s.pause.includes(kind) }, "msg.pause") }, (s.pause.includes(kind) ? t("settings.resume") : t("settings.pause")) + " " + t("kind." + kind));
    return h("div", { class: "grid2" },
      h("section", { class: "card" }, h("h3", { text: t("settings.kill") }), h("p", { class: "sub", text: t("settings.kill.body") }),
        h("button", { class: "pause-big" + (all ? " resume" : ""), onclick: () => post("/api/pause", { kind: "all", paused: !all }, "msg.pause") }, all ? t("settings.resume.all") : t("settings.pause.all")),
        h("div", { class: "actions" }, kindBtn("posting"), kindBtn("comments"))),
      h("section", { class: "card" }, h("h3", { text: t("settings.modes") }), h("table", {}, ["posting", "comments", "reading"].map((k) => h("tr", {}, h("th", { text: t("settings.mode." + k) }), h("td", { text: String(s.modes[k]) }))), h("tr", {}, h("th", { text: t("settings.mode.likes") }), h("td", { text: String(s.modes.likes) }))),
        (s.modes.notes || []).length ? h("ul", { class: "plain" }, s.modes.notes.map((n) => h("li", { class: "warn", text: n }))) : null),
      h("section", { class: "card" }, h("h3", { text: t("settings.acks") }), h("table", {}, Object.entries(s.acks).map(([k, v]) => h("tr", {}, h("th", { text: k }), h("td", {}, badge(v.status === "valid" ? "pass" : v.status === "missing" ? "warn" : "fail", t("ack." + v.status)), " ", h("span", { class: "sub", text: v.reason }))))),
        h("p", { class: "sub", text: t("settings.acks.how") })),
      h("section", { class: "card" }, h("h3", { text: t("settings.doctor") }), s.doctor.checks.length ? h("ul", { class: "plain" }, s.doctor.checks.map((c) => h("li", { class: c.status === "fail" ? "fail" : c.status === "warn" ? "warn" : "" }, badge(c.status === "pass" ? "pass" : c.status === "fail" ? "fail" : "warn", c.status), " ", c.name, ": ", c.detail, c.hint ? h("div", { class: "sub", text: c.hint }) : null))) : h("div", { class: "sub", text: s.doctor.error || t("settings.doctor.none") })),
      h("section", { class: "card" }, h("h3", { text: t("settings.board") }), h("table", {}, h("tr", {}, h("th", { text: t("settings.board.addr") }), h("td", { text: "127.0.0.1:" + s.board.port })), h("tr", {}, h("th", { text: t("settings.board.ws") }), h("td", { text: s.workspace }))),
        h("ul", { class: "plain" }, (s.notifications || []).map((n) => h("li", { class: "sub", text: [when(n.at), n.title, n.message].join(" · ") })))));
  }

  // ------------------------------------------------------------ render + load
  const VIEWS = { posts: postsView, comments: commentsView, connect: connectView, profile: profileView, metrics: metricsView, settings: settingsView };
  function render() {
    renderTabs(); renderBanners();
    const view = document.getElementById("view");
    if (S.tab === "posts" && document.getElementById("detail") && isTyping(view)) return;
    view.replaceChildren(VIEWS[S.tab]());
  }
  const ENDPOINTS = { comments: ["pending", "/api/pending"], connect: ["connect", "/api/connect"], profile: ["profile", "/api/profile"], metrics: ["metrics", "/api/metrics"], settings: ["settings", "/api/settings"] };
  async function loadTab() {
    const ep = ENDPOINTS[S.tab];
    if (ep) { const r = await api(ep[1]); if (r.code === 200) { S.data[ep[0]] = r.body; render(); } }
    if (S.tab === "posts") await loadDetail();
  }
  async function refresh(force) {
    try {
      const r = await api("/api/state", { etag: force ? null : S.etag });
      if (r.code === 200) { S.state = r.body; S.etag = r.etag; if (!S.slug && S.state.posts.length) { /* keep the list neutral until the user picks one */ } }
      if (r.code === 200 || force) render(); else renderBanners();
      await loadTab();
    } catch (e) { /* offline banner already shown */ }
  }

  async function boot() {
    const first = await (await fetch("/api/health")).json().catch(() => ({}));
    let lang = S.lang;
    if (!lang) { const r = await api("/api/state"); S.state = r.body; S.etag = r.etag; lang = (r.body && r.body.ui_language) || "en"; }
    await loadStrings(lang === "ar" ? "ar" : "en");
    document.getElementById("lang").addEventListener("change", async (e) => { localStorage.setItem("njliLang", e.target.value); await loadStrings(e.target.value); render(); });
    window.addEventListener("hashchange", () => { const id = location.hash.slice(1); if (TABS.includes(id) && id !== S.tab) { S.tab = id; render(); loadTab(); } });
    await refresh(true);
    setInterval(() => { if (!document.hidden) refresh(false); }, 5000);
    S.health = first;
  }
  boot();
})();

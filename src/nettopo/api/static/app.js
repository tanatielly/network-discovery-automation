/* NetTopo - interface web */
(function () {
  "use strict";
  var esc = window.NetTopoViewer.esc;
  var main = document.getElementById("main");
  var historyEl = document.getElementById("history");
  var current = { id: null, ws: null, viewer: null };
  var STATUS_PT = { queued: "na fila", running: "em execução", finished: "concluída", failed: "falhou" };

  function token() { try { return localStorage.getItem("nettopo_token") || ""; } catch (e) { return ""; } }
  function api(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    if (token()) opts.headers.Authorization = "Bearer " + token();
    return fetch(path, opts).then(function (r) {
      if (r.status === 401) {
        var t = window.prompt("Esta API exige um token (NETTOPO_API_TOKEN):");
        if (t) { try { localStorage.setItem("nettopo_token", t); } catch (e) { /* ignore */ } return api(path, opts); }
      }
      if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) {
        var d = b.detail; throw new Error(typeof d === "string" ? d : JSON.stringify(d || r.statusText));
      });
      return r.json();
    });
  }
  function closeWs() { if (current.ws) { try { current.ws.close(); } catch (e) { /* ignore */ } current.ws = null; } }
  function clearMain() {
    closeWs();
    if (current.viewer) { current.viewer.destroy(); current.viewer = null; }
    main.innerHTML = "";
  }
  function fmt(s) { try { return new Date(s).toLocaleString(); } catch (e) { return s || ""; } }

  /* ------------------------------------------------------------------ histórico */
  var pollTimer = null;
  function loadHistory() {
    return api("/api/discoveries").then(function (list) {
      if (!list.length) { historyEl.innerHTML = '<li class="nt-muted">Nenhuma descoberta ainda. Clique em “Demo” para testar.</li>'; }
      else historyEl.innerHTML = list.map(function (d) {
        var st = d.stats || {};
        return '<li data-id="' + esc(d.id) + '" class="' + (d.id === current.id ? "active" : "") + '"><div class="t"><span>' +
          esc(d.name || (d.seeds || []).join(", ")) + '</span><span class="ui-status ' + esc(d.status) + '">' + esc(STATUS_PT[d.status] || d.status) +
          '</span></div><div class="s">' + esc(fmt(d.created_at)) + (st.devices ? " · " + st.collected + " coletados · " + st.links + " links" : "") +
          (d.demo ? " · demo" : "") + "</div></li>";
      }).join("");
      clearTimeout(pollTimer);
      if (list.some(function (d) { return d.status === "running" || d.status === "queued"; })) pollTimer = setTimeout(loadHistory, 4000);
      return list;
    }).catch(function (e) { historyEl.innerHTML = '<li class="ui-error">' + esc(e.message) + "</li>"; });
  }
  historyEl.addEventListener("click", function (e) {
    var li = e.target.closest("li[data-id]");
    if (li) select(li.getAttribute("data-id"));
  });

  /* ------------------------------------------------------------------ seleção */
  function select(id) {
    current.id = id;
    Array.prototype.forEach.call(historyEl.children, function (li) { li.classList.toggle("active", li.getAttribute("data-id") === id); });
    try { history.replaceState(null, "", "#" + id); } catch (e) { /* ignore */ }
    api("/api/discoveries/" + id).then(function (d) {
      if (d.status === "finished") showResult(d);
      else if (d.status === "failed") { clearMain(); main.innerHTML = '<div class="ui-progress"><h1>Descoberta falhou</h1><p class="ui-error">' + esc(d.error || "") + "</p></div>"; }
      else showProgress(d);
    }).catch(function (e) { clearMain(); main.innerHTML = '<div class="ui-progress ui-error">' + esc(e.message) + "</div>"; });
  }

  function showResult(d) {
    clearMain();
    var bar = document.createElement("div");
    bar.className = "ui-exports";
    bar.innerHTML = '<span class="lbl">Exportar:</span>' + [["html", "HTML interativo"], ["drawio", "draw.io"], ["xlsx", "Excel"], ["md", "Markdown (.zip)"], ["json", "JSON"]]
      .map(function (f) { return '<a class="nt-btn" data-fmt="' + f[0] + '" href="#">' + f[1] + "</a>"; }).join("") +
      '<span class="ui-sep"></span><button class="nt-btn" type="button" data-del>Excluir</button>';
    bar.addEventListener("click", function (e) {
      var a = e.target.closest("[data-fmt]");
      if (a) { e.preventDefault(); download(d.id, a.getAttribute("data-fmt")); }
      if (e.target.closest("[data-del]")) {
        if (window.confirm("Excluir esta descoberta?")) api("/api/discoveries/" + d.id, { method: "DELETE" }).then(function () { clearMain(); current.id = null; loadHistory(); showForm(); });
      }
    });
    var root = document.createElement("div");
    main.appendChild(bar);
    main.appendChild(root);
    root.innerHTML = '<div class="nt-empty">Carregando topologia…</div>';
    api("/api/discoveries/" + d.id + "/view").then(function (data) {
      current.viewer = window.NetTopoViewer.mount(root, data, { deepLink: false });
    }).catch(function (e) { root.innerHTML = '<div class="nt-empty ui-error">' + esc(e.message) + "</div>"; });
  }

  function download(id, fmt) {
    var headers = token() ? { Authorization: "Bearer " + token() } : {};
    fetch("/api/discoveries/" + id + "/export/" + fmt, { headers: headers }).then(function (r) {
      if (!r.ok) throw new Error("falha ao exportar");
      var name = (r.headers.get("content-disposition") || "").match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/);
      return r.blob().then(function (b) { return { blob: b, name: name ? decodeURIComponent(name[1]) : "topologia." + fmt }; });
    }).then(function (x) {
      var a = document.createElement("a");
      a.href = URL.createObjectURL(x.blob); a.download = x.name; document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    }).catch(function (e) { window.alert(e.message); });
  }

  /* ------------------------------------------------------------------ progresso */
  function showProgress(d) {
    clearMain();
    var box = document.createElement("div");
    box.className = "ui-progress";
    box.innerHTML = "<h1>Descobrindo " + esc(d.name || (d.seeds || []).join(", ")) + "…</h1>" +
      '<div class="nt-stats"><div class="nt-stat"><b data-k="done">0</b><span>coletados</span></div>' +
      '<div class="nt-stat"><b data-k="queued">0</b><span>na fila</span></div>' +
      '<div class="nt-stat err"><b data-k="failed">0</b><span>falhas</span></div></div>' +
      '<div class="ui-bar"><span style="width:2%"></span></div><div class="ui-log" aria-live="polite"></div>';
    main.appendChild(box);
    var log = box.querySelector(".ui-log"), barEl = box.querySelector(".ui-bar > span");
    var c = { done: 0, failed: 0, queued: 0 };
    function upd() {
      Object.keys(c).forEach(function (k) { box.querySelector('[data-k="' + k + '"]').textContent = c[k]; });
      var total = Math.max(c.queued, c.done + c.failed, 1);
      barEl.style.width = Math.max(2, Math.min(100, 100 * (c.done + c.failed) / total)) + "%";
    }
    function line(cls, text) {
      var s = document.createElement("div"); s.className = cls; s.textContent = text; log.appendChild(s);
      log.scrollTop = log.scrollHeight;
    }
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var ws = new WebSocket(proto + "//" + location.host + "/api/discoveries/" + d.id + "/events" + (token() ? "?token=" + encodeURIComponent(token()) : ""));
    current.ws = ws;
    ws.onmessage = function (m) {
      var ev = JSON.parse(m.data);
      if (ev.type === "started") { c.queued += (ev.seeds || []).length; line("q", "Sementes: " + (ev.seeds || []).join(", ")); }
      else if (ev.type === "queued") { c.queued++; line("q", "  + fila: " + ev.target + (ev.hostname ? " (" + ev.hostname + ")" : "") + " nível " + ev.depth); }
      else if (ev.type === "device_done") { c.done++; line("ok", "OK  " + (ev.hostname || ev.target) + "  " + ev.target + "  " + (ev.vendor || "?") + " " + (ev.model || "") + "  via " + (ev.via || []).join(",") + "  · " + ev.neighbors + " vizinhos"); }
      else if (ev.type === "device_failed") { c.failed++; line("err", "ERRO " + ev.target + "  " + (ev.reason || "")); }
      else if (ev.type === "finished") { line("ok", "Concluído: " + JSON.stringify({ equipamentos: ev.stats.devices, links: ev.stats.links })); }
      else if (ev.type === "error") { line("err", "Falha: " + ev.message); }
      else if (ev.type === "closed") { closeWs(); loadHistory().then(function () { if (current.id === d.id) select(d.id); }); }
      upd();
    };
    ws.onerror = function () { line("err", "Conexão de progresso perdida; atualizando…"); setTimeout(function () { select(d.id); }, 3000); };
  }

  /* ------------------------------------------------------------------ formulário */
  function credRow(values) {
    var node = document.getElementById("tpl-cred").content.firstElementChild.cloneNode(true);
    values = values || {};
    Object.keys(values).forEach(function (k) { var f = node.querySelector('[data-f="' + k + '"]'); if (f) f.value = values[k]; });
    function sync() {
      var t = node.querySelector('[data-f="type"]').value, v = node.querySelector('[data-f="version"]').value;
      node.querySelectorAll("[data-for]").forEach(function (f) {
        var w = f.getAttribute("data-for"), show;
        if (w === "snmp") show = t === "snmp";
        else if (w === "snmp-v12") show = t === "snmp" && v !== "3";
        else if (w === "snmp-v3") show = t === "snmp" && v === "3";
        else if (w === "user") show = t !== "snmp" || v === "3";
        else if (w === "pass") show = t !== "snmp";
        else show = t === w;
        f.hidden = !show;
      });
    }
    node.addEventListener("change", sync);
    node.querySelector("[data-remove]").addEventListener("click", function () { node.remove(); });
    sync();
    return node;
  }

  function lines(v) { return (v || "").split(/[\n,;]+/).map(function (s) { return s.trim(); }).filter(Boolean); }

  function showForm() {
    clearMain();
    current.id = null;
    Array.prototype.forEach.call(historyEl.children, function (li) { li.classList.remove("active"); });
    main.appendChild(document.getElementById("tpl-form").content.cloneNode(true));
    var form = document.getElementById("discovery-form"), creds = document.getElementById("creds");
    creds.appendChild(credRow({ type: "ssh" }));
    creds.appendChild(credRow({ type: "snmp", version: "2c" }));
    document.getElementById("add-cred").addEventListener("click", function () { creds.appendChild(credRow({ type: "ssh" })); });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var f = form.elements, err = document.getElementById("form-error");
      err.textContent = "";
      var methods = ["rest", "netconf", "ssh", "snmp"].filter(function (m) { return f["m_" + m].checked; });
      var body = {
        name: f.name.value || null, seeds: lines(f.seeds.value),
        scope: { include: lines(f.include.value), exclude: lines(f.exclude.value) },
        max_depth: +f.max_depth.value, concurrency: +f.concurrency.value, timeout: +f.timeout.value, methods: methods,
        follow: { routing: f.f_routing.checked, arp: f.f_arp.checked },
        collect: { mac_table: f.c_mac.checked },
        credentials: Array.prototype.map.call(creds.children, function (row) {
          var c = {};
          row.querySelectorAll("[data-f]").forEach(function (x) { if (!x.hidden && x.value !== "") c[x.getAttribute("data-f")] = x.value; });
          if (c.port) c.port = +c.port;
          return c;
        }).filter(function (c) { return c.username || c.community || c.token; })
      };
      if (!body.seeds.length) { err.textContent = "Informe ao menos uma semente."; return; }
      if (!methods.length) { err.textContent = "Selecione ao menos um método de coleta."; return; }
      api("/api/discoveries", { method: "POST", body: JSON.stringify(body) }).then(function (r) {
        return loadHistory().then(function () { select(r.id); });
      }).catch(function (e2) { err.textContent = e2.message; });
    });
  }

  document.getElementById("btn-new").addEventListener("click", showForm);
  document.getElementById("btn-demo").addEventListener("click", function () {
    api("/api/demo", { method: "POST" }).then(function (r) { return loadHistory().then(function () { select(r.id); }); })
      .catch(function (e) { window.alert(e.message); });
  });

  loadHistory().then(function (list) {
    var hash = location.hash.replace("#", "");
    if (hash) select(hash);
    else if (list && list.length && list[0].status === "finished") select(list[0].id);
    else showForm();
  });
})();

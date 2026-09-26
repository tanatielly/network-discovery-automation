/* NetTopoViewer - relatório interativo (diagrama + documentação) a partir do JSON da topologia. */
(function () {
  "use strict";

  var ROLE_PT = { router: "Roteador", l3switch: "Switch L3", "switch": "Switch", firewall: "Firewall",
    wireless_controller: "Controladora Wi-Fi", ap: "Access Point", server: "Servidor/Host", phone: "Telefone IP",
    external: "Externo", unknown: "Desconhecido" };
  var TIER_PT = { external: "Externo", edge: "Borda", security: "Segurança", core: "Núcleo", distribution: "Distribuição",
    access: "Acesso", endpoint: "Endpoint" };
  var KIND_PT = { physical: "Físico", l3: "L3 (sub-rede)", logical: "Lógico (roteamento)" };

  function esc(v) {
    if (v === null || v === undefined) return "";
    return String(v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function el(tag, attrs, html) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === "class") e.className = attrs[k]; else if (k.indexOf("on") === 0) e.addEventListener(k.slice(2), attrs[k]);
      else e.setAttribute(k, attrs[k]);
    });
    if (html !== undefined) e.innerHTML = html;
    return e;
  }
  var IF_SHORT = [[/^GigabitEthernet/i, "Gi"], [/^TenGigabitEthernet/i, "Te"], [/^XGigabitEthernet/i, "XGE"],
    [/^FortyGigabitEthernet/i, "Fo"], [/^HundredGigE/i, "Hu"], [/^TwentyFiveGigE/i, "Twe"], [/^FastEthernet/i, "Fa"],
    [/^Port-channel/i, "Po"], [/^Ethernet/i, "Eth"], [/^ten-gigabit-ethernet-/i, "tge-"], [/^gigabit-ethernet-/i, "ge-"]];
  function shortIf(n) {
    if (!n) return "";
    for (var i = 0; i < IF_SHORT.length; i++) if (IF_SHORT[i][0].test(n)) return n.replace(IF_SHORT[i][0], IF_SHORT[i][1]);
    return n;
  }
  function status(v) { return v === true ? '<span class="dot up"></span>up' : v === false ? '<span class="dot down"></span>down' : "—"; }
  function speed(m) { return !m ? "" : m >= 1000 ? (m / 1000) + " Gbps" : m + " Mbps"; }
  function fmtDate(s) { try { return new Date(s).toLocaleString(); } catch (e) { return s || ""; } }

  /* ------------------------------------------------------------------ tabela ordenável/filtrável */
  function dataTable(container, columns, rows, opts) {
    opts = opts || {};
    var state = { sort: opts.sort !== undefined ? opts.sort : null, dir: 1, q: "" };
    var bar = el("div", { class: "nt-filterbar" });
    var input = el("input", { class: "nt-input", type: "search", placeholder: "Filtrar…", "aria-label": "Filtrar tabela" });
    var count = el("span", { class: "nt-muted" });
    bar.appendChild(input); bar.appendChild(count);
    if (opts.extra) bar.appendChild(opts.extra);
    var wrap = el("div", { class: "nt-tablewrap" });
    var table = el("table", { class: "nt-table" });
    wrap.appendChild(table);
    container.appendChild(bar); container.appendChild(wrap);

    function val(r, c) { return typeof c.get === "function" ? c.get(r) : r[c.key]; }
    function render() {
      var q = state.q.toLowerCase();
      var list = rows.filter(function (r) {
        if (!q) return true;
        return columns.some(function (c) { var v = val(r, c); return v !== null && v !== undefined && String(v).toLowerCase().indexOf(q) >= 0; });
      });
      if (state.sort !== null) {
        var c = columns[state.sort];
        list.sort(function (a, b) {
          var x = val(a, c), y = val(b, c);
          if (typeof x === "number" && typeof y === "number") return (x - y) * state.dir;
          return String(x === undefined || x === null ? "" : x).localeCompare(String(y === undefined || y === null ? "" : y), undefined, { numeric: true }) * state.dir;
        });
      }
      var head = "<thead><tr>" + columns.map(function (c, i) {
        var s = state.sort === i ? (state.dir > 0 ? "asc" : "desc") : "";
        return '<th data-i="' + i + '"' + (s ? ' data-sort="' + s + '"' : "") + ">" + esc(c.title) + "</th>";
      }).join("") + "</tr></thead>";
      var body = "<tbody>" + list.map(function (r, i) {
        return '<tr data-r="' + rows.indexOf(r) + '"' + (opts.onRow ? ' class="clickable"' : "") + ">" + columns.map(function (c) {
          return "<td>" + (c.html ? c.html(r) : esc(val(r, c))) + "</td>";
        }).join("") + "</tr>";
      }).join("") + "</tbody>";
      table.innerHTML = head + body;
      count.textContent = list.length + " de " + rows.length;
    }
    table.addEventListener("click", function (e) {
      var th = e.target.closest("th");
      if (th) {
        var i = +th.getAttribute("data-i");
        state.dir = state.sort === i ? -state.dir : 1;
        state.sort = i; render(); return;
      }
      var tr = e.target.closest("tr[data-r]");
      if (tr && opts.onRow) opts.onRow(rows[+tr.getAttribute("data-r")]);
    });
    input.addEventListener("input", function () { state.q = input.value; render(); });
    render();
  }

  /* ------------------------------------------------------------------ viewer */
  function mount(root, data, opts) {
    opts = opts || {};
    root.innerHTML = "";
    var devices = data.devices || {};
    var links = data.links || [];
    var meta = data.meta || {};
    var stats = meta.stats || {};
    var devList = Object.keys(devices).map(function (k) { return devices[k]; });
    var failed = meta.failed_targets || {};
    var view = null;

    /* cabeçalho */
    if (opts.header !== false) {
      var head = el("div", { class: "nt-head" });
      var title = el("div", null, "<h1>" + esc(meta.name || "Topologia de rede") + "</h1>" +
        '<div class="nt-sub">Descoberta a partir de <span class="nt-mono">' + esc((meta.seeds || []).join(", ")) +
        "</span> · " + esc(fmtDate(meta.finished_at || meta.started_at)) +
        (stats.duration_s !== undefined ? " · " + esc(stats.duration_s) + " s" : "") + " · NetTopo " + esc(meta.tool_version || "") + "</div>");
      var st = el("div", { class: "nt-stats" });
      [["collected", "coletados"], ["stubs", "vistos por vizinhos"], ["physical_links", "links físicos"],
       ["l3_links", "links L3"], ["interfaces", "interfaces"]].forEach(function (p) {
        st.appendChild(el("div", { class: "nt-stat" }, "<b>" + esc(stats[p[0]] || 0) + "</b><span>" + p[1] + "</span>"));
      });
      st.appendChild(el("div", { class: "nt-stat" }, "<b>" + Object.keys(stats.by_vendor || {}).filter(function (v) { return v !== "Desconhecido"; }).length + "</b><span>fabricantes</span>"));
      if (stats.failed_targets) st.appendChild(el("div", { class: "nt-stat err" }, "<b>" + stats.failed_targets + "</b><span>falhas</span>"));
      head.appendChild(title); head.appendChild(st);
      root.appendChild(head);
    }

    /* abas */
    var tabs = [
      ["diagram", "Diagrama"], ["inventory", "Inventário", devList.length], ["links", "Links", links.length],
      ["interfaces", "Interfaces"], ["vlans", "VLANs"], ["neighbors", "Vizinhos"], ["routing", "IPs & Rotas"]
    ];
    if (Object.keys(failed).length) tabs.push(["failures", "Falhas", Object.keys(failed).length]);
    var tabbar = el("div", { class: "nt-tabs", role: "tablist" });
    var panels = {};
    var built = {};
    tabs.forEach(function (t, i) {
      var b = el("button", { class: "nt-tab", role: "tab", "aria-selected": i === 0 ? "true" : "false", "data-tab": t[0] },
        esc(t[1]) + (t[2] !== undefined ? '<span class="nt-count">' + t[2] + "</span>" : ""));
      b.addEventListener("click", function () { show(t[0]); });
      tabbar.appendChild(b);
      var p = el("div", { class: "nt-panel", role: "tabpanel" });
      p.hidden = i !== 0;
      panels[t[0]] = p;
    });
    root.appendChild(tabbar);
    Object.keys(panels).forEach(function (k) { root.appendChild(panels[k]); });

    function show(name) {
      Array.prototype.forEach.call(tabbar.children, function (b) { b.setAttribute("aria-selected", b.getAttribute("data-tab") === name ? "true" : "false"); });
      Object.keys(panels).forEach(function (k) { panels[k].hidden = k !== name; });
      if (!built[name]) { builders[name](panels[name]); built[name] = true; }
      if (name === "diagram" && view) view.cy.resize();
    }

    function devName(id) { var d = devices[id]; return d ? (d.hostname || d.mgmt_ip || d.id) : id; }
    function openDevice(id) { show("diagram"); if (view) view.focus(id); renderDetail(id, "node"); }

    /* painel de detalhe */
    var detail, diagramBox;
    function kv(pairs) {
      return '<dl class="nt-kv">' + pairs.filter(function (p) { return p[1] !== null && p[1] !== undefined && p[1] !== ""; })
        .map(function (p) { return "<dt>" + esc(p[0]) + "</dt><dd>" + (p[2] ? p[1] : esc(p[1])) + "</dd>"; }).join("") + "</dl>";
    }
    function renderDetail(id, kind) {
      if (!detail) return;
      if (!id) { detail.innerHTML = '<div class="nt-empty">Clique em um equipamento ou link para ver os detalhes.</div>'; return; }
      if (kind === "edge") {
        var l = links.filter(function (x) { return x.id === id; })[0];
        if (!l) return;
        detail.innerHTML = "<h2>Link " + esc(l.id) + "</h2>" +
          '<span class="nt-badge">' + esc(KIND_PT[l.kind] || l.kind) + "</span>" +
          kv([["Origem", devName(l.source)], ["Interface", l.source_interface], ["Destino", devName(l.target)],
              ["Interface", l.target_interface], ["Protocolos", (l.protocols || []).join(", ")], ["Sub-rede", l.subnet],
              ["Velocidade", speed(l.speed_mbps)], ["Agregação", l.lag]]);
        return;
      }
      var d = devices[id];
      if (!d) return;
      var h = "<h2>" + esc(d.hostname || d.mgmt_ip || d.id) + "</h2>";
      h += '<span class="nt-badge">' + esc(ROLE_PT[d.role] || d.role) + "</span>";
      if (d.tier) h += '<span class="nt-badge">' + esc(TIER_PT[d.tier] || d.tier) + "</span>";
      h += d.stub ? '<span class="nt-badge stub">não coletado</span>' : '<span class="nt-badge ok">coletado</span>';
      h += "<h3>Identificação</h3>" + kv([
        ["IP gerência", d.mgmt_ip], ["Fabricante", d.vendor], ["Sistema", d.os], ["Versão", d.os_version],
        ["Modelo", d.model], ["Serial", d.serial], ["Uptime", d.uptime], ["Local", d.location], ["Contato", d.contact],
        ["Chassis MAC", d.chassis_id], ["Coletado via", (d.collected_via || []).join(", ")],
        ["Descoberto por", d.discovered_from ? devName(d.discovered_from) : ""],
        ["Descrição", d.sys_description]]);
      var lk = links.filter(function (x) { return x.source === id || x.target === id; });
      if (lk.length) {
        h += "<h3>Conexões (" + lk.length + ")</h3><table class='nt-table'><tr><th>Local</th><th>Vizinho</th><th>Remota</th></tr>" +
          lk.map(function (x) {
            var me = x.source === id, other = me ? x.target : x.source;
            return "<tr title='" + esc((x.protocols || []).join(", ")) + "'><td class='nt-mono'>" + esc(shortIf(me ? x.source_interface : x.target_interface)) +
              "</td><td><a href='#' data-dev='" + esc(other) + "'>" + esc(devName(other)) + "</a></td><td class='nt-mono'>" +
              esc(shortIf(me ? x.target_interface : x.source_interface)) + "</td></tr>";
          }).join("") + "</table>";
      }
      var ifs = (d.interfaces || []).filter(function (i) { return (i.ipv4 && i.ipv4.length) || i.oper_up || i.description; });
      if (ifs.length) {
        h += "<h3>Interfaces (" + ifs.length + " de " + (d.interfaces || []).length + ")</h3><table class='nt-table'><tr><th>Nome</th><th>IP</th><th>Status</th><th>Vel.</th></tr>" +
          ifs.slice(0, 80).map(function (i) {
            return "<tr><td class='nt-mono' title='" + esc(i.description) + "'>" + esc(shortIf(i.name)) + "</td><td class='nt-mono'>" + esc((i.ipv4 || []).join(" ")) +
              "</td><td>" + status(i.oper_up) + "</td><td>" + esc(speed(i.speed_mbps)) + "</td></tr>";
          }).join("") + "</table>";
      }
      if (d.vlans && d.vlans.length) h += "<h3>VLANs</h3><div>" + d.vlans.map(function (v) { return '<span class="nt-badge">' + v.id + (v.name ? " " + esc(v.name) : "") + "</span>"; }).join("") + "</div>";
      if (d.errors && d.errors.length) h += "<h3>Avisos</h3><ul>" + d.errors.map(function (e) { return "<li class='nt-muted'>" + esc(e) + "</li>"; }).join("") + "</ul>";
      detail.innerHTML = h;
    }

    var builders = {
      diagram: function (p) {
        if (typeof cytoscape === "undefined" || !window.TopoView) {
          p.innerHTML = '<div class="nt-empty">Não foi possível carregar o Cytoscape.js (sem acesso à internet?). As abas de documentação continuam disponíveis.</div>';
          return;
        }
        diagramBox = el("div", { class: "nt-diagram" });
        var wrap = el("div", { class: "nt-canvas-wrap" });
        var canvas = el("div", { class: "nt-canvas" });
        var tb = el("div", { class: "nt-toolbar" });
        var search = el("input", { class: "nt-input", type: "search", placeholder: "Buscar host, IP, modelo…", "aria-label": "Buscar" });
        var layout = el("select", { class: "nt-select", "aria-label": "Layout" },
          '<option value="hierarchical">Hierárquico</option><option value="cose">Orgânico</option>' +
          '<option value="breadthfirst">Árvore</option><option value="concentric">Concêntrico</option>');
        var filters = { kinds: { physical: true, l3: true, logical: true }, showStubs: true, showLabels: true };
        function toggle(label, get, set) {
          var id = "t" + Math.random().toString(36).slice(2);
          var t = el("label", { class: "nt-toggle", for: id }, '<input type="checkbox" id="' + id + '"' + (get() ? " checked" : "") + "> " + esc(label));
          t.querySelector("input").addEventListener("change", function (e) { set(e.target.checked); view.setFilter(filters); });
          return t;
        }
        tb.appendChild(search); tb.appendChild(layout);
        tb.appendChild(toggle("L3", function () { return true; }, function (v) { filters.kinds.l3 = v; }));
        tb.appendChild(toggle("Roteamento", function () { return true; }, function (v) { filters.kinds.logical = v; }));
        tb.appendChild(toggle("Não coletados", function () { return true; }, function (v) { filters.showStubs = v; }));
        tb.appendChild(toggle("Portas", function () { return true; }, function (v) { filters.showLabels = v; }));
        var fit = el("button", { class: "nt-btn", type: "button" }, "Ajustar");
        var png = el("button", { class: "nt-btn", type: "button" }, "PNG");
        var det = el("button", { class: "nt-btn", type: "button", title: "Mostrar/ocultar painel" }, "Painel");
        tb.appendChild(fit); tb.appendChild(png); tb.appendChild(det);
        var legend = el("div", { class: "nt-legend" });
        var roles = {};
        devList.forEach(function (d) { roles[d.role] = true; });
        var lg = (data.graph.legend || {}).roles || {};
        legend.innerHTML = '<div class="row">' + Object.keys(lg).filter(function (r) { return roles[r]; }).map(function (r) {
          return '<span class="it"><img alt="" src="' + lg[r].icon + '">' + esc(lg[r].label) + "</span>";
        }).join("") + '</div><div class="row" style="margin-top:4px"><span class="it"><span class="ln"></span>Físico</span>' +
          '<span class="it"><span class="ln l3"></span>L3</span><span class="it"><span class="ln logical"></span>Roteamento</span>' +
          '<span class="it nt-muted">tracejado/itálico = não coletado</span></div>';
        wrap.appendChild(canvas); wrap.appendChild(tb); wrap.appendChild(legend);
        detail = el("div", { class: "nt-detail" });
        diagramBox.appendChild(wrap); diagramBox.appendChild(detail);
        p.appendChild(diagramBox);
        view = window.TopoView.create(canvas, data.graph, { onSelect: renderDetail });
        renderDetail(null);
        search.addEventListener("input", function () { view.search(search.value); });
        layout.addEventListener("change", function () { view.setLayout(layout.value); });
        fit.addEventListener("click", function () { view.fit(); });
        det.addEventListener("click", function () { diagramBox.classList.toggle("nodetail"); setTimeout(function () { view.cy.resize(); }, 50); });
        png.addEventListener("click", function () {
          var a = document.createElement("a");
          a.href = view.png(); a.download = (meta.name || "topologia").replace(/\W+/g, "_") + ".png"; a.click();
        });
        detail.addEventListener("click", function (e) {
          var a = e.target.closest("[data-dev]");
          if (a) { e.preventDefault(); openDevice(a.getAttribute("data-dev")); }
        });
        if (window.matchMedia) {
          window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { view.refreshTheme(); });
        }
      },
      inventory: function (p) {
        dataTable(p, [
          { title: "Hostname", get: function (d) { return d.hostname || d.id; } },
          { title: "IP", key: "mgmt_ip" },
          { title: "Papel", get: function (d) { return ROLE_PT[d.role] || d.role; } },
          { title: "Camada", get: function (d) { return TIER_PT[d.tier] || d.tier || ""; } },
          { title: "Fabricante", key: "vendor" }, { title: "Sistema", key: "os" }, { title: "Versão", key: "os_version" },
          { title: "Modelo", key: "model" }, { title: "Serial", key: "serial" },
          { title: "Coleta", get: function (d) { return d.stub ? "vizinho" : (d.collected_via || []).join(", "); } },
          { title: "Interfaces", get: function (d) { return (d.interfaces || []).length; } }
        ], devList, { onRow: function (d) { openDevice(d.id); }, sort: 0 });
      },
      links: function (p) {
        dataTable(p, [
          { title: "ID", key: "id" }, { title: "Origem", get: function (l) { return devName(l.source); } },
          { title: "Interface", key: "source_interface" }, { title: "Destino", get: function (l) { return devName(l.target); } },
          { title: "Interface", key: "target_interface" }, { title: "Tipo", get: function (l) { return KIND_PT[l.kind] || l.kind; } },
          { title: "Protocolos", get: function (l) { return (l.protocols || []).join(", "); } },
          { title: "Velocidade", get: function (l) { return speed(l.speed_mbps); } }, { title: "Sub-rede", key: "subnet" },
          { title: "LAG", key: "lag" }
        ], links, { onRow: function (l) { show("diagram"); if (view) { view.focus(l.source); renderDetail(l.id, "edge"); } } });
      },
      interfaces: function (p) {
        var rows = [];
        devList.forEach(function (d) { if (!d.stub) (d.interfaces || []).forEach(function (i) { rows.push(Object.assign({ dev: d.hostname || d.id, devId: d.id }, i)); }); });
        dataTable(p, [
          { title: "Equipamento", key: "dev" }, { title: "Interface", key: "name" }, { title: "Descrição", key: "description" },
          { title: "IPv4", get: function (i) { return (i.ipv4 || []).join(" "); } },
          { title: "Admin", get: function (i) { return i.admin_up === true ? "up" : i.admin_up === false ? "down" : ""; } },
          { title: "Oper", get: function (i) { return i.oper_up === true ? "up" : i.oper_up === false ? "down" : ""; }, html: function (i) { return status(i.oper_up); } },
          { title: "Velocidade", get: function (i) { return speed(i.speed_mbps); } }, { title: "MTU", key: "mtu" },
          { title: "MAC", key: "mac" }, { title: "LAG", key: "parent" }, { title: "VLAN", key: "access_vlan" }
        ], rows, { onRow: function (i) { openDevice(i.devId); } });
      },
      vlans: function (p) {
        var map = {};
        devList.forEach(function (d) { (d.vlans || []).forEach(function (v) {
          var m = map[v.id] || (map[v.id] = { id: v.id, names: {}, devs: [] });
          if (v.name) m.names[v.name] = true; m.devs.push(d.hostname || d.id);
        }); });
        var rows = Object.keys(map).map(function (k) { var m = map[k]; return { id: m.id, name: Object.keys(m.names).join(" / "), count: m.devs.length, devs: m.devs.join(", ") }; });
        if (!rows.length) { p.innerHTML = '<div class="nt-empty">Nenhuma VLAN coletada.</div>'; return; }
        dataTable(p, [{ title: "VLAN", key: "id" }, { title: "Nome", key: "name" }, { title: "Equipamentos", key: "count" },
          { title: "Presente em", key: "devs" }], rows, { sort: 0 });
      },
      neighbors: function (p) {
        var rows = [];
        devList.forEach(function (d) { (d.neighbors || []).forEach(function (n) { rows.push(Object.assign({ dev: d.hostname || d.id, devId: d.id }, n)); }); });
        dataTable(p, [
          { title: "Equipamento", key: "dev" }, { title: "Protocolo", key: "protocol" }, { title: "Interface local", key: "local_interface" },
          { title: "Vizinho", key: "remote_hostname" }, { title: "Interface remota", key: "remote_interface" },
          { title: "IP", key: "remote_mgmt_ip" }, { title: "Plataforma", key: "remote_platform" },
          { title: "Capacidades", get: function (n) { return (n.remote_capabilities || []).join(", "); } },
          { title: "ASN", key: "remote_asn" }, { title: "Estado", key: "state" }
        ], rows, { onRow: function (n) { openDevice(n.devId); } });
      },
      routing: function (p) {
        var ips = [];
        devList.forEach(function (d) { (d.interfaces || []).forEach(function (i) { (i.ipv4 || []).forEach(function (a) {
          ips.push({ ip: a, dev: d.hostname || d.id, devId: d.id, itf: i.name, desc: i.description, vrf: i.vrf });
        }); }); });
        p.appendChild(el("h3", null, "Endereçamento IPv4"));
        dataTable(p, [{ title: "Endereço", key: "ip" }, { title: "Equipamento", key: "dev" }, { title: "Interface", key: "itf" },
          { title: "VRF", key: "vrf" }, { title: "Descrição", key: "desc" }], ips, { onRow: function (r) { openDevice(r.devId); } });
        var routes = [];
        devList.forEach(function (d) { (d.routes || []).forEach(function (r) { routes.push(Object.assign({ dev: d.hostname || d.id }, r)); }); });
        p.appendChild(el("h3", { style: "margin-top:22px" }, "Tabela de rotas"));
        dataTable(p, [{ title: "Equipamento", key: "dev" }, { title: "Prefixo", key: "prefix" }, { title: "Next-hop", key: "next_hop" },
          { title: "Interface", key: "interface" }, { title: "Protocolo", key: "protocol" }, { title: "VRF", key: "vrf" }], routes);
      },
      failures: function (p) {
        var rows = Object.keys(failed).map(function (k) { return { target: k, reason: failed[k] }; });
        dataTable(p, [{ title: "Alvo", key: "target" }, { title: "Motivo", key: "reason" }], rows);
      }
    };
    builders.diagram(panels.diagram);
    built.diagram = true;
    // Deep-link: #tab=inventory ou #device=<id>
    if (opts.deepLink !== false) {
      var tabMatch = /tab=(\w+)/.exec(location.hash), devMatch = /device=([^&]+)/.exec(location.hash);
      if (devMatch && devices[decodeURIComponent(devMatch[1])]) setTimeout(function () { openDevice(decodeURIComponent(devMatch[1])); }, 0);
      else if (tabMatch && panels[tabMatch[1]]) show(tabMatch[1]);
    }
    return { show: show, openDevice: openDevice, view: function () { return view; },
      destroy: function () { if (view) view.destroy(); root.innerHTML = ""; } };
  }

  window.NetTopoViewer = { mount: mount, esc: esc };
})();

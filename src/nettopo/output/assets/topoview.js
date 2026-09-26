/* TopoView - renderização da topologia com Cytoscape.js (compartilhado entre relatório HTML e UI web). */
(function () {
  "use strict";

  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }

  function edgeWidth(e) {
    var s = e.data("speed") || 0;
    if (!s) return 2;
    return 1.6 + Math.log10(Math.max(s, 100) / 100) * 1.3;
  }

  function buildStyle() {
    var fg = cssVar("--fg", "#1f2328");
    var muted = cssVar("--muted", "#656d76");
    var bg = cssVar("--bg", "#ffffff");
    var line = cssVar("--edge", "#8c959f");
    var accent = cssVar("--accent", "#0969da");
    return [
      { selector: "node", style: {
          "background-color": bg, "background-opacity": 0, "background-image": "data(icon)",
          "background-fit": "contain", "background-clip": "none", "width": 44, "height": 44, "shape": "round-rectangle",
          "label": "data(label)", "text-valign": "bottom", "text-halign": "center", "text-margin-y": 6,
          "font-size": 11, "font-family": "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", "color": fg,
          "text-wrap": "wrap", "text-max-width": 140, "text-background-color": bg, "text-background-opacity": 0.85,
          "text-background-padding": 2, "text-background-shape": "round-rectangle", "border-width": 0 } },
      { selector: "node.stub", style: { "opacity": 0.72, "font-style": "italic" } },
      { selector: "node:selected", style: { "border-width": 3, "border-color": accent, "border-style": "solid",
          "background-opacity": 0 } },
      { selector: "node.match", style: { "border-width": 3, "border-color": "#bf8700", "border-style": "double" } },
      { selector: "node.faded, edge.faded", style: { "opacity": 0.15 } },
      { selector: "edge", style: {
          "width": edgeWidth, "line-color": line, "curve-style": "bezier", "control-point-step-size": 28,
          "source-label": "data(sourceLabel)", "target-label": "data(targetLabel)",
          "source-text-offset": 34, "target-text-offset": 34, "font-size": 9, "color": muted,
          "text-background-color": bg, "text-background-opacity": 0.9, "text-background-padding": 1,
          "text-rotation": "autorotate" } },
      { selector: "edge.l3", style: { "line-style": "dashed", "line-color": "#0969da" } },
      { selector: "edge.logical", style: { "line-style": "dotted", "line-color": "#bf8700" } },
      { selector: "edge:selected", style: { "line-color": accent, "width": 5 } },
      { selector: ".nolabels edge", style: { "source-label": "", "target-label": "" } },
      { selector: "edge.hidden, node.hidden", style: { "display": "none" } }
    ];
  }

  function create(container, graph, opts) {
    opts = opts || {};
    var cy = cytoscape({
      container: container,
      elements: [].concat(graph.elements.nodes, graph.elements.edges),
      layout: { name: "preset", padding: 40 },
      style: buildStyle(),
      wheelSensitivity: 0.25,
      minZoom: 0.05,
      maxZoom: 4
    });
    var presetPositions = {};
    cy.nodes().forEach(function (n) { presetPositions[n.id()] = Object.assign({}, n.position()); });

    cy.on("tap", "node", function (e) { if (opts.onSelect) opts.onSelect(e.target.id(), "node"); });
    cy.on("tap", "edge", function (e) { if (opts.onSelect) opts.onSelect(e.target.id(), "edge"); });
    cy.on("tap", function (e) { if (e.target === cy && opts.onSelect) opts.onSelect(null); });
    cy.on("mouseover", "node", function (e) {
      var n = e.target, hood = n.closedNeighborhood();
      cy.elements().not(hood).addClass("faded");
    });
    cy.on("mouseout", "node", function () { cy.elements().removeClass("faded"); });

    var api = {
      cy: cy,
      setLayout: function (name) {
        if (name === "hierarchical") {
          cy.layout({ name: "preset", positions: function (n) { return presetPositions[n.id()]; },
                      animate: true, animationDuration: 400, padding: 40 }).run();
        } else if (name === "breadthfirst") {
          var roots = cy.nodes().filter(function (n) { return ["external", "edge"].indexOf(n.data("tier")) >= 0; });
          cy.layout({ name: "breadthfirst", roots: roots.length ? roots : undefined, spacingFactor: 1.1,
                      animate: true, animationDuration: 400, padding: 40 }).run();
        } else if (name === "concentric") {
          var order = { external: 7, edge: 6, security: 5, core: 4, distribution: 3, access: 2, endpoint: 1 };
          cy.layout({ name: "concentric", concentric: function (n) { return order[n.data("tier")] || 0; },
                      levelWidth: function () { return 1; }, minNodeSpacing: 40, animate: true,
                      animationDuration: 400, padding: 40 }).run();
        } else {
          cy.layout({ name: "cose", animate: true, animationDuration: 500, nodeRepulsion: 90000,
                      idealEdgeLength: 110, padding: 40 }).run();
        }
      },
      search: function (text) {
        cy.nodes().removeClass("match");
        text = (text || "").trim().toLowerCase();
        if (!text) return 0;
        var m = cy.nodes().filter(function (n) {
          var d = n.data();
          return [d.id, d.hostname, d.ip, d.vendor, d.model, d.roleLabel].join(" ").toLowerCase().indexOf(text) >= 0;
        });
        m.addClass("match");
        if (m.length) cy.animate({ fit: { eles: m, padding: 120 } }, { duration: 350 });
        return m.length;
      },
      focus: function (id) {
        var n = cy.getElementById(id);
        if (!n || !n.length) return;
        cy.elements().unselect();
        n.select();
        cy.animate({ center: { eles: n }, zoom: Math.max(cy.zoom(), 1.1) }, { duration: 350 });
      },
      setFilter: function (f) {
        cy.batch(function () {
          cy.edges().forEach(function (e) {
            e.toggleClass("hidden", f.kinds && f.kinds[e.data("kind")] === false);
          });
          cy.nodes().forEach(function (n) {
            n.toggleClass("hidden", f.showStubs === false && n.data("stub"));
          });
        });
        container.classList.toggle("nolabels", f.showLabels === false);
        cy.style().selector("edge").style({
          "source-label": f.showLabels === false ? "" : "data(sourceLabel)",
          "target-label": f.showLabels === false ? "" : "data(targetLabel)"
        }).update();
      },
      refreshTheme: function () { cy.style().fromJson(buildStyle()).update(); },
      fit: function () { cy.animate({ fit: { padding: 40 } }, { duration: 300 }); },
      png: function () { return cy.png({ full: true, scale: 2, bg: cssVar("--bg", "#ffffff") }); },
      destroy: function () { cy.destroy(); }
    };
    return api;
  }

  window.TopoView = { create: create };
})();

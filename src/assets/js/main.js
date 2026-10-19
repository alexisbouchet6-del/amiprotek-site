/**
 * AMIPROTEK : animation de la baie de brassage (page d'accueil).
 *
 * Les ports sont de vrais liens HTML : sans JavaScript, ils restent
 * utilisables. Ce script ajoute les câbles (SVG), les branche un par un au
 * chargement, puis allume les voyants de liaison. Il respecte le réglage
 * « réduire les animations » du système.
 */
(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const STAGGER_MS = 120;
  const PLUG_DELAY_MS = 200;
  const CABLE_MS = 750;
  const BUNDLE_SPACING = 9;
  const BUNDLE_POSITION = 0.8; // le faisceau sort aux 4/5 de la largeur

  const panel = document.querySelector("[data-panel]");
  if (!panel) return;

  const svg = panel.querySelector("[data-cables]");
  const rack = panel.querySelector(".panel__rack");
  const ports = Array.from(panel.querySelectorAll("[data-port]"));
  if (!svg || !rack || ports.length === 0) return;

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let cables = [];
  let animated = false;
  let frame = 0;

  /** Couleur de câble d'un port, lue sur sa classe .cable-<couleur>. */
  const cableClass = (port) =>
    Array.from(port.classList).find((name) => name.startsWith("cable-")) || "";

  /**
   * Calcule le tracé de chaque câble à partir de la position réelle des ports.
   * Une rangée : les câbles partent des fiches, devant la baie.
   * Plusieurs rangées (mobile) : ils sortent sous la baie, derrière elle.
   */
  function draw() {
    const box = panel.getBoundingClientRect();
    const rackBottom = rack.getBoundingClientRect().bottom - box.top;
    const rows = [...new Set(ports.map((p) => Math.round(p.getBoundingClientRect().top)))]
      .sort((a, b) => a - b);
    const front = rows.length === 1;

    svg.classList.toggle("is-front", front);
    svg.setAttribute("viewBox", `0 0 ${box.width} ${box.height}`);
    svg.replaceChildren();

    const count = ports.length;
    // Plusieurs rangées : faisceau centré, plus lisible sur un écran étroit.
    const bundleX = box.width * (front ? BUNDLE_POSITION : 0.5);
    const endY = box.height + 10;

    // Point de départ de chaque câble.
    const starts = ports.map((port) => {
      const jack = port.querySelector(".port__jack").getBoundingClientRect();
      const row = rows.indexOf(Math.round(port.getBoundingClientRect().top));
      const offset = front ? 0 : (row - (rows.length - 1) / 2) * 8;
      return {
        x: jack.left + jack.width / 2 - box.left + offset,
        y: front ? jack.bottom - box.top + 10 : rackBottom - 2,
      };
    });
    // Dans le faisceau, les câbles gardent leur ordre gauche-droite : aucun croisement.
    const rank = starts
      .map((start, index) => ({ x: start.x, index }))
      .sort((a, b) => a.x - b.x)
      .reduce((acc, item, position) => ({ ...acc, [item.index]: position }), {});

    cables = ports.map((port, index) => {
      const { x, y: startY } = starts[index];
      const endX = bundleX + (rank[index] - (count - 1) / 2) * BUNDLE_SPACING;
      const height = endY - startY;

      const path = document.createElementNS(SVG_NS, "path");
      path.setAttribute(
        "d",
        `M ${x.toFixed(1)} ${startY.toFixed(1)} ` +
          `C ${x.toFixed(1)} ${(startY + height * 0.6).toFixed(1)}, ` +
          `${endX.toFixed(1)} ${(startY + height * 0.3).toFixed(1)}, ` +
          `${endX.toFixed(1)} ${endY.toFixed(1)}`
      );
      path.setAttribute("class", `cable ${cableClass(port)}`);
      svg.appendChild(path);
      return path;
    });

    // Après la première animation, un redimensionnement redessine sans rejouer.
    if (animated) {
      cables.forEach((path, index) => {
        if (ports[index].matches(":hover, :focus-visible")) path.classList.add("is-hot");
      });
    }
  }

  /** Branche les câbles un par un, puis allume les voyants. */
  function animate() {
    cables.forEach((path, index) => {
      const length = path.getTotalLength();
      path.style.strokeDasharray = `${length}`;
      path.style.strokeDashoffset = `${length}`;
    });

    // Force le navigateur à appliquer l'état initial avant la transition.
    svg.getBoundingClientRect();

    ports.forEach((port, index) => {
      const start = PLUG_DELAY_MS + index * STAGGER_MS;
      window.setTimeout(() => port.classList.add("is-plugged"), start);

      const path = cables[index];
      path.style.transition = `stroke-dashoffset ${CABLE_MS}ms cubic-bezier(0.22, 1, 0.36, 1) ${start + 150}ms`;
      path.style.strokeDashoffset = "0";

      window.setTimeout(() => port.classList.add("is-up"), start + 150 + CABLE_MS);
    });

    const total = PLUG_DELAY_MS + ports.length * STAGGER_MS + 150 + CABLE_MS;
    window.setTimeout(() => {
      animated = true;
      // Nettoie les styles d'animation pour que les redessins restent simples.
      cables.forEach((path) => {
        path.style.transition = "";
        path.style.strokeDasharray = "";
        path.style.strokeDashoffset = "";
      });
    }, total + 50);
  }

  function showStatic() {
    ports.forEach((port) => port.classList.add("is-plugged", "is-up"));
    animated = true;
  }

  // Survol ou focus d'un port : son câble ressort et son voyant clignote.
  ports.forEach((port, index) => {
    const on = () => cables[index] && cables[index].classList.add("is-hot");
    const off = () => cables[index] && cables[index].classList.remove("is-hot");
    port.addEventListener("pointerenter", on);
    port.addEventListener("pointerleave", off);
    port.addEventListener("focus", on);
    port.addEventListener("blur", off);
  });

  // Redessine quand la mise en page change (rotation, chargement de la police...).
  const observer = new ResizeObserver(() => {
    if (!animated) return;
    window.cancelAnimationFrame(frame);
    frame = window.requestAnimationFrame(draw);
  });
  observer.observe(panel);
  observer.observe(rack);

  if (reduceMotion) {
    draw();
    showStatic();
    return;
  }

  document.documentElement.classList.add("js-anim");
  const start = () => {
    draw();
    animate();
  };
  // Attend la police pour tracer les câbles depuis leur position définitive.
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(start, start);
  } else {
    start();
  }
})();

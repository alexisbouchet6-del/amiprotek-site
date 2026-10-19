/**
 * AMI TECH : interactions de la page d'accueil.
 *
 * 1. Baie réseau : les ports sont de vrais liens HTML, utilisables sans
 *    JavaScript. Ce script trace les câbles (SVG), les branche un par un au
 *    chargement, allume les voyants, puis fait descendre une impulsion rouge
 *    dans chaque câble. Au survol d'un port, l'impulsion repart.
 * 2. Carrousel d'avis : défilement natif (doigt, molette, clavier) complété
 *    par des boutons Précédent / Suivant.
 *
 * Le réglage « réduire les animations » du système est respecté. Aucune
 * propriété n'est écrite via l'attribut style (compatible avec la CSP).
 */
(() => {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------------------------ */
  /* 1. Baie réseau                                                     */
  /* ------------------------------------------------------------------ */
  const initPanel = () => {
    const SVG_NS = "http://www.w3.org/2000/svg";
    const STAGGER_MS = 110;
    const PLUG_DELAY_MS = 200;
    const CABLE_MS = 700;
    const PULSE_MS = 900;
    const PULSE_LENGTH = 34;
    const BUNDLE_SPACING = 7;
    const BUNDLE_POSITION = 0.8;

    const panel = document.querySelector("[data-panel]");
    if (!panel) return;
    const svg = panel.querySelector("[data-cables]");
    const rack = panel.querySelector(".panel__rack");
    const ports = Array.from(panel.querySelectorAll("[data-port]"));
    if (!svg || !rack || ports.length === 0) return;

    let cables = [];
    let pulses = [];
    let animated = false;
    let frame = 0;

    /** Trace les câbles à partir de la position réelle des ports. */
    function draw() {
      const box = panel.getBoundingClientRect();
      const rackBottom = rack.getBoundingClientRect().bottom - box.top;
      const rows = [...new Set(ports.map((p) => Math.round(p.getBoundingClientRect().top)))].sort((a, b) => a - b);
      const front = rows.length === 1;

      svg.classList.toggle("is-front", front);
      svg.setAttribute("viewBox", `0 0 ${box.width} ${box.height}`);
      svg.replaceChildren();

      const count = ports.length;
      const bundleX = box.width * (front ? BUNDLE_POSITION : 0.5);
      const endY = box.height + 10;

      const starts = ports.map((port) => {
        const jack = port.querySelector(".port__jack").getBoundingClientRect();
        const row = rows.indexOf(Math.round(port.getBoundingClientRect().top));
        const offset = front ? 0 : (row - (rows.length - 1) / 2) * 8;
        return {
          x: jack.left + jack.width / 2 - box.left + offset,
          y: front ? jack.bottom - box.top + 10 : rackBottom - 2,
        };
      });
      // Les câbles gardent leur ordre gauche-droite dans le faisceau : aucun croisement.
      const order = starts.map((s, i) => ({ x: s.x, i })).sort((a, b) => a.x - b.x);
      const rank = new Map(order.map((item, position) => [item.i, position]));

      cables = [];
      pulses = [];
      starts.forEach(({ x, y }, index) => {
        const endX = bundleX + (rank.get(index) - (count - 1) / 2) * BUNDLE_SPACING;
        const height = endY - y;
        const d =
          `M ${x.toFixed(1)} ${y.toFixed(1)} ` +
          `C ${x.toFixed(1)} ${(y + height * 0.6).toFixed(1)}, ` +
          `${endX.toFixed(1)} ${(y + height * 0.3).toFixed(1)}, ` +
          `${endX.toFixed(1)} ${endY.toFixed(1)}`;

        const cable = document.createElementNS(SVG_NS, "path");
        cable.setAttribute("d", d);
        cable.setAttribute("class", "cable");
        const pulse = document.createElementNS(SVG_NS, "path");
        pulse.setAttribute("d", d);
        pulse.setAttribute("class", "pulse");
        svg.append(cable, pulse);
        cables.push(cable);
        pulses.push(pulse);
      });
    }

    /** Fait descendre une impulsion rouge le long d'un câble (Web Animations API). */
    function sendPulse(index, delay = 0) {
      const pulse = pulses[index];
      if (!pulse || reduceMotion || typeof pulse.animate !== "function") return;
      const length = pulse.getTotalLength();
      pulse.animate(
        [
          { strokeDasharray: `${PULSE_LENGTH} ${length}`, strokeDashoffset: PULSE_LENGTH, opacity: 1 },
          { strokeDasharray: `${PULSE_LENGTH} ${length}`, strokeDashoffset: -length, opacity: 1 },
        ],
        { duration: PULSE_MS, delay, easing: "cubic-bezier(0.45, 0, 0.55, 1)" }
      );
    }

    /** Branche les câbles un par un, allume les voyants, puis envoie une impulsion. */
    function animateIn() {
      ports.forEach((port, index) => {
        const start = PLUG_DELAY_MS + index * STAGGER_MS;
        const cable = cables[index];
        const length = cable.getTotalLength();
        window.setTimeout(() => port.classList.add("is-plugged"), start);
        cable.animate(
          [
            { strokeDasharray: `${length}`, strokeDashoffset: length },
            { strokeDasharray: `${length}`, strokeDashoffset: 0 },
          ],
          { duration: CABLE_MS, delay: start + 150, easing: "cubic-bezier(0.22, 1, 0.36, 1)", fill: "backwards" }
        );
        window.setTimeout(() => port.classList.add("is-up"), start + 150 + CABLE_MS);
        sendPulse(index, start + 150 + CABLE_MS + 100);
      });
      const total = PLUG_DELAY_MS + ports.length * STAGGER_MS + 150 + CABLE_MS;
      window.setTimeout(() => {
        animated = true;
      }, total);
    }

    ports.forEach((port, index) => {
      const on = () => {
        if (cables[index]) cables[index].classList.add("is-hot");
        if (animated) sendPulse(index);
      };
      const off = () => cables[index] && cables[index].classList.remove("is-hot");
      port.addEventListener("pointerenter", on);
      port.addEventListener("pointerleave", off);
      port.addEventListener("focus", on);
      port.addEventListener("blur", off);
    });

    // Redessine quand la mise en page change (rotation, chargement de la police...).
    if ("ResizeObserver" in window) {
      const observer = new ResizeObserver(() => {
        if (!animated) return;
        window.cancelAnimationFrame(frame);
        frame = window.requestAnimationFrame(draw);
      });
      observer.observe(panel);
      observer.observe(rack);
    }

    const canAnimate = !reduceMotion && typeof Element.prototype.animate === "function";
    if (!canAnimate) {
      draw();
      ports.forEach((port) => port.classList.add("is-plugged", "is-up"));
      animated = true;
      return;
    }

    document.documentElement.classList.add("js-anim");
    const start = () => {
      draw();
      animateIn();
    };
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(start, start);
    } else {
      start();
    }
  };

  /* ------------------------------------------------------------------ */
  /* 2. Carrousel d'avis                                                */
  /* ------------------------------------------------------------------ */
  const initCarousel = () => {
    const viewport = document.querySelector("[data-carousel]");
    const controls = document.querySelector("[data-carousel-controls]");
    if (!viewport || !controls) return;

    const track = viewport.querySelector("[data-track]");
    const items = Array.from(track.children);
    const prev = controls.querySelector("[data-prev]");
    const next = controls.querySelector("[data-next]");
    const counter = controls.querySelector("[data-count]");
    if (items.length < 2) return;

    /** Index du premier avis visible. */
    const currentIndex = () => {
      const left = viewport.getBoundingClientRect().left;
      let best = 0;
      let bestDistance = Infinity;
      items.forEach((item, index) => {
        const distance = Math.abs(item.getBoundingClientRect().left - left - parseFloat(getComputedStyle(viewport).paddingLeft));
        if (distance < bestDistance) {
          bestDistance = distance;
          best = index;
        }
      });
      return best;
    };

    const update = () => {
      const max = viewport.scrollWidth - viewport.clientWidth;
      const overflow = max > 4;
      controls.hidden = !overflow;
      prev.disabled = viewport.scrollLeft <= 4;
      next.disabled = viewport.scrollLeft >= max - 4;
      counter.textContent = `${currentIndex() + 1} / ${items.length}`;
    };

    const goTo = (index) => {
      const target = items[Math.max(0, Math.min(items.length - 1, index))];
      const offset = target.offsetLeft - track.offsetLeft;
      viewport.scrollTo({ left: offset, behavior: reduceMotion ? "auto" : "smooth" });
    };

    prev.addEventListener("click", () => goTo(currentIndex() - 1));
    next.addEventListener("click", () => goTo(currentIndex() + 1));
    viewport.addEventListener("keydown", (event) => {
      if (event.key === "ArrowRight") {
        event.preventDefault();
        goTo(currentIndex() + 1);
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        goTo(currentIndex() - 1);
      }
    });

    let ticking = false;
    viewport.addEventListener(
      "scroll",
      () => {
        if (ticking) return;
        ticking = true;
        window.requestAnimationFrame(() => {
          update();
          ticking = false;
        });
      },
      { passive: true }
    );
    window.addEventListener("resize", update);
    update();
  };

  initPanel();
  initCarousel();
})();

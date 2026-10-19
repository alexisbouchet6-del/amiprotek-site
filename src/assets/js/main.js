/**
 * AMI TECH : interactions de la page d'accueil.
 *
 * 1. Écosystème : les services sont de vrais liens HTML, utilisables sans
 *    JavaScript. Ce script trace les liaisons (SVG) entre le cœur AMI TECH et
 *    chaque service, puis y envoie une impulsion rouge qui allume le service.
 *    Au survol d'un service, l'impulsion repart.
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
  /* 1. Écosystème : liaisons entre le cœur AMI TECH et chaque service   */
  /* ------------------------------------------------------------------ */
  const initHub = () => {
    const SVG_NS = "http://www.w3.org/2000/svg";
    const STAGGER_MS = 160;
    const START_MS = 250;
    const PULSE_MS = 750;
    const PULSE_LENGTH = 26;

    const hub = document.querySelector("[data-hub]");
    if (!hub) return;
    const svg = hub.querySelector("[data-links]");
    const core = hub.querySelector("[data-core]");
    const nodes = Array.from(hub.querySelectorAll("[data-node]"));
    if (!svg || !core || nodes.length === 0) return;

    const body = svg.parentElement;
    let links = [];
    let pulses = [];
    let ready = false;
    let frame = 0;

    /** Trace une liaison courbe du cœur vers l'icône de chaque service. */
    function draw() {
      const box = body.getBoundingClientRect();
      const c = core.getBoundingClientRect();
      const cx = c.left + c.width / 2 - box.left;
      const cy = c.top + c.height / 2 - box.top;
      svg.setAttribute("viewBox", `0 0 ${box.width} ${box.height}`);
      svg.replaceChildren();
      links = [];
      pulses = [];
      nodes.forEach((node) => {
        const i = node.querySelector(".hub__icon").getBoundingClientRect();
        const x = i.left + i.width / 2 - box.left;
        const y = i.top + i.height / 2 - box.top;
        // Point de contrôle à mi-chemin, décalé verticalement : courbe douce.
        const mx = (cx + x) / 2;
        const d = `M ${cx.toFixed(1)} ${cy.toFixed(1)} Q ${mx.toFixed(1)} ${y.toFixed(1)} ${x.toFixed(1)} ${y.toFixed(1)}`;
        const link = document.createElementNS(SVG_NS, "path");
        link.setAttribute("d", d);
        link.setAttribute("class", "hub__link");
        const pulse = document.createElementNS(SVG_NS, "path");
        pulse.setAttribute("d", d);
        pulse.setAttribute("class", "hub__pulse");
        svg.append(link, pulse);
        links.push(link);
        pulses.push(pulse);
      });
    }

    /** Envoie une impulsion rouge du cœur vers un service (Web Animations API). */
    function sendPulse(index, delay = 0) {
      const pulse = pulses[index];
      if (!pulse || reduceMotion || typeof pulse.animate !== "function") return null;
      const length = pulse.getTotalLength();
      return pulse.animate(
        [
          { strokeDasharray: `${PULSE_LENGTH} ${length}`, strokeDashoffset: PULSE_LENGTH, opacity: 1 },
          { strokeDasharray: `${PULSE_LENGTH} ${length}`, strokeDashoffset: -length, opacity: 1 },
        ],
        { duration: PULSE_MS, delay, easing: "cubic-bezier(0.45, 0, 0.55, 1)" }
      );
    }

    nodes.forEach((node, index) => {
      const on = () => {
        if (links[index]) links[index].classList.add("is-hot");
        if (ready) sendPulse(index);
      };
      const off = () => links[index] && links[index].classList.remove("is-hot");
      node.addEventListener("pointerenter", on);
      node.addEventListener("pointerleave", off);
      node.addEventListener("focus", on);
      node.addEventListener("blur", off);
    });

    if ("ResizeObserver" in window) {
      const observer = new ResizeObserver(() => {
        window.cancelAnimationFrame(frame);
        frame = window.requestAnimationFrame(draw);
      });
      observer.observe(body);
    }

    const showAll = () => {
      nodes.forEach((node) => node.classList.add("is-up"));
      ready = true;
    };

    const start = () => {
      draw();
      if (reduceMotion || typeof Element.prototype.animate !== "function") {
        showAll();
        return;
      }
      // Les services s'allument un à un quand l'impulsion les atteint.
      nodes.forEach((node, index) => {
        const delay = START_MS + index * STAGGER_MS;
        sendPulse(index, delay);
        window.setTimeout(() => node.classList.add("is-up"), delay + PULSE_MS * 0.8);
      });
      window.setTimeout(() => {
        ready = true;
      }, START_MS + nodes.length * STAGGER_MS + PULSE_MS);
    };

    if (!reduceMotion) document.documentElement.classList.add("js-hub");
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

  initHub();
  initCarousel();
})();

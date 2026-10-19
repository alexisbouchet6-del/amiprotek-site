/**
 * AMI TECH : carrousel d'avis de la page d'accueil.
 *
 * Défilement natif (doigt, molette, clavier) complété par des boutons
 * Précédent / Suivant et un compteur. Le réglage « réduire les animations »
 * du système est respecté. Aucune propriété n'est écrite via l'attribut
 * style (compatible avec la CSP).
 */
(() => {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------------------------ */
  /* Carrousel d'avis                                                   */
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

  initCarousel();
})();

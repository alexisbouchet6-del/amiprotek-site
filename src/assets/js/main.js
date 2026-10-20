/**
 * AMI TECH : carrousel d'avis, calculateur antivirus et visionneuse des chantiers.
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

  /* ------------------------------------------------------------------ */
  /* Calculateur du tarif antivirus (page antivirus.html)               */
  /* ------------------------------------------------------------------ */
  function initPriceCalc() {
    const box = document.querySelector("[data-av-calc]");
    if (!box) return;
    const input = box.querySelector("[data-av-input]");
    const result = box.querySelector("[data-av-result]");
    const pro = Number(box.dataset.pro);
    const part = Number(box.dataset.part);
    const fmt = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", minimumFractionDigits: 0, maximumFractionDigits: 2 });

    const update = () => {
      const n = Math.floor(Number(input.value));
      if (!Number.isFinite(n) || n < 1 || n > 500) {
        result.textContent = "Indiquez un nombre de postes entre 1 et 500.";
        return;
      }
      const label = n === 1 ? "1 poste" : `${n} postes`;
      result.textContent = `${label} : ${fmt.format(pro * n)} HT par an (professionnels), ${fmt.format(part * n)} TTC par an (particuliers).`;
    };
    input.addEventListener("input", update);
    update();
  }

  /* ------------------------------------------------------------------ */
  /* Visionneuse de la page Nos chantiers                               */
  /* ------------------------------------------------------------------ */
  /* Sans JavaScript, chaque vignette reste un lien vers la photo complète. */
  function initLightbox() {
    const dialog = document.querySelector("[data-lightbox]");
    const shots = Array.from(document.querySelectorAll("[data-shot]"));
    if (!dialog || !shots.length || typeof dialog.showModal !== "function") return;

    const img = dialog.querySelector("[data-lb-img]");
    const caption = dialog.querySelector("[data-lb-caption]");
    const count = dialog.querySelector("[data-lb-count]");
    const prev = dialog.querySelector("[data-lb-prev]");
    const next = dialog.querySelector("[data-lb-next]");
    let group = [];
    let index = 0;
    let opener = null;

    /** Affiche la photo n° i de la catégorie ouverte (navigation en boucle). */
    const show = (i) => {
      index = (i + group.length) % group.length;
      const link = group[index];
      const thumb = link.querySelector("img");
      img.src = link.getAttribute("href");
      img.alt = thumb ? thumb.alt : "";
      caption.textContent = link.dataset.caption || "";
      count.textContent = group.length > 1 ? `${index + 1} / ${group.length}` : "";
      prev.hidden = next.hidden = group.length < 2;
    };

    shots.forEach((link) => {
      link.addEventListener("click", (event) => {
        if (event.ctrlKey || event.metaKey || event.shiftKey) return; // ouverture dans un onglet
        event.preventDefault();
        group = shots.filter((s) => s.dataset.shot === link.dataset.shot);
        opener = link;
        show(group.indexOf(link));
        dialog.showModal();
      });
    });

    prev.addEventListener("click", () => show(index - 1));
    next.addEventListener("click", () => show(index + 1));
    dialog.querySelector("[data-lb-close]").addEventListener("click", () => dialog.close());
    // Un clic sur le fond (hors photo et boutons) ferme la visionneuse.
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "ArrowRight") show(index + 1);
      else if (event.key === "ArrowLeft") show(index - 1);
    });
    // Glissement du doigt vers la gauche ou la droite sur mobile.
    let startX = null;
    dialog.addEventListener("touchstart", (event) => { startX = event.touches[0].clientX; }, { passive: true });
    dialog.addEventListener("touchend", (event) => {
      if (startX === null) return;
      const delta = event.changedTouches[0].clientX - startX;
      if (Math.abs(delta) > 50 && group.length > 1) show(index + (delta < 0 ? 1 : -1));
      startX = null;
    });
    dialog.addEventListener("close", () => {
      img.removeAttribute("src");
      if (opener) opener.focus();
    });
  }

  initCarousel();
  initPriceCalc();
  initLightbox();
})();

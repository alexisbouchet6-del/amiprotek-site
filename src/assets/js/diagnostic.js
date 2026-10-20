/**
 * AMIPROTEK : diagnostic guidé.
 *
 * L'arbre de décision est injecté au build dans <script id="diagnostic-data">
 * (src/data/diagnostic.json). Tout se passe dans le navigateur : aucune réponse
 * n'est envoyée. Le DOM est construit avec textContent uniquement (pas
 * d'innerHTML), ce qui exclut toute injection de code.
 *
 * Le bouton « Précédent » du navigateur fonctionne (history.pushState), et
 * l'adresse diagnostic.html?start=<raccourci> ouvre directement une branche.
 */
(() => {
  "use strict";

  const root = document.querySelector("[data-diagnostic]");
  if (!root) return;

  const stage = root.querySelector("[data-stage]");
  const progressBar = root.querySelector("[data-progress]");
  const trailBox = root.querySelector("[data-trail-box]");
  const trailList = root.querySelector("[data-trail]");
  const restartButton = root.querySelector("[data-restart]");

  /** Crée un élément avec ses attributs et son texte, sans jamais interpréter de HTML. */
  function el(tag, attrs = {}, text = "") {
    const node = document.createElement(tag);
    Object.entries(attrs).forEach(([name, value]) => node.setAttribute(name, value));
    if (text) node.textContent = text;
    return node;
  }

  let data;
  try {
    data = JSON.parse(document.getElementById("diagnostic-data").textContent);
  } catch (error) {
    stage.replaceChildren(el("p", { class: "note" }, "Le diagnostic n'a pas pu se charger. Appelez-nous directement."));
    return;
  }

  const { tree, tarifs, services, contact, antivirus } = data;

  /** Chemin parcouru : liste de { node, label, next }. */
  let path = [];
  let current = tree.start;

  function nodeOf(id) {
    const node = tree.nodes[id];
    if (!node) throw new Error(`Nœud de diagnostic inconnu : ${id}`);
    return node;
  }

  /**
   * Enregistre l'étape dans l'historique du navigateur. Certains cadres
   * intégrés (iframe sandboxée) refusent l'API History : le diagnostic
   * continue alors de fonctionner, sans le bouton Précédent du navigateur.
   */
  function saveState(replace = false) {
    try {
      const url = window.location.pathname + (replace ? window.location.search : "");
      window.history[replace ? "replaceState" : "pushState"]({ path }, "", url);
    } catch (error) {
      /* Historique indisponible : sans conséquence pour le parcours. */
    }
  }

  // --- Navigation ----------------------------------------------------------

  function choose(option) {
    path = [...path, { node: current, label: option.label, next: option.next }];
    current = option.next;
    saveState();
    render("forward");
  }

  function rewindTo(index) {
    current = path[index].node;
    path = path.slice(0, index);
    saveState();
    render("back");
  }

  function restart() {
    path = [];
    current = tree.start;
    saveState();
    render("back");
  }

  function restore(savedPath) {
    path = Array.isArray(savedPath) ? savedPath : [];
    current = path.length ? path[path.length - 1].next : tree.start;
  }

  window.addEventListener("popstate", (event) => {
    restore(event.state && event.state.path);
    render("back");
  });

  // --- Rendu ------------------------------------------------------------------

  function render(direction) {
    let node;
    try {
      node = nodeOf(current);
    } catch (error) {
      stage.replaceChildren(el("p", { class: "note" }, `Une erreur est survenue. Appelez-nous au ${contact.phone_display}.`));
      return;
    }

    const step = node.type === "result" ? renderResult(node) : renderQuestion(node);
    step.classList.add("diag__step");
    if (direction === "back") step.classList.add("is-back");
    stage.replaceChildren(step);

    renderTrail();
    updateProgress(node);

    // Déplace le focus sur le titre pour les lecteurs d'écran et le clavier,
    // sauf au premier affichage (on ne vole pas le focus à l'arrivée).
    if (direction) {
      const heading = step.querySelector("h2");
      if (heading) heading.focus({ preventScroll: true });
      if (root.getBoundingClientRect().top < 0) {
        root.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  }

  function renderQuestion(node) {
    const wrapper = el("div");
    wrapper.append(
      el("p", { class: "diag__count" }, `Question ${path.length + 1}`),
      el("h2", { class: "diag__title", tabindex: "-1" }, node.title)
    );
    if (node.help) wrapper.append(el("p", { class: "diag__help" }, node.help));

    const list = el("ul", { class: "diag__options" });
    node.options.forEach((option) => {
      const button = el("button", { type: "button", class: "diag__option" }, option.label);
      button.addEventListener("click", () => choose(option));
      const item = el("li");
      item.append(button);
      list.append(item);
    });
    wrapper.append(list);

    if (path.length) {
      const nav = el("div", { class: "diag__nav" });
      const back = el("button", { type: "button", class: "link-btn" }, "Question précédente");
      back.addEventListener("click", () => rewindTo(path.length - 1));
      nav.append(back);
      wrapper.append(nav);
    }
    return wrapper;
  }

  function renderResult(node) {
    const wrapper = el("div", { class: `diag__result${node.urgent ? " is-urgent" : ""}` });
    wrapper.append(el("h2", { tabindex: "-1" }, node.title), el("p", {}, node.summary));

    const offers = (node.tarifs || []).map((id) => tarifs[id]).filter(Boolean);
    // En cas d'urgence sans tarif fixe, on ne parle pas de devis : on va droit aux gestes utiles.
    if (offers.length || !node.urgent) wrapper.append(el("h3", {}, "Prestation conseillée"));
    if (offers.length) {
      const table = el("table", { class: "tarifs" });
      const head = el("thead");
      const headRow = el("tr");
      // En-têtes sur deux lignes (« Professionnels » / « HT »), comme sur la page Tarifs.
      const priceHead = (label, unit) => {
        const th = el("th", { scope: "col", class: "num" }, label);
        th.append(el("span", { class: "unit" }, unit));
        return th;
      };
      headRow.append(
        el("th", { scope: "col" }, "Prestation"),
        priceHead("Professionnels", "HT"),
        priceHead("Particuliers", "TTC")
      );
      head.append(headRow);
      const body = el("tbody");
      offers.forEach((offer) => {
        const row = el("tr");
        row.append(
          el("th", { scope: "row" }, offer.name),
          el("td", { class: "num" }, offer.pro),
          el("td", { class: "num" }, offer.part)
        );
        body.append(row);
      });
      table.append(head, body);
      const box = el("div", { class: "diag__offer table-scroll" });
      box.append(table);
      wrapper.append(box);
      const domicile = el("p", { class: "note" }, "Intervention possible à domicile ou sur site. ");
      domicile.append(el("a", { href: "tarifs.html#domicile" }, "Voir les tarifs à domicile et les frais de déplacement"));
      wrapper.append(domicile);
    } else if (!node.urgent) {
      wrapper.append(
        el("p", { class: "diag__quote" }, "Sur devis, après un échange sur votre situation. Appelez-nous ou écrivez-nous pour en parler.")
      );
    }

    if (node.tips && node.tips.length) {
      wrapper.append(el("h3", {}, node.urgent ? "À faire tout de suite" : "En attendant notre intervention"));
      const tips = el("ul", { class: "diag__tips" });
      node.tips.forEach((tip) => tips.append(el("li", {}, tip)));
      wrapper.append(tips);
    }

    if (node.offer === "antivirus" && antivirus) wrapper.append(renderAntivirus(node));

    const actions = el("div", { class: "diag__actions" });
    actions.append(
      el("a", { class: "btn btn--primary", href: `tel:${contact.phone_link}` }, `Appeler le ${contact.phone_display}`),
      el("a", { class: "btn btn--line", href: mailtoFor(node) }, "Préparer un e-mail")
    );
    wrapper.append(actions);

    const links = el("p", { class: "diag__links" });
    if (node.service && services[node.service]) {
      links.append(el("a", { href: `services.html#${node.service}` }, `En savoir plus : ${services[node.service]}`));
    }
    if (node.link) {
      links.append(el("a", { href: node.link.url, rel: "noopener", target: "_blank" }, node.link.label));
    }
    const again = el("button", { type: "button", class: "link-btn" }, "Recommencer le diagnostic");
    again.addEventListener("click", restart);
    links.append(again);
    wrapper.append(links);

    return wrapper;
  }

  /** Proposition de protection antivirus, affichée sur les résultats liés aux virus. */
  function renderAntivirus(node) {
    const box = el("aside", { class: "diag__av", "aria-label": "Protection antivirus conseillée" });
    box.append(el("h3", {}, node.urgent ? "Après l'incident : protéger vos postes" : "Pour éviter que cela se reproduise"));
    box.append(
      el(
        "p",
        {},
        `Nous installons et activons ${antivirus.product} (${antivirus.edition}) sur vos ordinateurs : ` +
          "protection contre les virus et les rançongiciels, blocage des sites et pièces jointes piégés, " +
          "et analyse de l'origine d'une attaque pour la corriger durablement."
      )
    );
    if (antivirus.stat) box.append(el("p", { class: "diag__av-stat" }, antivirus.stat));
    if (antivirus.price) {
      box.append(
        el(
          "p",
          { class: "diag__av-price" },
          `${antivirus.price.pro} € HT par poste et par an pour les professionnels, ${antivirus.price.part} € TTC pour les particuliers, ` +
            `${antivirus.price.mobiles} smartphones inclus.`
        )
      );
    }
    box.append(el("a", { href: antivirus.page }, "Pourquoi un antivirus actif est indispensable"));
    return box;
  }

  /** E-mail pré-rempli avec les réponses : le visiteur le relit avant d'envoyer. */
  function mailtoFor(node) {
    const answers = path.map((step) => `- ${nodeOf(step.node).title} ${step.label}`).join("\n");
    const body = [
      "Bonjour,",
      "",
      "J'ai utilisé le diagnostic de votre site.",
      "",
      "Mes réponses :",
      answers,
      "",
      `Résultat : ${node.title}`,
      "",
      "Nom :",
      "Téléphone :",
      "Commune :",
      "",
      "Merci.",
    ].join("\n");
    const subject = `Diagnostic en ligne : ${node.title}`;
    return `mailto:${contact.email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  }

  function renderTrail() {
    trailBox.hidden = path.length === 0;
    trailList.replaceChildren();
    path.forEach((step, index) => {
      const item = el("li");
      const button = el("button", { type: "button" }, step.label);
      button.setAttribute("aria-label", `Modifier la réponse : ${step.label}`);
      button.addEventListener("click", () => rewindTo(index));
      item.append(el("span", { class: "q" }, nodeOf(step.node).title), button);
      trailList.append(item);
    });
  }

  function updateProgress(node) {
    const done = node.type === "result";
    const width = done ? 100 : Math.min(85, 12 + path.length * 25);
    progressBar.style.width = `${width}%`;
    progressBar.classList.toggle("is-done", done && !node.urgent);
    progressBar.classList.toggle("is-urgent", done && Boolean(node.urgent));
  }

  restartButton.addEventListener("click", restart);

  // --- Démarrage : raccourci éventuel (?start=lent, ?start=internet, ...) ----

  const shortcut = new URLSearchParams(window.location.search).get("start");
  const target = shortcut && tree.shortcuts ? tree.shortcuts[shortcut] : null;
  if (target) {
    const option = nodeOf(tree.start).options.find((opt) => opt.next === target);
    if (option) {
      path = [{ node: tree.start, label: option.label, next: target }];
      current = target;
    }
  }
  saveState(true);
  render(null);
})();

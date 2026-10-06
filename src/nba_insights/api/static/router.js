// Page navigation: shows one page, keeps the nav and URL in sync, and runs
// the page's loader. Pages register themselves so this module needs no
// knowledge of any page's internals.
const loaders = new Map();
const retries = new Map();
const deepLinks = new Map();

export const PAGES = ["pulse", "players", "explore", "compare", "teams", "games", "tracking", "matchup", "outlook", "ask", "methodology", "more"];
const PRIMARY = ["pulse", "players", "games", "matchup"];

/** Run *loader* whenever *page* is shown. */
export function registerPage(page, loader) {
  loaders.set(page, loader);
}

/** Open `#page/param` URLs: *handler* receives the decoded param. */
export function registerDeepLink(page, handler) {
  deepLinks.set(page, handler);
}

/** Split a location hash such as "#players/203999" into page and param. */
export function parseHash(hash) {
  const [page, ...rest] = hash.replace(/^#/, "").split("/");
  const param = rest.length ? decodeURIComponent(rest.join("/")) : null;
  return PAGES.includes(page) ? { page, param } : { page: "pulse", param: null };
}

/** Run *handler* when a `[data-retry="name"]` button is pressed. */
export function registerRetry(name, handler) {
  retries.set(name, handler);
}

export function showPage(page, updateHash = true) {
  const primaryPage = PRIMARY.includes(page) ? page : "more";
  document.querySelectorAll(".page").forEach(el => el.classList.toggle("active", el.id === `page-${page}`));
  document.querySelectorAll(".desktop-nav [data-page], .mobile-nav [data-page]").forEach(el => {
    const active = el.dataset.page === primaryPage;
    el.classList.toggle("active", active);
    if (active) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current");
  });
  if (updateHash) history.replaceState(null, "", page === "pulse" ? location.pathname : `#${page}`);
  loaders.get(page)?.();
  window.scrollTo({ top: 0, behavior: "smooth" });
  if(updateHash){
    const heading=document.querySelector(`#page-${page} h1`);
    if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}
  }
}

export const initialPage = parseHash(location.hash).page;

function route(updateHash) {
  const { page, param } = parseHash(location.hash);
  const deepLink = param !== null ? deepLinks.get(page) : null;
  showPage(page, updateHash && !deepLink);
  if (deepLink) deepLink(param);
}

/** Wire nav buttons and retry buttons, then show the page in the URL. */
export function startRouter() {
  document.querySelectorAll("[data-page]").forEach(el => el.addEventListener("click", () => showPage(el.dataset.page)));
  document.addEventListener("click", event => {
    const retry = event.target.closest("[data-retry]");
    if (retry) retries.get(retry.dataset.retry)?.();
  });
  // a link pasted into an open tab changes only the hash
  window.addEventListener("hashchange", () => route(true));
  route(false);
}

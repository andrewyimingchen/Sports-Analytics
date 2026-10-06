// PWA entry point. Each page module registers its loader with the router on
// import; this file loads them, starts navigation, and installs the worker.
import { updateConnectionStatus } from "./meta.js";
import { startRouter } from "./router.js";
import "./pages/ask.js";
import "./pages/compare.js";
import "./pages/explore.js";
import "./pages/games.js";
import "./pages/matchup.js";
import "./pages/methodology.js";
import "./pages/outlook.js";
import "./pages/profile.js";
import "./pages/pulse.js";
import "./pages/teams.js";
import "./pages/tracking.js";

startRouter();
updateConnectionStatus();

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").then(registration=>registration.update());

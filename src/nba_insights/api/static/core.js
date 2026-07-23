export const $ = (id) => document.getElementById(id);

export const escapeHTML = (value) => String(value ?? "").replace(
  /[&<>'"]/g,
  (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character],
);

export const api = async (path, options = {}) => {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = response.statusText;
    try {
      message = (await response.json()).detail || message;
    } catch {
      // Preserve the HTTP status text when the response is not JSON.
    }
    throw new Error(message);
  }
  return response.json();
};

export const fmt = (value, digits = 1) => (
  Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—"
);

export const money = (value) => (
  Number.isFinite(Number(value)) ? `$${(Number(value) / 1e6).toFixed(1)}M` : "—"
);

export const deepValue = (result) => (
  result.status === "fulfilled" ? result.value : null
);

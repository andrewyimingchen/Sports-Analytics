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

// null and "" are missing values, not zero (Number(null) === 0).
const present = (value) => value !== null && value !== "" && Number.isFinite(Number(value));

export const fmt = (value, digits = 1) => (
  present(value) ? Number(value).toFixed(digits) : "—"
);

export const money = (value) => (
  present(value) ? `$${(Number(value) / 1e6).toFixed(1)}M` : "—"
);

export const deepValue = (result) => (
  result.status === "fulfilled" ? result.value : null
);

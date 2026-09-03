// Handles the login screen, Google OAuth redirect, logout, and
// deciding which screen to show on page load based on session state.
// Exposes window.Starbit.* helpers that app.js also uses.

window.Starbit = window.Starbit || {};

(function () {
  const API = window.STARBIT_API_BASE;

  function showScreen(name) {
    document.querySelectorAll(".screen").forEach((el) => el.classList.remove("active"));
    document.getElementById(`screen-${name}`).classList.add("active");
  }

  function setUserBadges(user) {
    const label = `👤 ${user.name}`;
    const badge1 = document.getElementById("user-badge");
    const badge2 = document.getElementById("user-badge-2");
    if (badge1) badge1.textContent = label;
    if (badge2) badge2.textContent = label;
  }

  async function checkSession() {
    try {
      const res = await fetch(`${API}/auth/me`, { credentials: "include" });
      const data = await res.json();
      if (!data.logged_in) {
        showScreen("login");
        return;
      }
      setUserBadges(data);
      window.Starbit.questionsRemaining = data.questions_remaining;
      if (data.has_dataset) {
        showScreen("console");
        window.Starbit.onEnterConsole && window.Starbit.onEnterConsole();
      } else {
        showScreen("upload");
      }
    } catch (err) {
      console.error("Session check failed:", err);
      showScreen("login");
    }
  }

  document.getElementById("btn-login").addEventListener("click", () => {
    const btn = document.getElementById("btn-login");
    const transition = document.getElementById("login-transition");
    btn.disabled = true;
    transition.hidden = false;
    // Small delay purely so the "Contacting Starbit HQ..." beat is visible
    // before navigating -- in mock-auth mode the redirect is instant and
    // otherwise felt like the button did nothing.
    setTimeout(() => {
      window.location.href = `${API}/auth/login`;
    }, 650);
  });

  async function doLogout() {
    await fetch(`${API}/auth/logout`, { method: "POST", credentials: "include" });
    window.location.href = "index.html";
  }

  document.getElementById("btn-logout").addEventListener("click", doLogout);

  const consoleLogoutBtn = document.getElementById("btn-logout-console");
  if (consoleLogoutBtn) consoleLogoutBtn.addEventListener("click", doLogout);

  window.Starbit.showScreen = showScreen;
  window.Starbit.checkSession = checkSession;

  document.addEventListener("DOMContentLoaded", checkSession);
})();
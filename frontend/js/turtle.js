// A small, purely-decorative pixel turtle that wanders around the
// viewport edges every few seconds. Purely for charm -- no game logic
// depends on it, and it respects prefers-reduced-motion.

(function () {
  const turtle = document.getElementById("turtle");
  if (!turtle) return;

  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (prefersReducedMotion) {
    turtle.style.display = "none";
    return;
  }

  function wander() {
    const margin = 60;
    const maxX = window.innerWidth - margin;
    const maxY = window.innerHeight - margin;

    const nextX = Math.max(margin, Math.random() * maxX);
    const nextY = Math.max(margin, Math.random() * maxY);

    const currentLeft = parseFloat(turtle.style.left || "20");
    const facingLeft = nextX < currentLeft;

    turtle.style.left = `${nextX}px`;
    turtle.style.bottom = `${window.innerHeight - nextY}px`;
    turtle.style.transform = facingLeft ? "scaleX(-1)" : "scaleX(1)";
  }

  // Wander every 4-7 seconds, matching the CSS transition duration.
  setInterval(wander, 4000 + Math.random() * 3000);
  wander();
})();

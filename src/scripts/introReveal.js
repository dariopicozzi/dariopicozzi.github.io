/*
 * Reveal the homepage intro gradually: the name letter-by-letter, then each
 * paragraph word-by-word on a gentle stagger. Splits text nodes into <span>s
 * (recursing into links so they stay intact) and drives each with a CSS
 * animation via a per-span animation-delay. Falls back to plain visible text
 * when JS is off or reduced motion is requested.
 */
const NAME_STEP = 0.07; // seconds between letters of the name
const WORD_STEP = 0.085; // seconds between words of the paragraphs
const NAME_GAP = 0.25; // pause after the name, before the first paragraph
const PARA_GAP = 0.4; // pause between paragraphs

// Reveals one block's text word-by-word starting at `start` seconds; returns
// the time (seconds) at which its last word begins. Reduced motion just shows it.
export function revealBlock(block, start = 0) {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    block.style.opacity = '1';
    return start;
  }
  let t = start;
  const h1 = block.querySelector('h1');
  if (h1 && !h1.classList.contains('sr-only')) {
    t = split(h1, 'char', t, NAME_STEP);
    t += NAME_GAP;
  }
  block.querySelectorAll('p').forEach((p) => {
    t = split(p, 'word', t, WORD_STEP);
    t += PARA_GAP;
  });
  block.style.opacity = '1';
  return t;
}

function split(el, mode, t, step) {
  const walk = (node) => {
    Array.from(node.childNodes).forEach((child) => {
      if (child.nodeType === Node.TEXT_NODE) {
        const tokens =
          mode === 'char' ? Array.from(child.textContent) : child.textContent.split(/(\s+)/);
        const frag = document.createDocumentFragment();
        tokens.forEach((tok) => {
          if (tok === '') return;
          if (/^\s+$/.test(tok)) {
            frag.appendChild(document.createTextNode(tok));
            return;
          }
          const span = document.createElement('span');
          span.className = 'intro-rv';
          span.textContent = tok;
          span.style.animationDelay = t.toFixed(3) + 's';
          t += step;
          frag.appendChild(span);
        });
        node.replaceChild(frag, child);
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        walk(child); // recurse into <a> etc. so links keep working
      }
    });
  };
  walk(el);
  return t;
}

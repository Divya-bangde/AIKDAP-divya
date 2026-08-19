/**
 * The structural backdrop shared by the public entry experience and
 * the sign-in screen (Sprint 9K.4).
 *
 * Three stacked layers, all decorative and all `aria-hidden`: two very
 * wide colour washes, a fine structural grid, and a vignette that
 * darkens the frame so the centre composition holds the eye.
 *
 * It is a *component* rather than three copies of the same markup
 * specifically so the landing page and the login page paint the same
 * surface. Crossing from one to the other, the background does not
 * change — only the content on top of it does, which is what makes the
 * handoff read as one continuous place rather than two pages. Every
 * layer is driven by palette tokens, so it renders correctly in both
 * themes even though the landing itself is always dark.
 *
 * Pure CSS: no canvas, no WebGL, no image, no runtime cost beyond
 * compositing.
 *
 * Fixed to the viewport rather than to the document. The grid's mask
 * and the vignette are both radial gradients sized in percentages, and
 * once the entry page became a nine-section scrolling document those
 * percentages resolved against ~8,500px of page — which stretched the
 * vignette into a single enormous ellipse and left visible horizontal
 * bands where its stops landed (seen at 1440×900, section 09). Pinned
 * to the viewport, every gradient resolves against one screen, so the
 * texture is identical at every scroll position and there is no edge
 * to notice.
 */
export function EntryBackdrop({ vignette = true }: { vignette?: boolean }) {
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      <div className="landing-aurora absolute inset-0" />
      <div className="landing-grid absolute inset-0" />
      {vignette && <div className="landing-vignette absolute inset-0" />}
    </div>
  );
}

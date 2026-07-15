/* GraphView 1.0.0 — tiny local SVG pan/zoom helper for the static demo. */
window.GraphView = class GraphView {
  constructor(svg, content) {
    this.svg = svg; this.content = content; this.scale = 1; this.x = 0; this.y = 0;
    this.drag = null;
    svg.addEventListener('pointerdown', (event) => { this.drag = { x: event.clientX, y: event.clientY }; svg.setPointerCapture(event.pointerId); });
    svg.addEventListener('pointermove', (event) => { if (!this.drag) return; this.x += event.clientX - this.drag.x; this.y += event.clientY - this.drag.y; this.drag = { x: event.clientX, y: event.clientY }; this.render(); });
    svg.addEventListener('pointerup', () => { this.drag = null; });
    svg.addEventListener('wheel', (event) => { event.preventDefault(); this.scale = Math.max(.35, Math.min(3, this.scale * (event.deltaY < 0 ? 1.12 : .89))); this.render(); }, { passive: false });
  }
  render() { this.content.setAttribute('transform', `translate(${this.x} ${this.y}) scale(${this.scale})`); }
  zoom(factor) { this.scale = Math.max(.35, Math.min(3, this.scale * factor)); this.render(); }
  reset() { this.scale = 1; this.x = 0; this.y = 0; this.render(); }
  fit() { this.reset(); }
};

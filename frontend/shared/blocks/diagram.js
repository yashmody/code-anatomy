// The course `diagram` block is a thin wrapper over the shared renderDiagram helper,
// so course diagrams and feed media diagrams go through the exact same code path.
import { renderDiagram } from '../render/diagram.js';

export function diagram(block) {
  return renderDiagram(block);
}

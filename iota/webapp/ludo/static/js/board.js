/* ═══════════════════════════════════════════════════════════
   Iota Ludo — Board Renderer

   Draws a classic 15×15 cross-shaped Ludo board on a 780×780 SVG
   viewBox (52 cells = 1 cell per 52px "ring" logically, but laid
   out on the real grid coordinates below) and positions player
   piece tokens on it based on game state (0-58 position values
   from utils/ludo_engine.py on the Python side).

   COORDINATE SYSTEM
   The board is a 15x15 grid of 52px cells (780 / 15 = 52).
   We hardcode the (col,row) grid position of each of the 52 path
   cells + each color's 6 home-stretch cells, matching a standard
   Ludo layout. This mirrors exactly what the Python engine's
   START_POSITIONS / HOME_ENTRY / SAFE_CELLS describe, so a
   position number always renders in the same place logic expects.
   ═══════════════════════════════════════════════════════════ */

const CELL = 52; // 780 / 15

// The 52 outer-track cells in walk order, starting at the red entry
// square (path index 1) going clockwise. Each is a [col,row] grid coord
// (0-indexed, 15x15 grid).
const PATH_COORDS = [
  // 1-5: red start arm (col 6, rows 6->2 going up column 1..5, then across)
  [1,6],[2,6],[3,6],[4,6],[5,6],           // 1-5
  [6,5],[6,4],[6,3],[6,2],[6,1],[6,0],     // 6-11
  [7,0],                                    // 12
  [8,0],[8,1],[8,2],[8,3],[8,4],[8,5],     // 13-18
  [9,6],[10,6],[11,6],[12,6],[13,6],[14,6],// 19-24
  [14,7],                                   // 25
  [14,8],                                   // 26
  [13,8],[12,8],[11,8],[10,8],[9,8],       // 27-31
  [8,9],[8,10],[8,11],[8,12],[8,13],[8,14],// 32-37
  [7,14],                                   // 38
  [6,14],[6,13],[6,12],[6,11],[6,10],[6,9],// 39-44
  [5,8],[4,8],[3,8],[2,8],[1,8],[0,8],     // 45-50
  [0,7],                                    // 51
  [0,6],                                    // 52 (back near red start)
];

// Home-stretch cells (53-58) per color, leading into the center.
const HOME_STRETCH_COORDS = {
  red:    [[1,7],[2,7],[3,7],[4,7],[5,7],[6,7]],
  blue:   [[7,1],[7,2],[7,3],[7,4],[7,5],[7,6]],
  green:  [[13,7],[12,7],[11,7],[10,7],[9,7],[8,7]],
  yellow: [[7,13],[7,12],[7,11],[7,10],[7,9],[7,8]],
};

// Yard slot coordinates (4 pieces per color, inside the big colored corner square).
const YARD_COORDS = {
  red:    [[2,2],[3,2],[2,3],[3,3]],
  blue:   [[11,2],[12,2],[11,3],[12,3]],
  green:  [[11,11],[12,11],[11,12],[12,12]],
  yellow: [[2,11],[3,11],[2,12],[3,12]],
};

const COLOR_HEX = { red: '#ef5350', blue: '#42a5f5', green: '#66bb6a', yellow: '#ffca28' };
const SAFE_CELLS = new Set([1,9,14,22,27,35,40,48]);

function cellCenter([col, row]) {
  return { x: col * CELL + CELL / 2, y: row * CELL + CELL / 2 };
}

function posToCoord(pos, color) {
  if (pos === 0) return null; // caller uses yard slot instead
  if (pos <= 52) return PATH_COORDS[pos - 1];
  const stretchIdx = pos - 53; // 53->0 .. 58->5
  return HOME_STRETCH_COORDS[color][Math.min(stretchIdx, 5)];
}

function svgEl(tag, attrs) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

function drawBoard(svg) {
  svg.innerHTML = '';
  const bg = svgEl('rect', { x: 0, y: 0, width: 780, height: 780, fill: '#1a1e33', rx: 18 });
  svg.appendChild(bg);

  // Four big corner yards
  const corners = {
    red:    { x: 0,   y: 0 },
    blue:   { x: 468, y: 0 },
    green:  { x: 468, y: 468 },
    yellow: { x: 0,   y: 468 },
  };
  for (const color in corners) {
    const { x, y } = corners[color];
    svg.appendChild(svgEl('rect', {
      x, y, width: 312, height: 312, fill: COLOR_HEX[color], opacity: 0.16, rx: 14,
    }));
    svg.appendChild(svgEl('rect', {
      x: x + 34, y: y + 34, width: 244, height: 244, fill: '#171b2e', rx: 20,
      stroke: COLOR_HEX[color], 'stroke-width': 3, opacity: 0.9,
    }));
    // Yard slots (dashed circles where pieces sit at position 0)
    YARD_COORDS[color].forEach(coord => {
      const { x: cx, y: cy } = cellCenter(coord);
      svg.appendChild(svgEl('circle', {
        cx, cy, r: 16, fill: 'none', stroke: COLOR_HEX[color],
        'stroke-width': 2, 'stroke-dasharray': '4 3', opacity: 0.5,
      }));
    });
  }

  // Center home triangle (4-color pinwheel)
  const cx = 390, cy = 390, r = 78;
  const triColors = [
    { color: 'red',    pts: `${cx-r},${cy-r} ${cx},${cy} ${cx-r},${cy+r}` },
    { color: 'blue',   pts: `${cx-r},${cy-r} ${cx},${cy} ${cx+r},${cy-r}` },
    { color: 'green',  pts: `${cx+r},${cy-r} ${cx},${cy} ${cx+r},${cy+r}` },
    { color: 'yellow', pts: `${cx-r},${cy+r} ${cx},${cy} ${cx+r},${cy+r}` },
  ];
  triColors.forEach(t => svg.appendChild(svgEl('polygon', { points: t.pts, fill: COLOR_HEX[t.color] })));

  // Draw all 52 path cells + 24 home-stretch cells as a subtle grid
  const allTrackCells = [...PATH_COORDS.map((c, i) => ({ coord: c, pos: i + 1, color: null }))];
  Object.keys(HOME_STRETCH_COORDS).forEach(color => {
    HOME_STRETCH_COORDS[color].forEach((coord, i) => {
      allTrackCells.push({ coord, pos: 53 + i, color });
    });
  });

  allTrackCells.forEach(({ coord, pos, color }) => {
    const [col, row] = coord;
    const isSafe = !color && SAFE_CELLS.has(pos);
    const isStart = !color && [1,14,27,40].includes(pos);
    let fill = '#232842';
    if (color) fill = COLOR_HEX[color];
    else if (isStart) fill = COLOR_HEX[ pos===1?'red':pos===14?'blue':pos===27?'green':'yellow' ];
    else if (isSafe) fill = '#2f3555';

    svg.appendChild(svgEl('rect', {
      x: col * CELL + 2, y: row * CELL + 2, width: CELL - 4, height: CELL - 4,
      fill, opacity: color ? 0.55 : (isStart ? 0.85 : 1),
      rx: 6, stroke: '#12142200', 'stroke-width': 1,
    }));
    if (isSafe) {
      const { x, y } = cellCenter(coord);
      svg.appendChild(svgEl('text', {
        x, y: y + 5, 'text-anchor': 'middle', 'font-size': 16, fill: '#ffb648', opacity: 0.8,
      })).textContent = '★';
    }
  });

  // Outer border
  svg.appendChild(svgEl('rect', {
    x: 2, y: 2, width: 776, height: 776, fill: 'none',
    stroke: '#2a2f47', 'stroke-width': 3, rx: 18,
  }));
}

/**
 * Renders piece tokens on top of the board based on current game state.
 * `players` = [{id, name, color, pieces:[p0,p1,p2,p3]}]
 */
function drawPieces(svg, players, onPieceClick, movablePieceIdxForColor) {
  // Remove old piece layer
  const old = svg.querySelector('#piece-layer');
  if (old) old.remove();
  const layer = svgEl('g', { id: 'piece-layer' });
  svg.appendChild(layer);

  // Track how many pieces share a cell to offset them slightly (avoid full overlap)
  const occupancy = {};

  players.forEach(player => {
    player.pieces.forEach((pos, idx) => {
      let coord;
      let jitter = { x: 0, y: 0 };
      if (pos === 0) {
        coord = YARD_COORDS[player.color][idx];
      } else {
        coord = posToCoord(pos, player.color);
        const key = `${player.color}_${pos}`;
        occupancy[key] = (occupancy[key] || 0);
        const n = occupancy[key]++;
        const offsets = [[-8,-8],[8,-8],[-8,8],[8,8]];
        jitter = { x: offsets[n % 4][0], y: offsets[n % 4][1] };
      }
      if (!coord) return;
      const { x, y } = cellCenter(coord);

      const isMovable = movablePieceIdxForColor &&
        movablePieceIdxForColor.color === player.color &&
        movablePieceIdxForColor.indices.includes(idx);

      const g = svgEl('g', {
        transform: `translate(${x + jitter.x}, ${y + jitter.y})`,
        style: isMovable ? 'cursor:pointer' : 'cursor:default',
      });

      if (isMovable) {
        const pulse = svgEl('circle', { r: 17, fill: COLOR_HEX[player.color], opacity: 0.35 });
        pulse.innerHTML = `<animate attributeName="r" values="14;20;14" dur="1s" repeatCount="indefinite" />
                            <animate attributeName="opacity" values="0.45;0.1;0.45" dur="1s" repeatCount="indefinite" />`;
        g.appendChild(pulse);
      }

      g.appendChild(svgEl('circle', { r: 13, fill: '#0f1220', opacity: 0.35, cy: 2 })); // shadow
      g.appendChild(svgEl('circle', {
        r: 12, fill: COLOR_HEX[player.color], stroke: '#f0ece0', 'stroke-width': 2,
      }));
      g.appendChild(svgEl('circle', { r: 4, fill: 'rgba(255,255,255,0.55)', cx: -3, cy: -3 }));

      if (isMovable && onPieceClick) {
        g.addEventListener('click', () => onPieceClick(idx));
      }
      layer.appendChild(g);
    });
  });
}

window.LudoBoard = { drawBoard, drawPieces, COLOR_HEX };

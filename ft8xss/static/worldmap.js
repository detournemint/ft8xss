/* Azimuthal-equidistant map centred on the operator's QTH.
   Distance from centre is true great-circle distance; angle is true bearing.
   Coastlines are a deliberately coarse outline -- enough to orient by, small
   enough to inline with no external requests. */

const COAST = [
  // North America
  [[71,-156],[70,-141],[69,-131],[68,-120],[67,-108],[68,-95],[73,-85],[76,-95],[74,-110],[72,-125],[71,-156]],
  [[60,-141],[58,-135],[54,-130],[49,-125],[43,-124],[38,-123],[34,-120],[32,-117],[28,-114],[23,-110],
   [23,-106],[20,-105],[17,-100],[16,-95],[15,-92],[13,-88],[9,-83],[8,-78],[9,-77],[12,-83],[15,-83],
   [18,-88],[21,-87],[25,-97],[29,-94],[30,-89],[30,-84],[26,-80],[32,-81],[36,-76],[40,-74],[44,-70],
   [45,-67],[47,-65],[50,-60],[52,-56],[56,-61],[58,-68],[62,-78],[64,-88],[60,-95],[58,-94],[57,-89],
   [54,-82],[52,-79],[55,-77],[58,-78],[62,-78]],
  [[60,-165],[62,-165],[65,-168],[66,-162],[70,-160],[71,-156]],
  // South America
  [[12,-72],[11,-64],[8,-60],[5,-52],[0,-50],[-5,-36],[-8,-35],[-13,-38],[-18,-39],[-23,-43],[-27,-48],
   [-33,-53],[-38,-57],[-42,-63],[-47,-66],[-52,-68],[-55,-67],[-54,-72],[-50,-74],[-45,-74],[-40,-73],
   [-35,-72],[-30,-71],[-25,-70],[-20,-70],[-15,-75],[-10,-78],[-5,-81],[0,-80],[5,-77],[9,-78],[12,-72]],
  // Europe
  [[71,28],[70,20],[68,15],[64,11],[62,5],[58,6],[57,10],[54,9],[53,5],[51,3],[49,0],[48,-4],[46,-1],
   [43,-2],[43,-9],[38,-9],[37,-6],[36,-5],[38,0],[41,3],[43,7],[44,12],[41,15],[38,16],[40,18],[42,19],
   [45,14],[45,13],[46,13],[45,15],[42,19]],
  [[60,-5],[58,-6],[55,-6],[52,-10],[51,-5],[54,-3],[57,-2],[58,-3],[60,-5]],
  // Africa
  [[37,10],[33,11],[31,20],[31,25],[27,34],[22,37],[15,40],[11,43],[5,45],[0,42],[-5,39],[-11,40],
   [-17,36],[-22,35],[-27,32],[-33,27],[-34,20],[-31,17],[-25,15],[-18,12],[-12,13],[-6,12],[0,9],
   [5,4],[6,-2],[5,-8],[9,-13],[13,-17],[18,-16],[24,-15],[28,-12],[33,-8],[35,-2],[37,3],[37,10]],
  // Asia
  [[71,28],[70,45],[73,60],[73,75],[75,90],[74,105],[72,120],[70,135],[69,150],[66,165],[62,179],
   [60,165],[58,155],[55,140],[50,140],[46,143],[43,132],[39,127],[35,126],[31,122],[24,118],[21,110],
   [17,108],[10,105],[8,100],[13,98],[16,94],[21,90],[22,88],[19,85],[16,81],[11,76],[8,77],[13,74],
   [19,73],[23,68],[25,63],[27,57],[25,52],[20,40],[15,40]],
  [[36,36],[38,27],[40,26],[41,29],[43,35],[41,41],[38,48],[30,48],[27,52],[25,57],[27,57]],
  // India/SE Asia detail is folded into the Asia outline above
  // Australia / NZ
  [[-11,131],[-12,137],[-15,141],[-19,147],[-24,153],[-28,153],[-33,151],[-38,146],[-38,141],[-35,138],
   [-32,134],[-32,127],[-34,120],[-32,116],[-26,113],[-22,114],[-18,122],[-14,127],[-11,131]],
  [[-35,173],[-38,177],[-41,175],[-46,168],[-45,167],[-41,172],[-37,174],[-35,173]],
  // Greenland / Iceland
  [[83,-33],[81,-18],[76,-19],[70,-22],[65,-40],[70,-52],[76,-60],[80,-65],[83,-45],[83,-33]],
  [[66,-23],[65,-14],[64,-15],[63,-20],[65,-24],[66,-23]],
  // Antarctica (partial rim)
  [[-70,-60],[-72,-30],[-70,0],[-69,30],[-67,60],[-66,90],[-67,120],[-70,150],[-75,180],[-78,-150],
   [-75,-110],[-72,-80],[-70,-60]],
];

const R_EARTH = 6371;
const HALF_CIRC = Math.PI * R_EARTH;      // 20015 km to the antipode

function toRad(d) { return d * Math.PI / 180; }

/** great-circle distance (km) and initial bearing (rad) from a to b */
function gc(aLat, aLon, bLat, bLon) {
  const p1 = toRad(aLat), p2 = toRad(bLat);
  const dl = toRad(bLon - aLon), dp = p2 - p1;
  const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  const d = 2 * R_EARTH * Math.asin(Math.min(1, Math.sqrt(h)));
  const br = Math.atan2(Math.sin(dl) * Math.cos(p2),
                        Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl));
  return [d, br];
}

class AzMap {
  constructor(canvas, homeLat, homeLon) {
    this.c = canvas;
    this.home = [homeLat, homeLon];
    this.pts = [];
    canvas.addEventListener("click", e => this._click(e));
    this._hit = [];
  }

  _size() {
    const dpr = window.devicePixelRatio || 1;
    const w = this.c.clientWidth || 340, h = this.c.clientHeight || 300;
    if (this.c.width !== w * dpr || this.c.height !== h * dpr) {
      this.c.width = w * dpr; this.c.height = h * dpr;
    }
    const x = this.c.getContext("2d");
    x.setTransform(dpr, 0, 0, dpr, 0, 0);
    return [x, w, h];
  }

  /** lat/lon -> canvas x,y (null if beyond the drawable rim) */
  proj(lat, lon, cx, cy, rad) {
    const [d, br] = gc(this.home[0], this.home[1], lat, lon);
    const r = (d / HALF_CIRC) * rad;
    return [cx + r * Math.sin(br), cy - r * Math.cos(br), d];
  }

  draw(stations) {
    const [x, w, h] = this._size();
    const cx = w / 2, cy = h / 2, rad = Math.min(w, h) / 2 - 10;
    x.clearRect(0, 0, w, h);

    // ocean disc
    x.beginPath(); x.arc(cx, cy, rad, 0, 7);
    x.fillStyle = "#0b1016"; x.fill();
    x.strokeStyle = "#2b3440"; x.lineWidth = 1; x.stroke();

    // distance rings every 5000 km
    x.strokeStyle = "#1b232e"; x.setLineDash([2, 3]);
    for (const km of [5000, 10000, 15000]) {
      x.beginPath(); x.arc(cx, cy, (km / HALF_CIRC) * rad, 0, 7); x.stroke();
    }
    // bearing spokes
    for (let b = 0; b < 360; b += 45) {
      const a = toRad(b);
      x.beginPath(); x.moveTo(cx, cy);
      x.lineTo(cx + rad * Math.sin(a), cy - rad * Math.cos(a)); x.stroke();
    }
    x.setLineDash([]);

    // coastlines
    x.strokeStyle = "#39485a"; x.lineWidth = 1;
    for (const poly of COAST) {
      x.beginPath();
      let started = false, prev = null;
      for (const [la, lo] of poly) {
        const [px, py, d] = this.proj(la, lo, cx, cy, rad);
        // a segment that jumps across the far rim would draw a false chord
        if (prev && Math.hypot(px - prev[0], py - prev[1]) > rad * 0.9) { started = false; }
        if (!started) { x.moveTo(px, py); started = true; } else { x.lineTo(px, py); }
        prev = [px, py];
      }
      x.stroke();
    }

    // bearing labels
    x.fillStyle = "#5d6b7d"; x.font = "10px ui-monospace,monospace";
    x.textAlign = "center";
    const labels = [["N", 0], ["E", 90], ["S", 180], ["W", 270]];
    for (const [t, b] of labels) {
      const a = toRad(b), rr = rad - 8;
      x.fillText(t, cx + rr * Math.sin(a), cy - rr * Math.cos(a) + 3);
    }

    // stations
    this._hit = [];
    const seen = new Set();
    for (const s of stations) {
      if (!s.ll) continue;
      const key = s.grid;
      if (seen.has(key)) continue;
      seen.add(key);
      const [px, py] = this.proj(s.ll[0], s.ll[1], cx, cy, rad);
      const col = s.to_me ? "#2ee06a" : s.cq ? "#f0a02c" : s.worked ? "#5d6b7d" : "#4aa3ff";
      // stronger signals draw larger
      const size = s.snr >= 0 ? 4.2 : s.snr >= -12 ? 3.2 : 2.3;
      x.beginPath(); x.arc(px, py, size, 0, 7);
      x.fillStyle = col; x.fill();
      if (s.to_me) { x.strokeStyle = "#2ee06a"; x.lineWidth = 1;
                     x.beginPath(); x.arc(px, py, size + 3, 0, 7); x.stroke(); }
      this._hit.push({ x: px, y: py, s });
    }

    // home
    x.strokeStyle = "#ff5d5d"; x.lineWidth = 1.5;
    x.beginPath(); x.arc(cx, cy, 4, 0, 7); x.stroke();
    x.beginPath(); x.moveTo(cx - 7, cy); x.lineTo(cx + 7, cy);
    x.moveTo(cx, cy - 7); x.lineTo(cx, cy + 7); x.stroke();
  }

  _click(e) {
    const r = this.c.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    let best = null, bd = 12;
    for (const p of this._hit) {
      const d = Math.hypot(p.x - mx, p.y - my);
      if (d < bd) { bd = d; best = p.s; }
    }
    if (best && this.onpick) this.onpick(best);
  }
}

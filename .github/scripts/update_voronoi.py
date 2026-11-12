#!/usr/bin/env python3
"""Draw a power diagram whose cell areas equal each language's share of code.

Reads language byte counts of the owner's public, non-fork repositories from the
GitHub API (standard library only), solves the cell weights and writes an SVG.

Usage:  python update_voronoi.py --owner NAME [--config FILE] [--out FILE] [--fake FILE]
--fake takes a JSON file {"repo": {"Language": bytes}} instead of calling the API (for tests).
"""
import argparse, json, math, os, sys, urllib.request, collections

COLORS = {"Python": "#4584b6", "TypeScript": "#3178c6", "R": "#1fa89a", "Jupyter Notebook": "#F37626",
          "CSS": "#663399", "HTML": "#e34c26", "C++": "#f34b7d", "C": "#7a7a7a", "Java": "#b07219",
          "SQL": "#e38c00", "Shell": "#89e051", "JavaScript": "#d4b800", "Rust": "#dea584",
          "Go": "#00ADD8", "Julia": "#a270ba", "MATLAB": "#e16737", "TeX": "#3D6117"}
FALLBACK = ["#8a6fdf", "#d97a8c", "#5aa469", "#c2a24b", "#5fa8d3", "#b5651d"]
LIGHT_FILLS = {"#d4b800", "#89e051", "#dea584", "#e38c00"}


def api(path, token):
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "voronoi-territory",
        **({"Authorization": "Bearer " + token} if token else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def collect(owner, token, cfg, fake=None):
    if fake:
        per_repo = json.load(open(fake, encoding="utf-8"))
    else:
        repos, page = [], 1
        while True:
            batch = api(f"/users/{owner}/repos?per_page=100&type=owner&page={page}", token)
            repos += batch
            if len(batch) < 100:
                break
            page += 1
        per_repo = {r["name"]: api(f"/repos/{owner}/{r['name']}/languages", token)
                    for r in repos if not r["fork"] and not r["archived"]}
    total = collections.Counter()
    for repo, langs in per_repo.items():
        if repo in cfg.get("exclude_repos", []):
            continue
        for lang, n in langs.items():
            if lang in cfg.get("exclude_languages", []):
                continue
            total[cfg.get("merge_languages", {}).get(lang, lang)] += n * cfg.get("weights", {}).get(lang, 1.0)
    return total


def select(total, cfg):
    s = sum(total.values())
    if s == 0:
        sys.exit("no language data found, keeping the existing image")
    items = [(k, v / s) for k, v in total.most_common() if v / s >= cfg.get("min_share", 0.01)]
    items = items[: cfg.get("max_cells", 8)]
    t = sum(v for _, v in items)
    return [k for k, _ in items], [v / t for _, v in items]


W, H = 620.0, 420.0


def clip(poly, a, b, wa, wb):
    ax, ay = a; bx, by = b; dx, dy = bx - ax, by - ay; d2 = dx * dx + dy * dy
    t = 0.5 + (wa - wb) / (2 * d2)
    mx, my = ax + dx * t, ay + dy * t
    f = lambda p: (p[0] - mx) * dx + (p[1] - my) * dy
    out = []
    for i in range(len(poly)):
        p, q = poly[i], poly[(i + 1) % len(poly)]; fp, fq = f(p), f(q)
        if fp <= 0: out.append(p)
        if (fp < 0 < fq) or (fq < 0 < fp):
            s = fp / (fp - fq); out.append((p[0] + (q[0] - p[0]) * s, p[1] + (q[1] - p[1]) * s))
    return out


def area(p):
    return abs(sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))) / 2 if len(p) > 2 else 0


def centroid(p):
    A = cx = cy = 0
    for i in range(len(p)):
        x0, y0 = p[i]; x1, y1 = p[(i + 1) % len(p)]; c = x0 * y1 - x1 * y0
        A += c; cx += (x0 + x1) * c; cy += (y0 + y1) * c
    return (cx / (3 * A), cy / (3 * A)) if A else p[0]


def solve(share):
    n = len(share)
    if n == 1:
        return [[(0, 0), (W, 0), (W, H), (0, H)]], 0.0
    sites = [[W * 0.38, H * 0.5]] + [[W / 2 + W * 0.42 * math.cos(2 * math.pi * i / (n - 1) + 0.6),
                                       H / 2 + H * 0.40 * math.sin(2 * math.pi * i / (n - 1) + 0.6)] for i in range(n - 1)]
    w = [0.0] * n

    def cells():
        res = []
        for i in range(n):
            poly = [(0, 0), (W, 0), (W, H), (0, H)]
            for j in range(n):
                if i != j and poly: poly = clip(poly, sites[i], sites[j], w[i], w[j])
            res.append(poly)
        return res
    scale = W * H
    for it in range(800):
        cs = cells(); ar = [area(c) / scale for c in cs]
        for i in range(n): w[i] += (share[i] - ar[i]) * scale * 0.55
        m = max(w); w = [x - m for x in w]
        if it % 3 == 2:
            for i in range(n):
                if len(cs[i]) > 2:
                    cx, cy = centroid(cs[i]); sites[i][0] += (cx - sites[i][0]) * 0.25; sites[i][1] += (cy - sites[i][1]) * 0.25
    cs = cells(); ar = [area(c) / scale for c in cs]
    return cs, max(abs(a - s) for a, s in zip(ar, share)) * 100


def render(names, share, cs, title):
    cols, k = {}, 0
    for nme in names:
        if nme in COLORS: cols[nme] = COLORS[nme]
        else: cols[nme] = FALLBACK[k % len(FALLBACK)]; k += 1
    width, height = int(W) + 250, int(H) + 40
    alt = f"{title}: languages by area. " + ", ".join(f"{a} {s * 100:.1f}%" for a, s in zip(names, share))
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{alt}">',
         '<style>text{font-family:Helvetica,Arial,sans-serif}</style>', '<rect width="100%" height="100%" rx="10" fill="#0b0f16"/>', '<g transform="translate(20,20)">']
    for i, c in enumerate(cs):
        o.append(f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in c)}" fill="{cols[names[i]]}" stroke="#0b0f16" stroke-width="3" stroke-linejoin="round"/>')
    for i, c in enumerate(cs):
        if share[i] >= 0.04 and len(c) > 2:
            cx, cy = centroid(c); ink = "#0b0f16" if cols[names[i]] in LIGHT_FILLS else "#ffffff"
            fs = 22 if share[i] > 0.3 else 14
            o.append(f'<text x="{cx:.0f}" y="{cy:.0f}" text-anchor="middle" fill="{ink}" font-size="{fs}" font-weight="700">{names[i]}</text>'
                     f'<text x="{cx:.0f}" y="{cy + fs + 2:.0f}" text-anchor="middle" fill="{ink}" font-size="{fs - 4}" opacity=".9">{share[i] * 100:.1f}%</text>')
    o.append('</g>')
    lx = int(W) + 40
    for i, nme in enumerate(names):
        y = 52 + i * 30
        o.append(f'<rect x="{lx}" y="{y - 11}" width="14" height="14" rx="3" fill="{cols[nme]}"/><text x="{lx + 22}" y="{y}" fill="#c8d2e8" font-size="14">{nme}</text>'
                 f'<text x="{lx + 170}" y="{y}" text-anchor="end" fill="#7c86b8" font-size="14">{share[i] * 100:.1f}%</text>')
    o.append(f'<text x="{lx}" y="{int(H) + 8}" fill="#7c86b8" font-size="10">Cell area = share of code in my public repos</text></svg>')
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--config", default=".github/voronoi-config.json")
    ap.add_argument("--out", default="assets/voronoi-territory.svg")
    ap.add_argument("--fake")
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    total = collect(a.owner, os.environ.get("GITHUB_TOKEN"), cfg, a.fake)
    names, share = select(total, cfg)
    cs, err = solve(share)
    print(f"{len(names)} languages, max area error {err:.3f} pp:", ", ".join(f"{n} {s * 100:.1f}%" for n, s in zip(names, share)))
    if err > 0.5:
        sys.exit("solver did not converge, keeping the existing image")
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(render(names, share, cs, cfg.get("title", a.owner)))


if __name__ == "__main__":
    main()

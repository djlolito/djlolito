#!/usr/bin/env python3
"""Genera las tarjetas SVG del perfil sin depender de servicios de terceros.

Uso (dentro de GitHub Actions):
    GITHUB_TOKEN=... python3 scripts/gen_profile_cards.py djlolito dist

Escribe en el directorio de salida:
    commit-stats.svg   total de commits y contribuciones (sección 06)
    profile-stats.svg  tarjeta de estadísticas generales (sección 05)
    top-langs.svg      lenguajes más usados (sección 05)

Solo usa la librería estándar. Por defecto los lenguajes excluyen los forks
(el código de un fork no es tuyo); usa --include-forks para contarlos.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.request

import gen_commit_stats as cs

REPOS_QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    allPublic: repositories(ownerAffiliations: OWNER, privacy: PUBLIC) { totalCount }
    repositories(ownerAffiliations: OWNER, privacy: PUBLIC, isFork: %s, first: 100) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

STYLE = """
    text { font-family: 'JetBrains Mono', Consolas, 'DejaVu Sans Mono', monospace; }
    .title { fill: #39ff14; font-size: 14px; font-weight: bold; }
    .lbl { fill: #c9ffd5; font-size: 13px; }
    .val { fill: #39ff14; font-size: 14px; font-weight: bold; }
    .dim { fill: #80a88a; font-size: 12px; }
"""


def fetch_repos(login, token, include_forks):
    query = REPOS_QUERY % ("null" if include_forks else "false")
    body = json.dumps({"query": query, "variables": {"login": login}}).encode()
    req = urllib.request.Request(
        cs.API,
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "djlolito-profile-stats",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors") or not (payload.get("data") or {}).get("user"):
        raise RuntimeError(f"Error de la API GraphQL: {payload.get('errors') or 'usuario no encontrado'}")
    return payload["data"]["user"]


def summarize(user):
    """Reduce la respuesta de repos a estrellas, repos, seguidores y lenguajes."""
    langs = {}
    stars = 0
    for repo in user["repositories"]["nodes"]:
        stars += repo["stargazerCount"]
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            color = edge["node"]["color"]
            size, _ = langs.get(name, (0, color))
            langs[name] = (size + edge["size"], color)
    return {
        "stars": stars,
        "public_repos": user["allPublic"]["totalCount"],
        "followers": user["followers"]["totalCount"],
        "langs": sorted(((n, s, c) for n, (s, c) in langs.items()), key=lambda x: -x[1]),
    }


def safe_color(color):
    return color if color and re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "#39ff14"


def card(width, inner):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 165" width="{width}" height="165">\n'
        f"  <style>{STYLE}  </style>\n"
        f'  <rect x="1" y="1" width="{width - 2}" height="163" rx="10" fill="#050b07" stroke="#39ff14" stroke-width="1.5"/>\n'
        f"{inner}</svg>\n"
    )


def render_profile_stats(login, s, repo):
    rows = [
        ("Total commits", s["commits"]),
        ("Pull requests", s["prs"]),
        ("Issues", s["issues"]),
        ("Stars earned", repo["stars"]),
        ("Public repos", repo["public_repos"]),
        ("Followers", repo["followers"]),
    ]
    out = f'  <text x="24" y="34" class="title">{html.escape(login)} // GITHUB STATS</text>\n'
    for i, (label, value) in enumerate(rows):
        col, row = divmod(i, 3)
        y = 76 + row * 32
        x_label = 24 + col * 200
        x_value = 196 + col * 200
        out += f'  <text x="{x_label}" y="{y}" class="lbl">{html.escape(label)}</text>\n'
        out += f'  <text x="{x_value}" y="{y}" class="val" text-anchor="end">{html.escape(cs.fmt(value))}</text>\n'
    return card(420, out)


def render_top_langs(langs, include_forks):
    out = '  <text x="20" y="34" class="title">TOP LANGUAGES</text>\n'
    total = sum(size for _, size, _ in langs)
    if not total:
        hint = "No code in your own repos yet." if not include_forks else "No language data."
        out += f'  <text x="20" y="80" class="dim">{html.escape(hint)}</text>\n'
        if not include_forks:
            out += '  <text x="20" y="102" class="dim">Forks are not counted.</text>\n'
        return card(300, out)
    for i, (name, size, color) in enumerate(langs[:5]):
        y = 62 + i * 22
        pct = size / total * 100
        width = max(2, round(pct / 100 * 120))
        out += f'  <text x="20" y="{y}" class="lbl">{html.escape(name[:12])}</text>\n'
        out += f'  <rect x="116" y="{y - 9}" width="120" height="8" rx="4" fill="#0d2410"/>\n'
        out += f'  <rect x="116" y="{y - 9}" width="{width}" height="8" rx="4" fill="{safe_color(color)}"/>\n'
        out += f'  <text x="280" y="{y}" class="dim" text-anchor="end">{pct:.1f}%</text>\n'
    return card(300, out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    include_forks = "--include-forks" in sys.argv
    if len(args) != 2:
        sys.exit("Uso: gen_profile_cards.py <usuario> <directorio_salida> [--include-forks]")
    login, outdir = args
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("Falta la variable de entorno GITHUB_TOKEN")

    stats = cs.collect(login, cs.make_gql(token), dt.datetime.now(cs.UTC))
    repo = summarize(fetch_repos(login, token, include_forks))

    os.makedirs(outdir, exist_ok=True)
    files = {
        "commit-stats.svg": cs.render(stats),
        "profile-stats.svg": render_profile_stats(login, stats, repo),
        "top-langs.svg": render_top_langs(repo["langs"], include_forks),
    }
    for name, content in files.items():
        with open(os.path.join(outdir, name), "w", encoding="utf-8") as f:
            f.write(content)
    print(f"OK: {stats['commits']} commits, {len(repo['langs'])} lenguajes -> {outdir}/ ({', '.join(files)})")


if __name__ == "__main__":
    main()

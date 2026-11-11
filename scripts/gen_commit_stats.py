#!/usr/bin/env python3
"""Genera un SVG con el número real de commits de un usuario de GitHub.

Uso (dentro de GitHub Actions):
    GITHUB_TOKEN=... python3 scripts/gen_commit_stats.py djlolito dist/commit-stats.svg

Solo usa la librería estándar. Consulta la API GraphQL de GitHub año por año
(la API limita cada consulta a un máximo de 1 año) y suma los totales.
Los números son los que ve un visitante del perfil (actividad pública).
"""
import datetime as dt
import html
import json
import os
import sys
import urllib.request

API = "https://api.github.com/graphql"
UTC = dt.timezone.utc

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    createdAt
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_gql(token):
    def gql(login, start, end):
        body = json.dumps(
            {"query": QUERY, "variables": {"login": login, "from": iso(start), "to": iso(end)}}
        ).encode()
        req = urllib.request.Request(
            API,
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

    return gql


def add_days(days, collection):
    """Mezcla los días de un calendario en `days` ({fecha: nº}). Con max() un día
    repetido entre dos ventanas nunca se pisa con un 0."""
    for week in collection["contributionCalendar"]["weeks"]:
        for d in week["contributionDays"]:
            days[d["date"]] = max(days.get(d["date"], 0), d["contributionCount"])


def collect(login, gql, now):
    """Devuelve los totales. `gql(login, start, end)` devuelve el nodo `user`."""
    last = gql(login, now - dt.timedelta(days=365), now)
    created = dt.datetime.strptime(last["createdAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)

    totals = {"commits": 0, "prs": 0, "issues": 0, "private": 0}
    days = {}
    add_days(days, last["contributionsCollection"])
    for year in range(created.year, now.year + 1):
        start = max(created, dt.datetime(year, 1, 1, tzinfo=UTC))
        end = min(dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC), now)
        cc = gql(login, start, end)["contributionsCollection"]
        totals["commits"] += cc["totalCommitContributions"]
        totals["prs"] += cc["totalPullRequestContributions"]
        totals["issues"] += cc["totalIssueContributions"]
        totals["private"] += cc["restrictedContributionsCount"]
        add_days(days, cc)

    totals["last_year"] = last["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    totals["since"] = created.year
    totals["login"] = login
    totals["updated"] = now.strftime("%Y-%m-%d")
    totals["days"] = days
    return totals


def fmt(n):
    return f"{n:,}".replace(",", ".")


def render(s):
    """Tarjeta ancha 560x210: pensada para que se lea también al encogerla en móvil."""

    def block(x, value, label):
        return (
            f'<text x="{x}" y="108" class="num">{html.escape(fmt(value))}</text>'
            f'<text x="{x}" y="134" class="lbl">{html.escape(label)}</text>'
        )

    foot1 = f"since {s['since']} // updated {s['updated']} UTC"
    foot2 = "public activity only (what visitors see)"
    if s["private"]:
        foot2 += f" // +{fmt(s['private'])} private"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 210" width="560" height="210" role="img" aria-label="Commit statistics for {html.escape(s['login'])}">
  <title>Commit statistics for {html.escape(s['login'])}</title>
  <style>
    text {{ font-family: 'JetBrains Mono', Consolas, 'DejaVu Sans Mono', monospace; }}
    .cmd {{ fill: #39ff14; font-size: 14px; }}
    .num {{ fill: #39ff14; font-size: 40px; font-weight: bold; }}
    .lbl {{ fill: #c9ffd5; font-size: 13px; letter-spacing: .5px; }}
    .foot {{ fill: #80a88a; font-size: 12px; }}
  </style>
  <rect x="1" y="1" width="558" height="208" rx="10" fill="#050b07" stroke="#39ff14" stroke-width="1.5"/>
  <text x="28" y="38" class="cmd">root@kaosnet:~$ git log --author={html.escape(s['login'])} | wc -l</text>
  {block(28, s['commits'], 'TOTAL COMMITS')}
  {block(178, s['last_year'], 'CONTRIBUTIONS 12M')}
  {block(346, s['prs'], 'PULL REQUESTS')}
  {block(480, s['issues'], 'ISSUES')}
  <text x="28" y="172" class="foot">{html.escape(foot1)}</text>
  <text x="28" y="190" class="foot">{html.escape(foot2)}</text>
</svg>
"""


def main():
    if len(sys.argv) != 3:
        sys.exit("Uso: gen_commit_stats.py <usuario> <salida.svg>")
    login, out = sys.argv[1], sys.argv[2]
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("Falta la variable de entorno GITHUB_TOKEN")

    stats = collect(login, make_gql(token), dt.datetime.now(UTC))
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(stats))
    print(f"OK: {stats['commits']} commits, {stats['last_year']} contribuciones en 12 meses -> {out}")


if __name__ == "__main__":
    main()

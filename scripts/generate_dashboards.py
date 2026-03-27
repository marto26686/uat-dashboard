#!/usr/bin/env python3
"""
generate_dashboards.py — HBI Plataforma Sprint Dashboard Generator
Grupo Petersen · Canales Digitales

Uso local:
    python3 scripts/generate_dashboards.py \
        --jira-url https://jira.gbsj.com.ar \
        --jira-user usuario@gbsj.com.ar \
        --jira-token <token_o_password> \
        --board 650

En GitHub Actions usa las variables de entorno:
    JIRA_URL, JIRA_USER, JIRA_TOKEN, JIRA_BOARD_ID
"""

import os, sys, json, hashlib, argparse, datetime, base64
from pathlib import Path
from urllib import request, error
from urllib.parse import urlencode

# ─── CONFIG ────────────────────────────────────────────────────────────────────
AUTH_HASH   = "d690597c86eda77739afadffe0cd8b34f4a8069278a829553aac6ba0fc21f9eb"
OUTPUT_DIR  = Path(__file__).parent.parent  # raíz del repo
SCRIPT_DIR  = Path(__file__).parent

# ─── JIRA CLIENT ───────────────────────────────────────────────────────────────
class JiraClient:
    def __init__(self, base_url: str, user: str, token: str):
        self.base = base_url.rstrip("/")
        creds = base64.b64encode(f"{user}:{token}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {creds}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def get(self, path: str) -> dict:
        url = f"{self.base}{path}"
        req = request.Request(url, headers=self.headers)
        try:
            with request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except error.HTTPError as e:
            print(f"[ERROR] HTTP {e.code} → {url}", file=sys.stderr)
            raise

    def get_active_sprint(self, board_id: int) -> dict | None:
        data = self.get(f"/rest/agile/1.0/board/{board_id}/sprint?state=active")
        sprints = data.get("values", [])
        return sprints[0] if sprints else None

    def get_sprint_issues(self, sprint_id: int, max_results: int = 200) -> list:
        fields = "summary,status,issuetype,priority,assignee,customfield_10016,labels,created,updated,resolutiondate"
        path = f"/rest/agile/1.0/sprint/{sprint_id}/issue?maxResults={max_results}&fields={fields}"
        data = self.get(path)
        return data.get("issues", [])


# ─── DATA PROCESSING ───────────────────────────────────────────────────────────
def process_issues(raw_issues: list) -> dict:
    issues = []
    for i in raw_issues:
        f = i.get("fields", {})
        status = f.get("status", {})
        issues.append({
            "key":            i["key"],
            "summary":        f.get("summary", ""),
            "status":         status.get("name", ""),
            "status_cat":     status.get("statusCategory", {}).get("name", ""),
            "type":           f.get("issuetype", {}).get("name", ""),
            "priority":       f.get("priority", {}).get("name", ""),
            "assignee":       (f.get("assignee") or {}).get("displayName", "Sin asignar"),
            "story_points":   f.get("customfield_10016"),
            "labels":         f.get("labels", []),
            "created":        f.get("created", ""),
            "updated":        f.get("updated", ""),
            "resolution_date": f.get("resolutiondate"),
        })

    by_status  = {}
    by_type    = {}
    by_assignee = {}
    for i in issues:
        by_status[i["status"]]    = by_status.get(i["status"], 0) + 1
        by_type[i["type"]]        = by_type.get(i["type"], 0) + 1
        by_assignee[i["assignee"]]= by_assignee.get(i["assignee"], 0) + 1

    listo    = sum(v for k, v in by_status.items() if "listo" in k.lower() or "done" in k.lower())
    testing  = sum(v for k, v in by_status.items() if "testing" in k.lower() or "test" in k.lower())
    progress = sum(v for k, v in by_status.items() if "progres" in k.lower() or "progress" in k.lower())
    todo     = sum(v for k, v in by_status.items() if "hacer" in k.lower() or "do" in k.lower() or "open" in k.lower())
    total    = len(issues)

    return {
        "issues":      issues,
        "total":       total,
        "by_status":   by_status,
        "by_type":     by_type,
        "by_assignee": by_assignee,
        "counts": {
            "listo":    listo,
            "testing":  testing,
            "progress": progress,
            "todo":     todo,
        },
        "pcts": {
            "listo":    round(listo   / total * 100, 1) if total else 0,
            "testing":  round(testing / total * 100, 1) if total else 0,
            "progress": round(progress/ total * 100, 1) if total else 0,
            "todo":     round(todo    / total * 100, 1) if total else 0,
            "done_plus_test": round((listo + testing) / total * 100, 1) if total else 0,
        },
    }


def sprint_days(sprint: dict) -> dict:
    fmt = "%Y-%m-%dT%H:%M:%S.%f%z"
    try:
        start = datetime.datetime.fromisoformat(sprint["startDate"])
        end   = datetime.datetime.fromisoformat(sprint["endDate"])
        today = datetime.datetime.now(tz=start.tzinfo)
        total_days   = (end - start).days
        elapsed_days = min((today - start).days, total_days)
        remaining    = max(total_days - elapsed_days, 0)
        time_pct     = round(elapsed_days / total_days * 100, 1) if total_days else 0
        return {
            "start":      start.strftime("%d/%m/%Y"),
            "end":        end.strftime("%d/%m/%Y"),
            "today":      today.strftime("%d/%m/%Y"),
            "total":      total_days,
            "elapsed":    elapsed_days,
            "remaining":  remaining,
            "time_pct":   time_pct,
        }
    except Exception as e:
        print(f"[WARN] No se pudo calcular días: {e}", file=sys.stderr)
        return {"start": "—", "end": "—", "today": "—", "total": 0, "elapsed": 0, "remaining": 0, "time_pct": 0}


# ─── AUTH GATE SNIPPET ─────────────────────────────────────────────────────────
def auth_gate_js(hash_val: str, page_title: str) -> str:
    return f"""
<script>
(function() {{
  const HASH = "{hash_val}";
  const KEY  = "gp_hbi_auth_v1";

  async function sha256(msg) {{
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(msg));
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2,"0")).join("");
  }}

  function showGate() {{
    document.body.style.overflow = "hidden";
    const gate = document.createElement("div");
    gate.id = "auth-gate";
    gate.innerHTML = `
      <div style="position:fixed;inset:0;background:#000;z-index:99999;display:flex;align-items:center;justify-content:center;font-family:'Inter',system-ui,sans-serif">
        <div style="background:#111;border:1px solid #2C2C2C;border-radius:16px;padding:36px 40px;width:100%;max-width:380px;text-align:center">
          <div style="width:44px;height:44px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:800;color:#000;margin:0 auto 20px">G·P</div>
          <div style="font-size:11px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;color:#6B6B6B;margin-bottom:6px">Grupo Petersen · Canales Digitales</div>
          <div style="font-size:18px;font-weight:800;color:#fff;margin-bottom:4px">{page_title}</div>
          <div style="font-size:12px;color:#6B6B6B;margin-bottom:24px">Acceso restringido · HBI Plataforma</div>
          <input id="gate-pw" type="password" placeholder="Contraseña de acceso" autocomplete="current-password"
            style="width:100%;padding:11px 14px;background:#1A1A1A;border:1px solid #2C2C2C;border-radius:8px;color:#fff;font-size:13px;font-family:inherit;outline:none;margin-bottom:10px">
          <div id="gate-err" style="font-size:11px;color:#CC1A1A;min-height:16px;margin-bottom:10px"></div>
          <button id="gate-btn"
            style="width:100%;padding:11px;background:#F5A800;border:none;border-radius:8px;font-size:13px;font-weight:800;color:#000;cursor:pointer;font-family:inherit;letter-spacing:-.01em">
            Ingresar
          </button>
          <div style="font-size:10px;color:#444;margin-top:16px">Sprint HBI Plataforma · Uso interno</div>
        </div>
      </div>
    `;
    document.body.appendChild(gate);

    const pw  = gate.querySelector("#gate-pw");
    const btn = gate.querySelector("#gate-btn");
    const err = gate.querySelector("#gate-err");

    pw.addEventListener("keydown", e => {{ if (e.key === "Enter") btn.click(); }});

    btn.addEventListener("click", async () => {{
      btn.textContent = "Verificando…";
      btn.disabled = true;
      const h = await sha256(pw.value);
      if (h === HASH) {{
        sessionStorage.setItem(KEY, HASH);
        gate.style.opacity = "0";
        gate.style.transition = "opacity .3s";
        setTimeout(() => {{ gate.remove(); document.body.style.overflow = ""; }}, 300);
      }} else {{
        err.textContent = "Contraseña incorrecta. Intentá de nuevo.";
        pw.value = "";
        pw.focus();
        btn.textContent = "Ingresar";
        btn.disabled = false;
      }}
    }});

    setTimeout(() => pw.focus(), 100);
  }}

  if (sessionStorage.getItem(KEY) !== HASH) {{
    if (document.readyState === "loading") {{
      document.addEventListener("DOMContentLoaded", showGate);
    }} else {{
      showGate();
    }}
  }}
}})();
</script>
"""


# ─── HTML GENERATORS ───────────────────────────────────────────────────────────
def generate_dashboard(sprint: dict, data: dict, days: dict) -> str:
    sprint_name = sprint.get("name", "Sprint Activo")
    sprint_goal = sprint.get("goal", "Sin objetivo definido")
    counts  = data["counts"]
    pcts    = data["pcts"]
    total   = data["total"]
    assignee_sorted = sorted(data["by_assignee"].items(), key=lambda x: -x[1])
    max_assign = assignee_sorted[0][1] if assignee_sorted else 1

    # Build assignee rows
    assignee_rows = ""
    colors = ["#1A5FA0","#267D26","#C98A00","#2C2C2C","#991212","#444","#1A5A1A","#2B7FD4","#6B6B6B","#000"]
    for idx, (name, count) in enumerate(assignee_sorted[:12]):
        initials = "".join(p[0].upper() for p in name.strip().split()[:2]) if name != "Sin asignar" else "—"
        color    = colors[idx % len(colors)]
        bar_pct  = round(count / max_assign * 100)
        assignee_rows += f"""
        <div class="assign-row">
          <div class="assign-avatar" style="background:{color}">{initials}</div>
          <div class="assign-name">{name}</div>
          <div class="assign-bar-wrap"><div class="assign-bar" style="width:{bar_pct}%"></div></div>
          <div class="assign-count">{count}</div>
        </div>"""

    # Build issues table rows (non-subtasks)
    main_issues = [i for i in data["issues"] if i["type"] != "Subtarea"]
    table_rows = ""
    status_badge = {
        "listo": '<span class="badge b-done">✓ Listo</span>',
        "en testing": '<span class="badge b-test">En Testing</span>',
        "en progreso": '<span class="badge b-prog">En progreso</span>',
        "por hacer": '<span class="badge b-todo">Por hacer</span>',
    }
    type_chip = {
        "Historia": '<span class="type-chip t-hist">Historia</span>',
        "Spike":    '<span class="type-chip t-spik">Spike</span>',
        "Tarea":    '<span class="type-chip t-task">Tarea</span>',
    }
    for iss in main_issues:
        st_key = iss["status"].lower()
        badge  = next((v for k, v in status_badge.items() if k in st_key),
                      f'<span class="badge b-todo">{iss["status"]}</span>')
        chip   = type_chip.get(iss["type"],
                               f'<span class="type-chip t-other">{iss["type"]}</span>')
        assignee_short = " ".join(iss["assignee"].strip().split()[:2])
        summary_short  = iss["summary"][:72] + ("…" if len(iss["summary"]) > 72 else "")
        table_rows += f"""
            <tr>
              <td>{iss["key"]}</td>
              <td><div class="issue-sum">{summary_short}</div></td>
              <td>{chip}</td>
              <td>{badge}</td>
              <td>{assignee_short}</td>
            </tr>"""

    # Goal lines
    goals_html = ""
    for idx, line in enumerate(sprint_goal.split("\n"), 1):
        line = line.strip()
        if not line:
            continue
        # Remove "1-", "2-", etc. prefixes from Jira
        import re
        line = re.sub(r"^\d+[-\.]\s*", "", line)
        goals_html += f"""
      <div class="goal-item">
        <div class="goal-num">{idx}</div>
        <div class="goal-text">{line}</div>
      </div>"""

    generated = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sprint Dashboard — {sprint_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
{auth_gate_js(AUTH_HASH, "Sprint Dashboard")}
<style>
  :root{{--black:#000;--g900:#111;--g800:#1A1A1A;--g700:#2C2C2C;--g600:#444;--g500:#6B6B6B;--g400:#909090;--g300:#C4C4C4;--g200:#E0E0E0;--g100:#F0F0F0;--g50:#F5F5F5;--white:#fff;--bsj:#F5A800;--bsj-dk:#C98A00;--ok:#1A8A4A;--warn:#D48A00;--err:#CC1A1A;--info:#2B7FD4;--font:'Inter',system-ui,sans-serif;--mono:'DM Mono',monospace;--r-sm:6px;--r-md:10px;--r-lg:14px;--r-xl:20px;--r-full:9999px;--sh-card:0 1px 3px rgba(0,0,0,.05),0 4px 14px rgba(0,0,0,.06);--sh-hover:0 4px 12px rgba(0,0,0,.12),0 8px 32px rgba(0,0,0,.08);}}
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
  body{{background:var(--g50);color:var(--black);font-family:var(--font);font-size:14px;line-height:1.6;}}
  .hdr{{background:var(--black);position:relative;overflow:hidden;}}
  .sh{{position:absolute;border-radius:16px;background:rgba(255,255,255,.04);}}
  .sh1{{width:220px;height:110px;right:80px;top:28px;transform:rotate(-7deg);}}
  .sh2{{width:140px;height:140px;right:270px;top:-28px;transform:rotate(14deg);}}
  .sh3{{width:180px;height:75px;right:36px;bottom:16px;transform:rotate(4deg);}}
  .hdr-inner{{position:relative;max-width:1140px;margin:0 auto;padding:42px 48px 36px;display:flex;justify-content:space-between;align-items:flex-end;gap:40px;}}
  .gp-circle{{width:38px;height:38px;border-radius:50%;background:var(--white);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:800;color:var(--black);}}
  .gp-word{{color:var(--white);font-size:13px;font-weight:600;line-height:1.3;}}
  .gp-word span{{display:block;font-weight:300;font-size:10px;color:var(--g400);letter-spacing:.1em;text-transform:uppercase;margin-top:1px;}}
  .hdr-logo{{display:flex;align-items:center;gap:13px;margin-bottom:18px;}}
  .hdr h1{{font-size:30px;font-weight:800;color:var(--white);line-height:1.1;letter-spacing:-.025em;}}
  .hdr h1 em{{font-style:normal;color:var(--g400);font-weight:300;}}
  .ver-tag{{display:inline-block;background:rgba(245,168,0,.15);color:var(--bsj);font-size:11px;font-weight:600;letter-spacing:.06em;padding:4px 12px;border-radius:var(--r-full);border:1px solid rgba(245,168,0,.3);margin-bottom:8px;}}
  .hdr-right{{text-align:right;flex-shrink:0;}}
  .hdr-meta{{font-size:11px;color:var(--g500);line-height:1.9;font-family:var(--mono);}}
  .hdr-meta strong{{color:var(--g300);}}
  .body{{max-width:1140px;margin:0 auto;padding:40px 48px 60px;display:flex;flex-direction:column;gap:32px;}}
  .eyebrow{{font-size:10px;font-weight:700;letter-spacing:.2em;text-transform:uppercase;color:var(--g400);margin-bottom:4px;}}
  .section-title{{font-size:17px;font-weight:700;letter-spacing:-.02em;color:var(--black);margin-bottom:16px;padding-bottom:12px;border-bottom:1.5px solid var(--g200);display:flex;align-items:center;justify-content:space-between;}}
  .section-title span{{font-size:12px;font-weight:400;color:var(--g400);letter-spacing:0;}}
  .kpi-row{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;}}
  .kpi-card{{background:var(--white);border-radius:var(--r-lg);padding:18px 16px 16px;border:1px solid var(--g200);box-shadow:var(--sh-card);border-top:3px solid var(--g300);transition:box-shadow .2s;}}
  .kpi-card:hover{{box-shadow:var(--sh-hover);}}
  .kpi-card.done{{border-top-color:var(--ok);}} .kpi-card.prog{{border-top-color:var(--bsj);}}
  .kpi-card.test{{border-top-color:var(--info);}} .kpi-card.todo{{border-top-color:var(--g400);}}
  .kpi-card.total{{border-top-color:var(--black);}}
  .kpi-label{{font-size:9px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--g400);margin-bottom:10px;}}
  .kpi-val{{font-size:38px;font-weight:800;letter-spacing:-.04em;color:var(--black);line-height:1;}}
  .kpi-pct{{font-size:11px;font-weight:500;color:var(--g500);margin-top:6px;}}
  .kpi-pct strong{{font-weight:700;}} .kpi-pct.ok strong{{color:var(--ok);}} .kpi-pct.warn strong{{color:var(--warn);}} .kpi-pct.info strong{{color:var(--info);}}
  .progress-card{{background:var(--white);border-radius:var(--r-lg);padding:22px 24px;border:1px solid var(--g200);box-shadow:var(--sh-card);}}
  .prog-header{{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:16px;}}
  .prog-title{{font-size:13px;font-weight:700;color:var(--black);}} .prog-sub{{font-size:11px;color:var(--g500);margin-top:2px;}}
  .prog-pct-big{{font-size:32px;font-weight:800;letter-spacing:-.03em;color:var(--black);}}
  .prog-pct-big span{{font-size:14px;font-weight:500;color:var(--g400);}}
  .prog-track{{height:10px;background:var(--g100);border-radius:var(--r-full);overflow:hidden;margin-bottom:10px;display:flex;gap:2px;}}
  .prog-fill{{height:100%;border-radius:var(--r-full);}}
  .prog-fill.done{{background:var(--ok);}} .prog-fill.test{{background:var(--info);}} .prog-fill.prog{{background:var(--bsj);}} .prog-fill.todo{{background:var(--g200);}}
  .prog-legend{{display:flex;gap:18px;flex-wrap:wrap;}}
  .leg{{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--g600);}}
  .leg-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0;}}
  .goals-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;}}
  .goal-item{{background:var(--white);border-radius:var(--r-md);padding:14px 16px;border:1px solid var(--g200);box-shadow:var(--sh-card);display:flex;gap:12px;align-items:flex-start;}}
  .goal-num{{width:24px;height:24px;border-radius:50%;background:var(--g900);color:var(--white);font-size:10px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:1px;}}
  .goal-text{{font-size:12px;color:var(--g700);line-height:1.5;}}
  .two-col{{display:grid;grid-template-columns:1.4fr 1fr;gap:20px;}}
  .table-card{{background:var(--white);border-radius:var(--r-lg);border:1px solid var(--g200);box-shadow:var(--sh-card);overflow:hidden;}}
  .table-hdr{{background:var(--g900);padding:10px 16px;display:flex;justify-content:space-between;align-items:center;}}
  .table-hdr-t{{font-size:10px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--g400);}}
  .ds-table{{width:100%;border-collapse:collapse;font-size:12px;}}
  .ds-table thead th{{background:var(--g100);color:var(--g500);font-size:9px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;padding:8px 14px;text-align:left;border-bottom:1px solid var(--g200);}}
  .ds-table tbody tr{{border-bottom:1px solid var(--g100);transition:background .15s;}}
  .ds-table tbody tr:hover{{background:var(--g50);}} .ds-table tbody tr:last-child{{border-bottom:none;}}
  .ds-table td{{padding:10px 14px;color:var(--g700);vertical-align:middle;}}
  .ds-table td:first-child{{font-family:var(--mono);font-size:10px;font-weight:500;color:var(--g500);white-space:nowrap;}}
  .issue-sum{{font-size:12px;font-weight:600;color:var(--black);line-height:1.35;}}
  .badge{{padding:2px 9px;border-radius:var(--r-full);font-size:10px;font-weight:600;white-space:nowrap;display:inline-flex;align-items:center;gap:4px;}}
  .b-done{{background:rgba(26,138,74,.1);color:var(--ok);}} .b-prog{{background:rgba(245,168,0,.12);color:var(--bsj-dk);}}
  .b-test{{background:rgba(43,127,212,.1);color:#1A5FA0;}} .b-todo{{background:var(--g100);color:var(--g500);}}
  .type-chip{{font-size:9px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:2px 7px;border-radius:4px;white-space:nowrap;}}
  .t-hist{{background:rgba(43,127,212,.1);color:#1A5FA0;}} .t-spik{{background:var(--g100);color:var(--g500);}}
  .t-task{{background:rgba(38,125,38,.08);color:#1A5A1A;}} .t-other{{background:var(--g50);color:var(--g400);}}
  .assign-list{{display:flex;flex-direction:column;}}
  .assign-row{{display:flex;align-items:center;gap:10px;padding:9px 16px;border-bottom:1px solid var(--g100);}}
  .assign-row:last-child{{border-bottom:none;}}
  .assign-avatar{{width:28px;height:28px;border-radius:50%;color:var(--white);display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;flex-shrink:0;}}
  .assign-name{{font-size:12px;font-weight:600;color:var(--black);flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
  .assign-bar-wrap{{width:80px;background:var(--g100);border-radius:var(--r-full);height:4px;flex-shrink:0;overflow:hidden;}}
  .assign-bar{{height:100%;border-radius:var(--r-full);background:var(--bsj);}}
  .assign-count{{font-size:11px;font-weight:700;color:var(--g600);font-family:var(--mono);width:20px;text-align:right;flex-shrink:0;}}
  .day-track{{height:8px;background:var(--g100);border-radius:var(--r-full);overflow:visible;position:relative;margin-bottom:8px;}}
  .day-fill{{height:100%;background:linear-gradient(90deg,var(--black),var(--g700));border-radius:var(--r-full);}}
  .day-marker{{position:absolute;top:-3px;height:14px;width:2px;background:var(--bsj);border-radius:1px;}}
  .tl-dates{{display:flex;justify-content:space-between;font-size:10px;color:var(--g500);font-family:var(--mono);}}
  .ftr{{background:var(--black);padding:18px 48px;display:flex;align-items:center;justify-content:space-between;}}
  .ftr-l{{font-size:12px;color:var(--g500);}} .ftr-l strong{{color:var(--g300);}}
  .ftr-r{{font-family:var(--mono);font-size:10px;color:var(--g700);letter-spacing:.08em;}}
  .update-time{{font-family:var(--mono);font-size:9px;color:var(--g600);background:rgba(255,255,255,.06);padding:3px 8px;border-radius:var(--r-full);border:1px solid rgba(255,255,255,.08);}}
</style>
</head>
<body>
<header class="hdr">
  <div style="position:absolute;inset:0;overflow:hidden"><div class="sh sh1"></div><div class="sh sh2"></div><div class="sh sh3"></div></div>
  <div class="hdr-inner">
    <div>
      <div class="hdr-logo">
        <div class="gp-circle">G·P</div>
        <div class="gp-word">Grupo Petersen <span>Canales Digitales · HBI Plataforma</span></div>
      </div>
      <h1>Sprint Dashboard<br><em>& Evolución</em></h1>
    </div>
    <div class="hdr-right">
      <div class="ver-tag">{sprint_name}</div>
      <div class="hdr-meta">
        <strong>Sprint activo · {sprint.get("name","")}</strong><br>
        {days["start"]} → {days["end"]} &nbsp;·&nbsp; {days["total"]} días<br>
        Actualizado: {generated}
      </div>
    </div>
  </div>
</header>
<main class="body">
  <section>
    <div class="eyebrow">01 — Estado General</div>
    <div class="kpi-row">
      <div class="kpi-card total"><div class="kpi-label">Total Issues</div><div class="kpi-val">{total}</div><div class="kpi-pct">Sprint activo</div></div>
      <div class="kpi-card done"><div class="kpi-label">Listo</div><div class="kpi-val">{counts["listo"]}</div><div class="kpi-pct ok"><strong>{pcts["listo"]}%</strong> completado</div></div>
      <div class="kpi-card test"><div class="kpi-label">En Testing</div><div class="kpi-val">{counts["testing"]}</div><div class="kpi-pct info"><strong>{pcts["testing"]}%</strong> del total</div></div>
      <div class="kpi-card prog"><div class="kpi-label">En Progreso</div><div class="kpi-val">{counts["progress"]}</div><div class="kpi-pct warn"><strong>{pcts["progress"]}%</strong> del total</div></div>
      <div class="kpi-card todo"><div class="kpi-label">Por Hacer</div><div class="kpi-val">{counts["todo"]}</div><div class="kpi-pct"><strong>{pcts["todo"]}%</strong> del total</div></div>
    </div>
  </section>
  <section>
    <div class="eyebrow">02 — Evolución</div>
    <div style="display:grid;grid-template-columns:1fr 280px;gap:16px">
      <div class="progress-card">
        <div class="prog-header">
          <div><div class="prog-title">Progreso del Sprint</div><div class="prog-sub">Tickets completados vs. tiempo transcurrido</div></div>
          <div style="text-align:right"><div class="prog-pct-big">{pcts["done_plus_test"]}<span>%</span></div><div style="font-size:10px;color:var(--g500);margin-top:2px">Done + Testing</div></div>
        </div>
        <div class="prog-track">
          <div class="prog-fill done" style="width:{pcts["listo"]}%"></div>
          <div class="prog-fill test" style="width:{pcts["testing"]}%"></div>
          <div class="prog-fill prog" style="width:{pcts["progress"]}%"></div>
          <div class="prog-fill todo" style="width:{pcts["todo"]}%"></div>
        </div>
        <div class="prog-legend">
          <div class="leg"><div class="leg-dot" style="background:var(--ok)"></div>Listo ({counts["listo"]})</div>
          <div class="leg"><div class="leg-dot" style="background:var(--info)"></div>En Testing ({counts["testing"]})</div>
          <div class="leg"><div class="leg-dot" style="background:var(--bsj)"></div>En Progreso ({counts["progress"]})</div>
          <div class="leg"><div class="leg-dot" style="background:var(--g300)"></div>Por Hacer ({counts["todo"]})</div>
        </div>
        <div style="margin-top:20px;padding-top:16px;border-top:1px solid var(--g100)">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <div style="font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--g400)">Tiempo del Sprint</div>
            <div style="font-size:11px;color:var(--g500)">Hoy: {days["today"]}</div>
          </div>
          <div class="day-track">
            <div class="day-fill" style="width:{days["time_pct"]}%"></div>
            <div class="day-marker" style="left:{days["time_pct"]}%"></div>
          </div>
          <div class="tl-dates"><span>{days["start"]}</span><span style="color:var(--bsj);font-weight:600">◆ Hoy (día {days["elapsed"]}/{days["total"]} · {days["time_pct"]}%)</span><span>{days["end"]}</span></div>
        </div>
      </div>
      <div class="table-card" style="border-radius:var(--r-lg)">
        <div class="table-hdr"><span class="table-hdr-t">Resumen temporal</span></div>
        <div style="padding:16px;display:flex;flex-direction:column;gap:12px">
          <div style="text-align:center;padding:12px;background:var(--g50);border-radius:var(--r-md)">
            <div style="font-size:28px;font-weight:800;letter-spacing:-.03em">{days["remaining"]}</div>
            <div style="font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--g500);margin-top:2px">días restantes</div>
          </div>
          <div style="text-align:center;padding:12px;background:rgba(26,138,74,.06);border-radius:var(--r-md)">
            <div style="font-size:28px;font-weight:800;color:var(--ok);letter-spacing:-.03em">{counts["listo"]}</div>
            <div style="font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--g500);margin-top:2px">tickets cerrados</div>
          </div>
          <div style="text-align:center;padding:12px;background:rgba(245,168,0,.08);border-radius:var(--r-md)">
            <div style="font-size:28px;font-weight:800;color:var(--bsj-dk);letter-spacing:-.03em">{total - counts["listo"]}</div>
            <div style="font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--g500);margin-top:2px">tickets activos</div>
          </div>
        </div>
      </div>
    </div>
  </section>
  <section>
    <div class="eyebrow">03 — Objetivos del Sprint</div>
    <div class="section-title">Compromisos <span>Liberación: {days["end"]}</span></div>
    <div class="goals-grid">{goals_html}</div>
  </section>
  <section>
    <div class="eyebrow">04 — Issues principales</div>
    <div class="section-title">Historias, Spikes & Tareas <span>Excluye subtareas</span></div>
    <div class="two-col">
      <div class="table-card">
        <div class="table-hdr"><span class="table-hdr-t">Issues del Sprint</span><span class="update-time">{generated}</span></div>
        <table class="ds-table">
          <thead><tr><th>Key</th><th>Issue</th><th>Tipo</th><th>Estado</th><th>Responsable</th></tr></thead>
          <tbody>{table_rows}</tbody>
        </table>
      </div>
      <div style="display:flex;flex-direction:column;gap:14px">
        <div class="table-card">
          <div class="table-hdr"><span class="table-hdr-t">Por Responsable</span></div>
          <div class="assign-list">{assignee_rows}</div>
        </div>
      </div>
    </div>
  </section>
</main>
<footer class="ftr">
  <div class="ftr-l"><strong>Grupo Petersen · Canales Digitales</strong> — {sprint_name} · Dashboard interno</div>
  <div class="ftr-r">GENERADO {generated}</div>
</footer>
</body>
</html>"""


def generate_release_note(sprint: dict, data: dict, days: dict) -> str:
    sprint_name = sprint.get("name", "Sprint Activo")
    sprint_goal = sprint.get("goal", "")
    counts = data["counts"]
    pcts   = data["pcts"]
    total  = data["total"]
    generated = datetime.datetime.now().strftime("%d/%m/%Y")

    import re

    def clean_summary(s):
        """Transforma el formato 'Quiero X para Y' en un título legible para release note."""
        s = s.strip()
        # Eliminar prefijo tipo "(Parte 2) - " preservando el resto
        prefix_match = re.match(r'^(\([^)]+\)\s*[-–]\s*)', s)
        prefix = prefix_match.group(1) if prefix_match else ""
        body = s[len(prefix):]
        # Eliminar "Como X quiero "
        body = re.sub(r'^Como\s+.{1,50}?\s+quiero\s+', '', body, flags=re.IGNORECASE)
        # Eliminar "Quiero "
        body = re.sub(r'^[Qq]uiero\s+', '', body)
        # Eliminar cláusula " para que..." al final
        body = re.sub(r'\s+para\s+(que\s+)?.{0,60}$', '', body, flags=re.IGNORECASE)
        # Capitalizar primera letra
        if body:
            body = body[0].upper() + body[1:]
        return (prefix + body)[:90]

    def parse_goals(goal_text):
        """Extrae objetivos reales del campo goal del sprint, filtrando líneas de encabezado."""
        real_goals = []
        for line in goal_text.split("\n"):
            line = line.strip()
            if not line or len(line) < 5:
                continue
            # Saltar líneas de encabezado (ej. "Objetivos del sprint:")
            if re.match(r'^objetivo', line, re.IGNORECASE) and len(line) < 40:
                continue
            if line.endswith(":") and len(line) < 50:
                continue
            # Eliminar prefijo numérico "1- " o "1. "
            line = re.sub(r"^\d+[-\.\)]\s*", "", line)
            real_goals.append(line)
        return real_goals

    # Feature list: historias ordenadas por prioridad de estado
    STATUS_PRIO = {"listo": 0, "done": 0, "testing": 1, "test": 1,
                   "progreso": 2, "progress": 2, "hacer": 3, "do": 3, "open": 3}

    def status_priority(iss):
        s = iss["status"].lower()
        for k, v in STATUS_PRIO.items():
            if k in s:
                return v
        return 4

    all_stories = [i for i in data["issues"] if i["type"] == "Historia"]
    stories = sorted(all_stories, key=status_priority)

    features_html = ""
    tags = {
        "valida": ("Seguridad &amp; Fraude", "security", "🔐"),
        "fraude": ("Seguridad &amp; Fraude", "security", "🔐"),
        "qualtrics": ("Mobile · Feedback", "mobile", "📱"),
        "android": ("Mobile · Android", "mobile", "📱"),
        "ios": ("Mobile · iOS", "mobile", "📱"),
        "homebanking": ("Canal Digital", "integration", "🏦"),
        "visa": ("Mobile · Fintech", "mobile", "💳"),
        "sdk": ("Mobile · Fintech", "mobile", "💳"),
        "dispositivo": ("UX · Seguridad", "ux", "🔑"),
        "clave": ("UX · Seguridad", "ux", "🔑"),
        "mail": ("Back Office", "backoffice", "📧"),
        "instructivo": ("Back Office", "backoffice", "📧"),
        "whatsapp": ("Canal Digital", "integration", "💬"),
        "cuit": ("Back Office", "backoffice", "🔍"),
        "cuil": ("Back Office", "backoffice", "🔍"),
        "bo": ("Back Office", "backoffice", "🖥️"),
        "back office": ("Back Office", "backoffice", "🖥️"),
        "codigo postal": ("Back Office", "backoffice", "📍"),
        "postal": ("Back Office", "backoffice", "📍"),
        "modo": ("Canal Digital", "integration", "📲"),
        "atm": ("Back Office", "backoffice", "🏧"),
        "fci": ("Finanzas", "ux", "📈"),
        "cuenta": ("Core Banking", "backoffice", "🏦"),
    }
    type_icons = {"Historia": "📋", "Spike": "🔬", "Tarea": "✅"}
    tag_icons_map = {"security": "🔐", "mobile": "📱", "backoffice": "🖥️",
                     "integration": "💬", "ux": "🎨"}

    for iss in stories[:8]:
        summary = iss["summary"]
        title = clean_summary(summary)
        tag_label, tag_class, icon = "Funcionalidad", "integration", type_icons.get(iss["type"], "📋")
        sumlow = summary.lower()
        for kw, (lbl, cls, ico) in tags.items():
            if kw.lower() in sumlow:
                tag_label, tag_class, icon = lbl, cls, ico
                break
        features_html += f"""
          <div class="feature-item">
            <div class="feat-icon">{icon}</div>
            <div class="feat-body">
              <div class="feat-tag {tag_class}">{tag_label}</div>
              <div class="feat-title">{title}</div>
              <div class="feat-ticket">{iss["key"]}</div>
            </div>
          </div>"""

    # Goals — usando parser limpio
    real_goals = parse_goals(sprint_goal)
    goals_html = ""
    for idx, line in enumerate(real_goals, 1):
        goals_html += f"""
          <div class="goal-card">
            <div class="goal-num">OBJ {idx:02d}</div>
            <div class="goal-text">{line}</div>
            <div class="goal-status">⏳ En progreso</div>
          </div>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Release Note — {sprint_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
{auth_gate_js(AUTH_HASH, "Release Note")}
<style>
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
  body{{background:#F0F0F0;font-family:'Inter',-apple-system,sans-serif;font-size:15px;line-height:1.6;color:#111;-webkit-font-smoothing:antialiased;}}
  .email-wrap{{max-width:640px;margin:40px auto;border-radius:20px;overflow:hidden;box-shadow:0 8px 40px rgba(0,0,0,.14);}}
  .email-header{{background:#000;position:relative;overflow:hidden;}}
  .hdr-top{{padding:32px 40px 0;display:flex;justify-content:space-between;align-items:flex-start;position:relative;z-index:2;}}
  .gp-badge{{display:flex;align-items:center;gap:10px;}}
  .gp-circle{{width:36px;height:36px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;color:#000;flex-shrink:0;}}
  .gp-name{{color:#fff;font-size:13px;font-weight:600;line-height:1.3;}}
  .gp-name span{{display:block;font-size:10px;font-weight:400;color:#6B6B6B;letter-spacing:.1em;text-transform:uppercase;}}
  .hdr-pill{{background:rgba(245,168,0,.18);color:#F5A800;font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;padding:5px 14px;border-radius:999px;border:1px solid rgba(245,168,0,.3);}}
  .hdr-body{{padding:28px 40px 36px;position:relative;z-index:2;}}
  .hdr-label{{font-size:10px;font-weight:700;letter-spacing:.2em;text-transform:uppercase;color:#6B6B6B;margin-bottom:10px;}}
  .hdr-title{{font-size:28px;font-weight:800;color:#fff;line-height:1.1;letter-spacing:-.03em;margin-bottom:6px;}}
  .hdr-subtitle{{font-size:13px;color:#909090;margin-bottom:20px;}}
  .hdr-meta{{display:flex;gap:20px;}}
  .hdr-meta-item{{text-align:left;}}
  .hdr-meta-val{{font-size:18px;font-weight:800;color:#fff;letter-spacing:-.02em;}}
  .hdr-meta-lbl{{font-size:9px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:#6B6B6B;margin-top:1px;}}
  .hdr-meta-div{{width:1px;background:#2C2C2C;align-self:stretch;}}
  .d-shape{{position:absolute;border-radius:14px;background:rgba(255,255,255,.04);}}
  .d1{{width:180px;height:90px;right:40px;top:30px;transform:rotate(-8deg);}}
  .d2{{width:110px;height:110px;right:190px;top:-30px;transform:rotate(12deg);}}
  .d3{{width:150px;height:60px;right:20px;bottom:20px;transform:rotate(5deg);}}
  .email-body{{background:#fff;}}
  .sec{{padding:28px 40px;}}
  .sec+.sec{{border-top:1px solid #F0F0F0;}}
  .sec-eyebrow{{font-size:9px;font-weight:700;letter-spacing:.2em;text-transform:uppercase;color:#909090;margin-bottom:6px;}}
  .sec-title{{font-size:17px;font-weight:800;color:#000;letter-spacing:-.02em;margin-bottom:4px;}}
  .sec-desc{{font-size:13px;color:#6B6B6B;line-height:1.6;margin-bottom:20px;}}
  .feature-list{{display:flex;flex-direction:column;gap:10px;}}
  .feature-item{{display:flex;gap:14px;align-items:flex-start;padding:14px 16px;background:#F5F5F5;border-radius:12px;border-left:3px solid #000;}}
  .feat-icon{{width:32px;height:32px;border-radius:8px;background:#111;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:16px;}}
  .feat-body{{flex:1;min-width:0;}}
  .feat-tag{{display:inline-block;font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;padding:2px 8px;border-radius:999px;margin-bottom:5px;}}
  .feat-tag.security{{background:rgba(204,26,26,.1);color:#CC1A1A;}}
  .feat-tag.ux{{background:rgba(43,127,212,.1);color:#1A5FA0;}}
  .feat-tag.mobile{{background:rgba(38,125,38,.1);color:#1A5A1A;}}
  .feat-tag.backoffice{{background:rgba(245,168,0,.12);color:#C98A00;}}
  .feat-tag.integration{{background:#F0F0F0;color:#444;}}
  .feat-title{{font-size:13px;font-weight:700;color:#000;margin-bottom:3px;}}
  .feat-ticket{{font-size:10px;color:#C4C4C4;font-family:monospace;margin-top:4px;}}
  .goals-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;}}
  .goal-card{{background:#F5F5F5;border-radius:10px;padding:14px;}}
  .goal-num{{font-size:11px;font-weight:800;color:#F5A800;letter-spacing:.05em;margin-bottom:4px;}}
  .goal-text{{font-size:12px;font-weight:600;color:#111;line-height:1.4;}}
  .goal-status{{display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:600;margin-top:6px;padding:2px 8px;border-radius:999px;background:rgba(212,138,0,.1);color:#D48A00;}}
  .stats-row{{display:flex;background:#000;border-radius:12px;overflow:hidden;margin-bottom:16px;}}
  .stat-block{{flex:1;padding:18px 14px;text-align:center;}}
  .stat-block+.stat-block{{border-left:1px solid #2C2C2C;}}
  .stat-val{{font-size:26px;font-weight:800;color:#fff;letter-spacing:-.04em;line-height:1;}}
  .stat-val.green{{color:#1A8A4A;}} .stat-val.blue{{color:#2B7FD4;}} .stat-val.amber{{color:#F5A800;}}
  .stat-lbl{{font-size:9px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:#6B6B6B;margin-top:4px;}}
  .ep-track{{height:8px;background:#E0E0E0;border-radius:999px;overflow:hidden;display:flex;margin-bottom:8px;}}
  .ep-fill{{height:100%;}}
  .ep-done{{background:#1A8A4A;width:{pcts["listo"]}%;}}
  .ep-test{{background:#2B7FD4;width:{pcts["testing"]}%;}}
  .ep-prog{{background:#F5A800;width:{pcts["progress"]}%;}}
  .ep-todo{{background:#E0E0E0;width:{pcts["todo"]}%;}}
  .timeline-banner{{background:linear-gradient(135deg,#1A1A1A,#000);border-radius:12px;padding:18px 20px;display:flex;align-items:center;justify-content:space-between;margin-top:16px;}}
  .tl-item{{text-align:center;}}
  .tl-val{{font-size:18px;font-weight:800;color:#fff;letter-spacing:-.03em;}}
  .tl-lbl{{font-size:9px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:#6B6B6B;margin-top:2px;}}
  .tl-div{{width:1px;background:#2C2C2C;align-self:stretch;}}
  .tl-highlight .tl-val{{color:#F5A800;}}
  .cta-section{{padding:24px 40px;background:#F5F5F5;}}
  .cta-box{{background:#000;border-radius:14px;padding:22px 26px;display:flex;align-items:center;justify-content:space-between;gap:20px;}}
  .cta-title{{font-size:14px;font-weight:800;color:#fff;margin-bottom:4px;}}
  .cta-sub{{font-size:12px;color:#6B6B6B;}}
  .cta-btn{{background:#F5A800;color:#000;font-size:12px;font-weight:800;padding:10px 20px;border-radius:8px;text-decoration:none;white-space:nowrap;display:inline-block;}}
  .email-footer{{background:#000;padding:20px 40px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;}}
  .footer-brand{{color:#6B6B6B;font-size:12px;}}
  .footer-brand strong{{color:#C4C4C4;}}
  .footer-right{{font-size:10px;color:#444;letter-spacing:.06em;font-family:monospace;text-align:right;line-height:1.8;}}
</style>
</head>
<body>
<div style="padding:0 16px">
<div class="email-wrap">
  <div class="email-header">
    <div style="position:absolute;inset:0;overflow:hidden;z-index:1">
      <div class="d-shape d1"></div><div class="d-shape d2"></div><div class="d-shape d3"></div>
    </div>
    <div class="hdr-top">
      <div class="gp-badge"><div class="gp-circle">G·P</div><div class="gp-name">Grupo Petersen <span>Canales Digitales</span></div></div>
      <div class="hdr-pill">Release Note</div>
    </div>
    <div class="hdr-body">
      <div class="hdr-label">HBI Plataforma · {sprint_name}</div>
      <div class="hdr-title">Novedades de la versión</div>
      <div class="hdr-subtitle">Actualización de avances al {generated}</div>
      <div class="hdr-meta">
        <div class="hdr-meta-item"><div class="hdr-meta-val">{len(real_goals)}</div><div class="hdr-meta-lbl">Objetivos</div></div>
        <div class="hdr-meta-div"></div>
        <div class="hdr-meta-item"><div class="hdr-meta-val">{len(all_stories)}</div><div class="hdr-meta-lbl">Historias</div></div>
        <div class="hdr-meta-div"></div>
        <div class="hdr-meta-item"><div class="hdr-meta-val">{pcts["listo"]}%</div><div class="hdr-meta-lbl">Completado</div></div>
        <div class="hdr-meta-div"></div>
        <div class="hdr-meta-item"><div class="hdr-meta-val">{days["end"]}</div><div class="hdr-meta-lbl">Fin Sprint</div></div>
      </div>
    </div>
  </div>
  <div class="email-body">
    <div class="sec">
      <div class="sec-eyebrow">Estado actual</div>
      <div class="sec-title">Progreso del Sprint</div>
      <div class="sec-desc">El equipo de plataforma avanza con {total} ítems en el sprint activo.</div>
      <div class="stats-row">
        <div class="stat-block"><div class="stat-val green">{counts["listo"]}</div><div class="stat-lbl">Listo</div></div>
        <div class="stat-block"><div class="stat-val blue">{counts["testing"]}</div><div class="stat-lbl">En Testing</div></div>
        <div class="stat-block"><div class="stat-val amber">{counts["progress"]}</div><div class="stat-lbl">En Progreso</div></div>
        <div class="stat-block"><div class="stat-val" style="color:#6B6B6B">{counts["todo"]}</div><div class="stat-lbl">Por Hacer</div></div>
      </div>
      <div style="background:#F5F5F5;border-radius:10px;padding:14px">
        <div style="display:flex;justify-content:space-between;margin-bottom:8px"><span style="font-size:12px;font-weight:700">Completado incl. testing</span><span style="font-size:12px;font-weight:800;color:#1A8A4A">{pcts["done_plus_test"]}%</span></div>
        <div class="ep-track"><div class="ep-fill ep-done"></div><div class="ep-fill ep-test"></div><div class="ep-fill ep-prog"></div><div class="ep-fill ep-todo"></div></div>
      </div>
      <div class="timeline-banner">
        <div class="tl-item"><div class="tl-val">{days["start"]}</div><div class="tl-lbl">Inicio</div></div>
        <div class="tl-div"></div>
        <div class="tl-item tl-highlight"><div class="tl-val">Hoy</div><div class="tl-lbl">Día {days["elapsed"]}/{days["total"]}</div></div>
        <div class="tl-div"></div>
        <div class="tl-item"><div class="tl-val">{days["remaining"]}</div><div class="tl-lbl">Días restantes</div></div>
        <div class="tl-div"></div>
        <div class="tl-item"><div class="tl-val">{days["end"]}</div><div class="tl-lbl">Fin Sprint</div></div>
      </div>
    </div>
    <div class="sec" style="border-top:1px solid #F0F0F0">
      <div class="sec-eyebrow">Compromisos</div>
      <div class="sec-title">Objetivos del Sprint</div>
      <div class="goals-grid">{goals_html}</div>
    </div>
    <div class="sec" style="border-top:1px solid #F0F0F0">
      <div class="sec-eyebrow">En desarrollo</div>
      <div class="sec-title">Funcionalidades</div>
      <div class="feature-list">{features_html}</div>
    </div>
    <div class="cta-section">
      <div class="cta-box">
        <div><div class="cta-title">Ver la pizarra del sprint</div><div class="cta-sub">Detalle en tiempo real en Jira</div></div>
        <a class="cta-btn" href="https://jira.gbsj.com.ar/secure/RapidBoard.jspa?rapidView=650">Abrir en Jira →</a>
      </div>
    </div>
  </div>
  <div class="email-footer">
    <div class="footer-brand"><strong>Grupo Petersen · Canales Digitales</strong><br>HBI Plataforma · Comunicación interna</div>
    <div class="footer-right">Generado: {generated}<br>No responder este correo</div>
  </div>
</div>
</div>
</body>
</html>"""


# ─── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Genera dashboards de sprint HBI Plataforma")
    parser.add_argument("--jira-url",   default=os.getenv("JIRA_URL",   "https://jira.gbsj.com.ar"))
    parser.add_argument("--jira-user",  default=os.getenv("JIRA_USER",  ""))
    parser.add_argument("--jira-token", default=os.getenv("JIRA_TOKEN", ""))
    parser.add_argument("--board",      default=int(os.getenv("JIRA_BOARD_ID", "650")), type=int)
    parser.add_argument("--sprint-id",  default=None, type=int, help="ID de sprint específico (default: sprint activo)")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    if not args.jira_user or not args.jira_token:
        print("[ERROR] Necesitás --jira-user y --jira-token (o JIRA_USER y JIRA_TOKEN)", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Conectando a {args.jira_url}…")
    jira = JiraClient(args.jira_url, args.jira_user, args.jira_token)

    # Get sprint
    if args.sprint_id:
        sprint = jira.get(f"/rest/agile/1.0/sprint/{args.sprint_id}")
    else:
        sprint = jira.get_active_sprint(args.board)
        if not sprint:
            print("[ERROR] No se encontró un sprint activo", file=sys.stderr)
            sys.exit(1)

    print(f"[INFO] Sprint: {sprint['name']} (id={sprint['id']})")

    # Get issues
    issues = jira.get_sprint_issues(sprint["id"])
    print(f"[INFO] Issues obtenidos: {len(issues)}")

    # Process
    data = process_issues(issues)
    days = sprint_days(sprint)

    print(f"[INFO] Estado: {data['counts']}")

    # Generate HTML
    dashboard_html = generate_dashboard(sprint, data, days)
    release_html   = generate_release_note(sprint, data, days)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ── Archivos raíz (siempre apuntan al sprint más reciente) ──
    (out / "sprint-dashboard.html").write_text(dashboard_html, encoding="utf-8")
    (out / "release-note-email.html").write_text(release_html, encoding="utf-8")
    print(f"[OK] Latest dashboard    → sprint-dashboard.html")
    print(f"[OK] Latest release note → release-note-email.html")

    # ── Archivos versionados por sprint: sprints/{id}/ ──
    sprint_dir = out / "sprints" / str(sprint["id"])
    sprint_dir.mkdir(parents=True, exist_ok=True)
    (sprint_dir / "dashboard.html").write_text(dashboard_html, encoding="utf-8")
    (sprint_dir / "release-note.html").write_text(release_html, encoding="utf-8")
    print(f"[OK] Versioned dashboard  → sprints/{sprint['id']}/dashboard.html")
    print(f"[OK] Versioned note       → sprints/{sprint['id']}/release-note.html")


if __name__ == "__main__":
    main()

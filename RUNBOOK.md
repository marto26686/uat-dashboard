# Runbook — Sprint Dashboard & Release Note
**HBI Plataforma · Grupo Petersen · Canales Digitales**

---

## Acceso a los dashboards

| URL | Descripción |
|-----|-------------|
| `https://marto26686.github.io/uat-dashboard/` | Landing page |
| `https://marto26686.github.io/uat-dashboard/sprint-dashboard.html` | Dashboard del sprint activo |
| `https://marto26686.github.io/uat-dashboard/release-note-email.html` | Release note del sprint activo |
| `https://marto26686.github.io/uat-dashboard/sprints/{ID}/dashboard.html` | Versión archivada de un sprint específico |
| `https://marto26686.github.io/uat-dashboard/sprints/{ID}/release-note.html` | Release note archivada |

**Contraseña de acceso:** `HBI@Petersen25`

---

## Flujo normal — sprint en curso

### Actualización automática (sin hacer nada)
El workflow corre automáticamente **lunes y jueves a las 9:00am ART**.
Genera los HTML con los datos más frescos de Jira y los sube al repo.

### Actualización manual (cuando querés verlo actualizado ahora)
1. Ir a: `https://github.com/marto26686/uat-dashboard/actions/workflows/generate-release.yml`
2. Clic en **Run workflow**
3. Dejar el campo "ID del sprint" vacío (usa el activo)
4. Board ID: `650` (ya viene por defecto)
5. Clic en **Run workflow** (verde)
6. Esperar ~30 segundos
7. Refrescar la URL del dashboard

---

## Cambio de sprint — qué hacer cuando arranca uno nuevo

### Paso 1 — Pedirle a Claude que genere el enrichment
Mandá este mensaje en Cowork:

> "Genera un nuevo enrichments/**{ID_DEL_NUEVO_SPRINT}**.json"

Claude va a:
1. Conectarse a Jira y traer todos los issues del sprint
2. Generar títulos comerciales y descripciones para cada historia y spike
3. Commitear el JSON al repo automáticamente

**¿Cómo saber el ID del nuevo sprint?**
Ir a `https://jira.gbsj.com.ar/secure/RapidBoard.jspa?rapidView=650`
y fijarse el número `&sprint=XXXX` en la URL.

### Paso 2 — Correr el workflow con el nuevo sprint
1. Ir a Actions → Run workflow
2. En "ID del sprint" poner el ID nuevo (ej: `1958`)
3. Ejecutar

A partir de ahí el workflow automático del lunes/jueves ya usa el sprint activo solo.

---

## Agregar créditos a la API de Anthropic (para enrichment 100% automático)

Cuando haya saldo en la cuenta, el enrichment se genera solo en cada run sin necesidad de pedirle a Claude.

1. Ir a `https://console.anthropic.com/settings/billing`
2. Agregar créditos (mínimo $5 — alcanzan para ~500 runs con Haiku)
3. Listo — el workflow detecta la `ANTHROPIC_API_KEY` y genera las descripciones automáticamente

> Sin créditos el sistema sigue funcionando con el JSON estático del sprint.
> La prioridad es: **JSON estático → Claude API → títulos originales de Jira**

---

## Archivos del repo

```
uat-dashboard/
├── index.html                          # Landing page
├── sprint-dashboard.html               # Dashboard latest (sobreescrito en cada run)
├── release-note-email.html             # Release note latest (sobreescrito en cada run)
├── sprints/
│   ├── 1697/
│   │   ├── dashboard.html              # Versión archivada sprint 1697
│   │   └── release-note.html
│   └── 1957/
│       ├── dashboard.html              # Versión archivada sprint 1957
│       └── release-note.html
├── enrichments/
│   ├── 1697.json                       # Títulos y descripciones curadas sprint 1697
│   └── 1957.json                       # Títulos y descripciones curadas sprint 1957
└── scripts/
    └── generate_dashboards.py          # Script generador (no tocar)
```

---

## Secrets configurados en GitHub

| Secret | Descripción |
|--------|-------------|
| `JIRA_URL` | `https://jira.gbsj.com.ar` |
| `JIRA_USER` | Usuario de Jira |
| `JIRA_TOKEN` | Contraseña/token de Jira |
| `ANTHROPIC_API_KEY` | API key de Anthropic (opcional, para auto-enrichment) |

Para editar: `https://github.com/marto26686/uat-dashboard/settings/secrets/actions`

---

## Renovar el token de GitHub (expira el 26/04/2026)

1. Ir a `https://github.com/settings/tokens`
2. Generar nuevo token con scopes: `repo` + `workflow`
3. Actualizar la remote URL del repo si trabajás localmente:
   ```
   git remote set-url origin https://TOKEN@github.com/marto26686/uat-dashboard.git
   ```

---

## Troubleshooting

| Problema | Causa probable | Solución |
|----------|---------------|----------|
| Workflow falla con "connect error" | Jira no accesible o credenciales vencidas | Verificar `JIRA_USER` y `JIRA_TOKEN` en secrets |
| Dashboard sin descripciones | No hay enrichment para ese sprint ID | Pedir a Claude que genere `enrichments/{ID}.json` |
| Sin sección "Análisis técnicos" | No hay Spikes en el sprint | Normal — la sección aparece solo si hay spikes |
| GitHub Pages muestra versión vieja | Caché del browser | Ctrl+F5 o esperar ~2 minutos |
| Token expirado | PAT vencido | Renovar en github.com/settings/tokens |

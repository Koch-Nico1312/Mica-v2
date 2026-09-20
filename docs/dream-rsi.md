# Dream-RSI in MICA — Recursive Self-Improvement über die eigene Verbesserungspipeline

> Umsetzung des Papers **„Dream-RSI: Recursive Self-Improvement through
> Evolving Worlds"** (Zheng et al., Sept 2026, Google/UMD —
> https://github.com/zhengkid/Dream-RSI / https://dream-rsi.com) auf MICA.
> Der offizielle Upstream-Code war bei der Umsetzung noch nicht veröffentlicht
> (nur Paper + Projektseite); dieses Modul implementiert das Konzept direkt und
> bleibt schnittstellenkompatibel, damit später der Original-Code als
> Replay-Backend angedockt werden kann.

## Die drei Schritte des Loops

| Paper | MICA-Umsetzung |
|---|---|
| ❶ Online-Discovery protokolliert Traces | `ImprovementRegistry` emittiert Lifecycle-Events (propose/evaluate/shadow_failed/promote/rollback) → `DreamTreeStore` (`dream.sqlite3`) als Entdeckungsbaum |
| ❷ Historie wird zum Replay-Simulator | `ReplaySimulator` traversiert aufgezeichnete Bäume alternativ (frühere Stopp-Schwellen, andere Reihenfolgen) — **rein lesend**, ohne Ausführung |
| ③ Policies im Traum bewerten, beste zurückspielen | `DreamRSIEngine.run_cycle()` vergleicht Baseline + Grid- + LLM-Kandidaten, schlägt den Gewinner als `config`-Artefakt `dream-exploration-config` vor; die aktive Policy steuert danach `maybe_propose_improvement` („redeploy online") |

## Sicherheit (unverändert)

- Dreaming ist **read-only** (SQLite-Lesezugriffe). Es wird niemals Code aus dem
  Baum oder aus Policies ausgeführt.
- Policy-Kandidaten sind `config`-Artefakte mit winziger Allowlist
  (`propose_after_occurrences`, `max_open_candidates`, `retry_backoff_factor`,
  `kind_preference`, `stop_on_shadow_failure`) und laufen durch die vollständige
  Registry-Validierung (Protected-Keys, JSON-Only).
- **Promotion bleibt manuell**: `POST /v1/improvements/{id}/promote` mit
  parametergebundener Freigabe über die `PolicyEngine`. Kein Auto-Promote.
- Der gesamte Loop ist standardmäßig **aus** (`MICA_DREAM_RSI_ENABLED=1` zum
  Aktivieren), respektiert den Not-Aus und ist budgetiert (max. 5 Kandidaten,
  Pool ≥ 3 Bäume).

## Bausteine

| Modul | Aufgabe |
|---|---|
| `mica_core/services/common/dream_rsi.py` | Baum-Speicher, Replay-Simulator, Policy-Schema, Engine |
| `mica_core/services/common/laya_scorer.py` | Optionales lokales Scoring mit [Laya](https://github.com/NandhaKishorM/laya) (~33 ms, CPU, deutsch); deterministischer Heuristik-Fallback |
| `mica_core/services/common/learning.py` | Recherche/Monitoring jetzt mit [Scrapling](https://github.com/D4Vinci/Scrapling) (adaptive Elemente überleben Web-Redesigns); HTTPX-Fallback bleibt, alle Guards (HTTPS-only, Allowlist, Public-IP, Größenlimit) unverändert |
| `mica_core/services/scheduler.py` | geplante Aktion `dream.rsi` (budgetiert) |
| `actions/cua_driver.py` | [Cua Driver](https://github.com/trycua/cua): native Windows-Apps ohne Fokus-Klau; `close` hinter dem Bestätigungs-Gate; Fallback-Hinweis auf bestehende Steuerung |
| `actions/seo_agent.py` | [OpenSEO](https://github.com/every-app/open-seo) via MCP: Key im OS-Keyring, Tagesbudget für bezahlte DataForSEO-Requests |

## Env-Flags

| Flag | Standard | Wirkung |
|---|---|---|
| `MICA_DREAM_RSI_ENABLED` | `0` | Meta-Loop aktivieren |
| `MICA_DREAM_DB` | `/data/dream.sqlite3` | Pfad des Entdeckungsbaums |
| `MICA_LAYA_ENABLED` | `0` | Laya-Scorer aktivieren (needs `pip install laya`) |
| `MICA_SCRAPLING_ENABLED` | `1` wenn installiert | adaptive Suche/Fetch; `0` erzwingt alte Parser |
| `MICA_CUA_ENABLED` | `0` | native App-Steuerung (Driver muss installiert sein) |
| `MICA_OPENSEO_ENABLED` | `0` | SEO-Workflows aktivieren |
| `MICA_OPENSEO_URL` | – | self-hosted oder `https://openseo.so` |
| `MICA_OPENSEO_DAILY_BUDGET` | `20` | bezahlte Requests/Tag |

## API

- `GET /v1/dream/state` — Pool-Größe, aktive Policy, letzte Zyklen
- `GET /v1/dream/policies` — aufgezeichnete Replay-Auswertungen
- `POST /v1/dream/cycle` — ein begrenzter Zyklus auf Abruf (liest nur;
  einziger Schreibvorgang ist der validierte Policy-Vorschlag)
- Scheduler: Aktion `dream.rsi` planbar (Budget 3 Kandidaten, Pool ≥ 3)

## Bewusst nicht umgesetzt

- Auto-Promotion (bleibt aus, wie im Rest des Systems).
- Paper-Domänen (GPU-Kernel, Mathe-Optimierung) — Domäne hier ist MICA selbst
  (Prompt-, Config-, Skill-, Runbook-Artefakte).
- Cua-VM-/Fleet-Teile (macOS) und OpenShorts/Dify (nach Abwägung verworfen).

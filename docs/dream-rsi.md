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
| ❷ Historie wird zum Replay-Simulator | `ReplaySimulator` traversiert aufgezeichnete Bäume alternativ — **rein lesend**, ohne Ausführung. Jeder Policy-Regler beantwortet eine kontrafaktische Frage an die Historie: `propose_after_occurrences` (Wiederholungen werden erst ab der Schwelle geöffnet; Erst-Vorkommen immer), `max_open_candidates` (Cap auf noch offene Kandidaten), `retry_backoff_factor` (`backoff ** retry_index` auf die Vorschlags-Kosten), `kind_preference` (Gewichtung des Validierungs-Rewards nach Artefakt-Kind: 1.0/0.75/0.5), `stop_on_shadow_failure` (Abbruch nach dem ersten Fehlschlag spart die aufgezeichneten Retries). Die Antwort enthält zusätzlich `admitted`/`skipped`. Nur die *Reihenfolge* der Kandidaten ist bedeutsam, nie der Absolutwert |
| ③ Policies im Traum bewerten, beste zurückspielen | `DreamRSIEngine.run_cycle()` vergleicht Baseline + Grid- + LLM-Kandidaten und schlägt den besten Kandidaten als `config`-Artefakt `dream-exploration-config` vor; die aktive Policy steuert danach `maybe_propose_improvement` („redeploy online") |

Ein Kandidat wird **nur vorgeschlagen, wenn der Replay ihn strikt besser bewertet
als die aktive Policy** (`score > baseline_score`). Ist der bestbewertete Kandidat
die Baseline selbst, oder sortiert der Laya-Scorer einen schlechteren Kandidaten
nach vorn, endet der Zyklus mit `status=completed`, `proposal_id=""` und einer
begründenden `reason` — der Loop kann sich so nicht selbst verschlechtern.

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
| `backend/services/common/dream_rsi.py` | Baum-Speicher, Replay-Simulator, Policy-Schema, Engine |
| `backend/services/common/laya_scorer.py` | Optionales lokales Scoring mit [Laya](https://github.com/NandhaKishorM/laya) (~33 ms, CPU, deutsch); deterministischer Heuristik-Fallback |
| `backend/services/common/learning.py` | Recherche/Monitoring jetzt mit [Scrapling](https://github.com/D4Vinci/Scrapling) (adaptive Elemente überleben Web-Redesigns). Der Scrapling-Fetch löst Redirects **selbst** auf und validiert jeden Hop über `SafeWebClient.validate_url` — Scraplings Default `follow_redirects="safe"` lehnt nur private/internale Ziele ab, nicht Allowlist-Abweichungen — und prüft Rohgröße (`MAX_BYTES`), Content-Type und die tatsächlich bedienende URL, bevor Text zurückgegeben wird. HTTPX-Fallback bleibt unverändert |
| `backend/services/scheduler.py` | geplante Aktion `dream.rsi` (budgetiert) |
| `desktop/actions/cua_driver.py` | [Cua Driver](https://github.com/trycua/cua): native Windows-Apps ohne Fokus-Klau; `close` hinter dem Bestätigungs-Gate; Fallback-Hinweis auf bestehende Steuerung |
| `desktop/actions/seo_agent.py` | [OpenSEO](https://github.com/every-app/open-seo) via MCP: Key im OS-Keyring, Tagesbudget für bezahlte DataForSEO-Requests. Der Endpoint muss HTTPS sein (Klartext-HTTP nur für einen Loopback-MCP-Server), und die Budget-DB liegt fest in der Installationswurzel (`<Wurzel>/connectors.sqlite3`, überschreibbar per `MICA_OPENSEO_DB`) statt relativ zum aktuellen Arbeitsverzeichnis |

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
  einziger Schreibvorgang ist der validierte Policy-Vorschlag). Braucht und
  akzeptiert **keine** Freigabe: das Vorschlagen ist billig und umkehrbar,
  freigabepflichtig ist erst die Promotion. Die Antwort enthält deshalb keine
  `approval_id`
- Scheduler: Aktion `dream.rsi` planbar (Budget 3 Kandidaten, Pool ≥ 3)

## Bewusst nicht umgesetzt

- Auto-Promotion (bleibt aus, wie im Rest des Systems).
- Paper-Domänen (GPU-Kernel, Mathe-Optimierung) — Domäne hier ist MICA selbst
  (Prompt-, Config-, Skill-, Runbook-Artefakte).
- Cua-VM-/Fleet-Teile (macOS) und OpenShorts/Dify (nach Abwägung verworfen).

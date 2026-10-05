/* Explicit local learning and review of generated candidates. */
(() => {
  const el = id => document.getElementById(id);
  const labels = {missing_tool:'Werkzeug fehlt',broken_tool:'Werkzeug fehlerhaft',missing_permission:'Freigabe oder Rechte fehlen',temporary_outage:'Vorübergehender Ausfall'};
  const approvals=new Map();
  async function api(path, method='GET', body) {
    const key=path+JSON.stringify(body);
    const requestBody=body!==undefined&&approvals.has(key)?{...body,approval_id:approvals.get(key)}:body;
    const response = await fetch(path, {method, headers:{'content-type':'application/json','x-mica-approval-intent':'confirm'}, ...(requestBody===undefined?{}:{body:JSON.stringify(requestBody)})});
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 403 && data.detail?.approval_id) {
        approvals.set(key,data.detail.approval_id);
        await loadApprovals();
        throw Error('Die Prüfung wartet auf Freigabe. Unter „Freigaben“ bestätigen und danach erneut starten.');
      }
      throw Error(response.status===401?'Zuerst die lokalen Freigaben entsperren.':typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));
    }
    approvals.delete(key);
    return data;
  }
  function node(tag, text, className) {
    const item=document.createElement(tag); item.textContent=text;
    if(className)item.className=className;
    return item;
  }
  function button(label, callback) {
    const item=node('button',label,'button');
    item.onclick=async()=>{item.disabled=true;try{await callback();await loadEvolution();}catch(error){el('evolution-status').textContent=error.message;}finally{item.disabled=false;}};
    return item;
  }
  async function loadEvolution() {
    try {
      const [preferences,gaps,suites,jobs]=await Promise.all([
        api('/v1/evolution/preferences'),api('/v1/evolution/gaps'),api('/v1/evolution/suites'),api('/v1/evolution/workshop')
      ]);
      const rules=el('evolution-rules');rules.replaceChildren();
      if(!preferences.preferences.length)rules.textContent='Noch keine bestätigten Vorlieben.';
      for(const rule of preferences.preferences){
        const card=node('article','','card');card.append(node('b',rule.preference_key),node('p',rule.value),node('span',`${rule.scope} · Quelle: ${rule.source}`,'meta'));
        card.append(button('Korrigieren',async()=>{const value=prompt('Neue bestätigte Vorliebe',rule.value);if(value===null)return;await api('/v1/evolution/preferences','POST',{key:rule.preference_key,value,scope:rule.scope,source:'Bestätigung in MICA'});}));
        card.append(button('Vergessen',async()=>{if(confirm('Diese Vorliebe einschließlich ihrer früheren Fassungen löschen?'))await api(`/v1/evolution/preferences/${rule.id}`,'DELETE');}));rules.append(card);
      }
      const gapList=el('evolution-gaps'),gapSelect=el('workshop-gap'),suiteSelect=el('workshop-suite');
      gapList.replaceChildren();gapSelect.replaceChildren();suiteSelect.replaceChildren();
      gapSelect.append(new Option('Lücke auswählen',''));
      if(!gaps.gaps.length)gapList.textContent='Noch keine erfassten Fähigkeitslücken.';
      for(const gap of gaps.gaps){gapList.append(node('article',`${labels[gap.category]}: ${gap.action} · ${gap.occurrences} Beobachtungen`,'card'));if(['missing_tool','broken_tool'].includes(gap.category))gapSelect.append(new Option(`${gap.action} · ${labels[gap.category]}`,gap.id));}
      suiteSelect.append(new Option('Prüfaufgabe auswählen',''));
      for(const suite of suites.suites)suiteSelect.append(new Option(`${suite.goal} · ${suite.cases.length} Beispiele`,suite.id));
      const list=el('workshop-jobs');list.replaceChildren();
      if(!jobs.jobs.length)list.textContent='Noch keine Entwicklungskandidaten.';
      for(const job of jobs.jobs){
        const improvement=job.improvement;if(!improvement)continue;
        const card=node('article','','card');card.append(node('b',improvement.name),node('span',`${job.intent==='repair'?'Reparatur':'Neue Fähigkeit'} · ${improvement.status}`,'meta'));
        const diff=document.createElement('details');diff.append(node('summary','Änderung ansehen'),node('pre',job.patch));card.append(diff);
        const report=node('pre',job.quality?JSON.stringify(job.quality,null,2):'Noch kein Qualitätsvergleich durchgeführt.');card.append(report);
        card.append(button('Isoliert prüfen',async()=>{const result=await api(`/v1/improvements/${improvement.id}/evaluate`,'POST',{auto_promote:false});report.textContent=JSON.stringify(result.quality||result,null,2);el('evolution-status').textContent=result.validated?'Prüfung bestanden. Übernahme bleibt ein eigener Schritt.':'Prüfung nicht bestanden; aktive Version bleibt erhalten.';}));
        if(improvement.status==='validated')card.append(button('Geprüfte Version übernehmen',async()=>{const result=await api(`/v1/improvements/${improvement.id}/promote`,'POST',{});el('evolution-status').textContent=result.promoted?'Version übernommen.':'Übernahme abgelehnt; Baseline oder Zustand erneut prüfen.';}));
        if(improvement.status==='active'){
          card.append(button('Fähigkeit nutzen',async()=>{const input=prompt('Eingabedaten für die Fähigkeit als JSON');if(input===null)return;const payload=JSON.parse(input);const result=await api('/v1/tasks/execute','POST',{action:'improvement.invoke',params:{improvement_id:improvement.id,payload},dry_run:false});el('evolution-status').textContent=JSON.stringify(result.output||result);}));
          card.append(button('Vorherige Version wiederherstellen',async()=>{await api(`/v1/improvements/${encodeURIComponent(improvement.name)}/rollback`,'POST',{});}));
          card.append(button('Reparatur vorbereiten',async()=>{el('workshop-name').value=improvement.name;el('workshop-intent').value='repair';el('evolution-status').textContent='Eine unabhängige Prüfaufgabe wählen und Kandidat erstellen. Die aktuelle Version bleibt aktiv.';}));
        }
        const observations=job.observations;card.append(node('p',`Bestätigte Alltagsbeobachtungen: vorher ${observations.baseline.tasks}, Kandidat ${observations.candidate.tasks}.`,'meta'));
        if(observations.candidate.tasks)card.append(node('p',`Kandidat: ${observations.candidate.correct} erfolgreiche Aufgaben · ${observations.candidate.errors} Fehler · ${observations.candidate.user_corrections} Nutzerkorrekturen · ${observations.candidate.provider_cost} EUR`));
        card.append(button('Alltagsergebnis bestätigen',async()=>{
          const task=prompt('Kennung der tatsächlich beobachteten Aufgabe');if(task===null)return;
          const duration=prompt('Gemessene Dauer in Millisekunden');if(duration===null)return;
          const cost=prompt('Tatsächliche Providerkosten in EUR; bei lokalem Lauf 0');if(cost===null)return;
          const corrections=prompt('Wie viele Nutzerkorrekturen waren nötig?');if(corrections===null)return;
          const success=confirm('War das Ergebnis richtig? OK = ja, Abbrechen = nein.');
          await api(`/v1/evolution/revisions/${improvement.id}/observations`,'POST',{task_id:task,success,duration_ms:Number(duration),provider_cost:Number(cost),user_corrections:Number(corrections),source:'Bestätigtes Alltagsergebnis in MICA'});
        }));
        list.append(card);
      }
    }catch(error){el('evolution-status').textContent=error.message;}
  }
  document.querySelector('[data-view="evolution"]').addEventListener('click',loadEvolution);
  el('preference-save').onclick=async()=>{try{await api('/v1/evolution/preferences','POST',{key:el('preference-key').value,value:el('preference-value').value,scope:el('preference-scope').value,source:'Ausdrückliche Nutzerkorrektur in MICA'});el('evolution-status').textContent='Vorliebe bestätigt und gespeichert.';await loadEvolution();}catch(error){el('evolution-status').textContent=error.message;}};
  el('suite-save').onclick=async()=>{try{const cases=JSON.parse(el('suite-cases').value);await api('/v1/evolution/suites','POST',{goal:el('suite-goal').value,cases,source:'Unabhängig bestätigte Nutzerbeispiele'});el('evolution-status').textContent='Prüfaufgabe gespeichert. Ihre Soll-Ergebnisse werden der Code-Erzeugung nicht mitgegeben.';await loadEvolution();}catch(error){el('evolution-status').textContent=error.message;}};
  el('workshop-create').onclick=async()=>{const item=el('workshop-create');item.disabled=true;try{const result=await api('/v1/evolution/workshop','POST',{name:el('workshop-name').value,suite_id:el('workshop-suite').value,gap_id:el('workshop-gap').value||null,intent:el('workshop-intent').value});el('evolution-status').textContent=`Kandidat erstellt: ${result.proposal.id}. Jetzt isoliert prüfen.`;await loadEvolution();}catch(error){el('evolution-status').textContent=error.message;}finally{item.disabled=false;}};
})();

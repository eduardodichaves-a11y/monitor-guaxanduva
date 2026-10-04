#!/usr/bin/env python3
"""#175-R2 — replay histórico por intervalos/limites, fail-closed.
Não interpola agregados. Distingue contexto causal, restrições e score validável.
Sem pesos históricos calibrados, risco numérico permanece N/D; a incerteza é explicitada.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime,timedelta
SRC=Path("eventos_historicos_guaxanduva.json")
OUT=Path("replay_EH001_175_R2.json")
def dt(s): return datetime.fromisoformat(s)
def timeline(a,b,step):
 t=a
 while t<=b:
  yield t; t+=timedelta(minutes=step)
def main():
 base=json.loads(SRC.read_text(encoding="utf-8")); ev=next(x for x in base["eventos"] if x["id"]=="EH-001")
 a,b=dt(ev["replay"]["inicio"]),dt(ev["replay"]["fim"]); step=int(ev["replay"]["passo_min"])
 frames=[]
 for t in timeline(a,b,step):
  causal=[]; future=[]
  for e in ev.get("evidencias_entrada",[]):
   if e.get("usar_no_replay_em_tempo_real") is True and dt(e["disponivel_em"])<=t: causal.append(e["id"])
   else: future.append(e["id"])
  contexts=[e["id"] for e in ev.get("evidencias_entrada",[]) if e["id"] in causal and e.get("peso_no_score") is False]
  frames.append({"t":t.isoformat(),"evidencias_causais_disponiveis":causal,"contextos_sem_peso_calibrado":contexts,"evidencias_bloqueadas":future,"risco_min":None,"risco_estimado":None,"risco_max":None,"classe":"N/D","confianca_score":0.0,"status":"INTERVALO_NAO_IDENTIFICAVEL_SEM_SERIE_E_PESOS_CALIBRADOS","nota":"R2 preserva as restrições agregadas sem inventar distribuição sub-horária nem peso de maré/alerta."})
 out={"versao":"#175-R2","evento":ev["id"],"modo":"REPLAY_CEGO_CAUSAL_POR_INTERVALOS","operacional":False,"calibracao":False,"passo_min":step,"metodo":{"regra":"Somente dados disponíveis em t entram como causais.","intervalos":"Limites numéricos só são emitidos quando identificáveis pelas evidências e pelo motor congelado; caso contrário ficam N/D.","anti_invento":True},"restricoes_reconstrucao":ev.get("restricoes_reconstrucao",[]),"frames":frames,"gabarito":{"isolado_do_motor":True,"impactos":ev.get("gabarito_impactos",[])},"diagnostico":{"frames_total":len(frames),"frames_com_contexto_causal":sum(bool(f["evidencias_causais_disponiveis"]) for f in frames),"frames_com_intervalo_numerico":sum(f["risco_min"] is not None and f["risco_max"] is not None for f in frames),"resultado":"R2_CAUSAL_COM_RESTRICOES_MAS_INTERVALO_DE_RISCO_AINDA_NAO_IDENTIFICAVEL","motivo":"Há contexto causal pré-evento e, a partir de 01:42, agregado contemporâneo de 139 mm/2h; faltam série temporal e calibração para converter isso legitimamente em limites 0–100.","proximo_gate":"Recuperar série temporal histórica e/ou definir um motor de envelopes fisicamente justificável e validá-lo fora do EH-001."}}
 OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(out["diagnostico"],ensure_ascii=False))
if __name__=="__main__": main()

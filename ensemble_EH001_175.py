#!/usr/bin/env python3
from pathlib import Path
import json, random, math, statistics
C=json.loads(Path("config_ensemble_EH001_175.json").read_text(encoding="utf-8"))
rng=random.Random(C["ensemble"]["seed"])
N=C["ensemble"]["n"]

# 12 bins de 10 min entre 22:00 e 00:00, soma obrigatória 139 mm.
# Não são observações: são trajetórias latentes condicionadas ao acumulado conhecido.
# Priors Dirichlet com concentração variável permitem chuva mais uniforme ou pulsada.
accepted=[]
for _ in range(N):
    alpha=10**rng.uniform(-0.35,0.55)
    xs=[rng.gammavariate(alpha,1.0) for _ in range(12)]
    s=sum(xs)
    rain=[139.0*x/s for x in xs]
    # Restrição física informada pelo decreto: existência de 1 h de 90 mm.
    # Como a estação do 90 mm não é necessariamente a mesma do acumulado 139 mm,
    # tratamos 90 como evidência suave, não igualdade rígida.
    one=[sum(rain[i:i+6]) for i in range(7)]
    peak=max(one)
    w=math.exp(-0.5*((peak-90.0)/18.0)**2)
    # Marcador de início ~21:30±30: favorece, sem exigir, atividade já no começo de 22-00.
    early=sum(rain[:3])
    w*=0.35+0.65*(1-math.exp(-early/15.0))
    if rng.random()<w:
        # proxies de pressão pluviométrica, NÃO probabilidade física calibrada.
        cum=0.0; first20=first40=first65=None
        for i,x in enumerate(rain):
            cum+=x
            # índice conservador: combinação de acumulado e intensidade recente.
            recent=sum(rain[max(0,i-5):i+1])
            score=min(100.0, 100*(0.55*cum/139.0 + 0.45*recent/90.0))
            minute=22*60+(i+1)*10
            if first20 is None and score>=20: first20=minute
            if first40 is None and score>=40: first40=minute
            if first65 is None and score>=65: first65=minute
        accepted.append((rain,peak,first20,first40,first65))
def fmt(m):
    if m is None:return None
    m%=1440
    return f"{m//60:02d}:{m%60:02d}"
def q(vals,p):
    vals=sorted(v for v in vals if v is not None)
    if not vals:return None
    return vals[round((len(vals)-1)*p)]
out={
 "id":"EH001_ENSEMBLE_175_RESULT",
 "natureza":"HINDCAST_PROBABILISTICO_EXPERIMENTAL_NAO_OPERACIONAL",
 "n_propostas":N,"n_aceitas":len(accepted),
 "restricao_dura":{"P_22_00_mm":139.0},
 "evidencia_suave":{"P1h_90mm":"usada com incerteza inter-estacao; nao imposta como igualdade"},
 "alerta_proxy":{
   "definicao":"Indice exploratorio de pressao pluviometrica; NAO e o motor hidraulico completo #175.",
   "limiares_exploratorios":[20,40,65],
   "horario_primeiro_cruzamento":{
      str(t):{"p05":fmt(q([a[2+(t//25)] for a in accepted],.05)),
              "p50":fmt(q([a[2+(t//25)] for a in accepted],.50)),
              "p95":fmt(q([a[2+(t//25)] for a in accepted],.95))}
      for t in (20,40,65)
   }
 },
 "impactos":{"00:30":"VALIDACAO_EXTERNA_NAO_ENTRA_NO_INDICE","00:50":"VALIDACAO_EXTERNA_NAO_ENTRA_NO_INDICE"},
 "mare":{"uso":"CONTEXTO_DE_FASE","observada":False,"altura_absoluta_m":None},
 "limitacao":"Os horarios sao do proxy pluviometrico condicionado, nao lead time validado do #175. Substituir pelo motor completo quando sua funcao historica causal estiver parametrizada.",
 "uso_operacional":False
}
Path(C["saida"]).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(out["alerta_proxy"],ensure_ascii=False,indent=2))

#!/usr/bin/env python3
from pathlib import Path
import json
d=json.loads(Path("validacao_final_175_R3.json").read_text(encoding="utf-8"))
c=d["casos"]; m=d["matriz_confusao_executada"]; met=d["metricas"]; f=d["congelamento"]
checks={
 "CINCO_CASOS_ROTULADOS":len(c)==5,
 "SO_EH001_EXECUTADO":sum(x["predicao"] is not None for x in c.values())==1 and c["EH-001"]["predicao"]=="POSITIVO",
 "EH002_NAO_CONTADO":c["EH-002"]["predicao"] is None,
 "EH003_NAO_CONTADO":c["EH-003"]["predicao"] is None,
 "CONTROLES_NAO_CONTADOS":c["CN-001"]["predicao"] is None and c["CN-002"]["predicao"] is None,
 "MATRIZ_N1":m=={"TP":1,"FN":0,"TN":0,"FP":0,"N_testado":1},
 "METRICAS_NAO_GLOBALIZADAS":met["publicaveis_como_desempenho_global"] is False,
 "PESOS_NAO_MEXIDOS":f["pesos_175_A1_alterados"] is False,
 "NAO_OPERACIONAL":f["liberar_operacional"] is False,
 "HORIZONTES_BLOQUEADOS":f["liberar_horizontes_30_60_120"] is False,
}
for k,v in checks.items(): print(k,"OK" if v else "FALHOU")
assert all(checks.values())
print("AUDITORIA FINAL #175 R3: APROVADO 10/10")

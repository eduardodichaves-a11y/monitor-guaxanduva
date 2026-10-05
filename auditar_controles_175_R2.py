#!/usr/bin/env python3
from pathlib import Path
import json
d=json.loads(Path("controles_negativos_175_R2.json").read_text(encoding="utf-8"))
c={x["id"]:x for x in d["controles"]}
checks={
"DOIS_CONTROLES":set(c)=={"CN-001","CN-002"},
"CN001_56MM_12H":c["CN-001"]["chuva"]=={"acumulado_mm":56.0,"janela_h":12},
"CN001_ZERO_OCORRENCIAS":c["CN-001"]["resultado_ate_corte"]["ocorrencias_registradas"]==0,
"CN002_20MM_12H":c["CN-002"]["chuva"]=={"acumulado_mm":20.0,"janela_h":12},
"CN002_ZERO_OCORRENCIAS":c["CN-002"]["resultado_ate_corte"]["ocorrencias_registradas"]==0,
"RECORTE_TEMPORAL_EXPLICITO":"ATÉ" in d["criterio"],
"40MM_1H_NAO_FOI_FALSE_NEGATIVE":d["comparador_excluido"]["data"]=="2023-02-23" and "NÃO é negativo" in d["comparador_excluido"]["motivo"],
"SEM_RECALIBRACAO":"Nenhum controle altera" in d["regra"],
}
for k,v in checks.items(): print(k,"OK" if v else "FALHOU")
assert all(checks.values())
print("AUDITORIA CONTROLES #175 R2: APROVADO 8/8")

#!/usr/bin/env python3
from pathlib import Path
import json
d=json.loads(Path("eventos_validacao_positiva_175_R1.json").read_text(encoding="utf-8"))
ev={x["id"]:x for x in d["eventos"]}
checks={
"DOIS_EVENTOS":set(ev)=={"EH-002","EH-003"},
"AMBOS_POSITIVOS":all(x["rotulo"]==1 and x["impacto"]["alagamentos"] for x in ev.values()),
"EH002_30MM_30MIN":ev["EH-002"]["chuva"]["mm"]==30 and ev["EH-002"]["chuva"]["duracao_min"]==30,
"EH002_SEM_HORA_INVENTADA":ev["EH-002"]["chuva"]["janela_exata"] is None,
"EH003_COMASA":"Comasa" in ev["EH-003"]["impacto"]["bairros"],
"EH003_79_5MM":ev["EH-003"]["chuva"]["media_municipal_24h_mm"]==79.5,
"EH003_VILANOVA":ev["EH-003"]["chuva"]["epagri_vila_nova_24h_mm"]==89,
"SEM_RECALIBRACAO":"Não recalibrar" in d["regra_validacao"],
}
for k,v in checks.items(): print(k,"OK" if v else "FALHOU")
assert all(checks.values())
print("AUDITORIA VALIDAÇÃO POSITIVA #175 R1: APROVADO 8/8")

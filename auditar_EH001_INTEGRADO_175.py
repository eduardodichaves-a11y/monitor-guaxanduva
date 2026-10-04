#!/usr/bin/env python3
from pathlib import Path
import json
p=Path("replay_EH001_INTEGRADO_175.json")
d=json.loads(p.read_text(encoding="utf-8"))
checks={
"NAO_INVENTA_ALERTA": d["resultado_atual"]["alerta_reconstituido"] is None,
"NAO_INVENTA_LEAD_TIME": d["resultado_atual"]["lead_time_min"] is None,
"MARE_NAO_OBSERVADA": d["evidencias_causais"][2]["observada"] is False,
"MARE_SEM_ALTURA_FALSA": d["evidencias_causais"][2]["altura_m"] is None,
"P139_COM_DISPONIBILIDADE": bool(d["evidencias_causais"][0]["disponibilidade_publica_aprox"]),
"IMPACTOS_SEPARADOS": len(d["evidencias_de_validacao"])>=2,
"REPLAY_NAO_OPERACIONAL": d["natureza"]=="REPLAY_HISTORICO_CAUSAL_NAO_OPERACIONAL"
}
for k,v in checks.items(): print(k, "OK" if v else "FALHOU")
assert all(checks.values())
print(f"AUDITORIA EH-001 INTEGRADO: APROVADO {sum(checks.values())}/{len(checks)}")

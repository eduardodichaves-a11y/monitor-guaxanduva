#!/usr/bin/env python3
from pathlib import Path
import json
d=json.loads(Path("envelope_causal_EH001_175.json").read_text(encoding="utf-8"))
r=d["resultado"]
checks={
 "SEM_LEAD_TIME_INVENTADO": r["lead_time_min"] is None,
 "SEM_HORA_ALERTA_INVENTADA": r["hora_alerta"] is None,
 "SEM_PROBABILIDADE_FALSA": r["probabilidade_alerta"] is None,
 "P1H_PRESERVADO": d["restricoes"]["P1h_cemaden_iririu_mm"]==90.0,
 "P2H_EPAGRI_PRESERVADO": d["restricoes"]["P2h_epagri_mm"]==120.0,
 "P2H_CONTEMPORANEO_SEPARADO": d["restricoes"]["P2h_contemporaneo_22_00_mm"]==139.0,
 "METODO_NAO_PROBABILISTICO": d["metodo"].startswith("ENVELOPE_DE_RESTRICOES")
}
for k,v in checks.items(): print(k, "OK" if v else "FALHOU")
assert all(checks.values())
print("AUDITORIA ENVELOPE CAUSAL EH-001: APROVADO 7/7")

#!/usr/bin/env python3
from pathlib import Path
import json, subprocess, sys
subprocess.run([sys.executable,"ensemble_EH001_175.py"],check=True)
d=json.loads(Path("ensemble_EH001_175.json").read_text(encoding="utf-8"))
checks={
"HA_AMOSTRAS":d["n_aceitas"]>100,
"139_PRESERVADO":d["restricao_dura"]["P_22_00_mm"]==139.0,
"90_NAO_FORCADO_COMO_MESMA_ESTACAO":"nao imposta" in d["evidencia_suave"]["P1h_90mm"],
"IMPACTO_FORA_DO_INDICE":all("VALIDACAO" in v for v in d["impactos"].values()),
"MARE_NAO_OBSERVADA":d["mare"]["observada"] is False,
"SEM_ALTURA_FALSA":d["mare"]["altura_absoluta_m"] is None,
"NAO_OPERACIONAL":d["uso_operacional"] is False,
"PROXY_DECLARADO":"NAO e o motor hidraulico completo #175" in d["alerta_proxy"]["definicao"],
}
for k,v in checks.items(): print(k,"OK" if v else "FALHOU")
assert all(checks.values())
print("AUDITORIA EH-001 ENSEMBLE: APROVADO 8/8")

#!/usr/bin/env python3
from pathlib import Path
import json, subprocess, sys
subprocess.run([sys.executable,"motor_integrado_EH001_175.py"],check=True)
d=json.loads(Path("resultado_motor_integrado_EH001_175.json").read_text(encoding="utf-8"))
m=d["motor"]; r=d["resultado"]
checks={
 "PESOS_A1":abs(sum(m["pesos_nominais_175_A1"].values())-1)<1e-9,
 "SEM_DRENAGEM_FALSA":m["segmentos_usados_numericamente_neste_hindcast"]==0,
 "119_DECLARADOS_SEM_SIMULACAO":m["segmentos_drenagem_modelados"]==119,
 "FATORES_AUSENTES_DECLARADOS":len(m["fatores_indisponiveis"])==4,
 "ALERTA_EXISTE":r["hora_alerta_p50"] is not None,
 "LEAD_TIME_MODELADO_EXISTE":r["lead_time_vs_00h30_min"]["p50"] is not None,
 "NAO_OPERACIONAL":d["uso_operacional"] is False,
 "LIMITACAO_EXPLICITA":"MODELADO/CONDICIONAL" in d["interpretacao"],
}
for k,v in checks.items(): print(k,"OK" if v else "FALHOU")
assert all(checks.values())
print("AUDITORIA MOTOR INTEGRADO EH-001 #175: APROVADO 8/8")

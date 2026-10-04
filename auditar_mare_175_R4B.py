#!/usr/bin/env python3
from pathlib import Path
import json, subprocess, sys
subprocess.run([sys.executable,"reconstruir_mare_175_R4A.py"],check=True)
subprocess.run([sys.executable,"diagnosticar_mare_175_R4B.py"],check=True)
d=json.loads(Path("diagnostico_mare_EH001_175_R4B.json").read_text(encoding="utf-8"))
checks=[
 ("73_FRAMES",d["frames_total"]==73),
 ("SEM_OBSERVACAO_FALSA",d["mare_observada"]=="N/D"),
 ("SEM_ALTURA_FALSA",d["mare_reconstruida_absoluta"]=="N/D"),
 ("SEM_USO_FUSION",d["uso_no_fusion_175"] is False),
 ("SEM_ALTERAR_PESOS",d["pesos_175_alterados"] is False),
 ("GATE_IDENTIFICABILIDADE",d["status"] in ("NAO_IDENTIFICAVEL_SEM_ANCORA","IDENTIFICAVEL")),
]
# With current R4A unconstrained phases, scientific expectation is non-identifiable.
checks.append(("R4A_CORRETAMENTE_BLOQUEADO",d["status"]=="NAO_IDENTIFICAVEL_SEM_ANCORA"))
r={"versao":"#175-R4B-AUDIT","status":"APROVADO" if all(v for _,v in checks) else "FALHA",
   "checks":[{"codigo":k,"ok":v} for k,v in checks],
   "resumo":{"aprovados":sum(v for _,v in checks),"total":len(checks)}}
Path("auditoria_mare_175_R4B.json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(r["resumo"]|{"status":r["status"]},ensure_ascii=False))
raise SystemExit(0 if r["status"]=="APROVADO" else 1)

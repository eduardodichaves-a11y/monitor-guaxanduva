#!/usr/bin/env python3
import json, subprocess, sys
from pathlib import Path
subprocess.run([sys.executable,"reconstruir_mare_175_R4A.py"],check=True)
d=json.loads(Path("mare_reconstruida_EH001_175_R4A.json").read_text(encoding="utf-8"))
checks=[
 ("73_FRAMES",d["frames_total"]==73),
 ("NAO_OPERACIONAL",d["status"]=="LABORATORIO_NAO_OPERACIONAL"),
 ("OBSERVADA_ND",d["mare_observada"]=="N/D"),
 ("ABSOLUTA_ND",d["altura_absoluta"]=="N/D"),
 ("MET_NAO_ZERO",d["meteorologia"].startswith("N/D")),
 ("TODOS_FRAMES_SEM_ALTURA",all(x["mare_observada_m"] is None and x["mare_reconstruida_absoluta_m"] is None for x in d["frames"])),
 ("FASE_LIMITADA",all(-1<=x["fase_relativa"]["p05"]<=1 and -1<=x["fase_relativa"]["p50"]<=1 and -1<=x["fase_relativa"]["p95"]<=1 for x in d["frames"])),
]
r={"versao":"#175-R4A-AUDIT","status":"APROVADO" if all(v for _,v in checks) else "FALHA",
   "checks":[{"codigo":k,"ok":v} for k,v in checks],"resumo":{"aprovados":sum(v for _,v in checks),"total":len(checks)}}
Path("auditoria_mare_175_R4A.json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(r["resumo"]|{"status":r["status"]},ensure_ascii=False))
raise SystemExit(0 if r["status"]=="APROVADO" else 1)

#!/usr/bin/env python3
from pathlib import Path
import json,subprocess,sys
subprocess.run([sys.executable,"diagnosticar_JIC_175_R4C.py"],check=True)
d=json.loads(Path("diagnostico_JIC_175_R4C.json").read_text(encoding="utf-8"))
checks=[
 ("FATOR_FORMA_COERENTE",0.28 <= d["fator_forma_calculado"] <= 0.30),
 ("PREDOMINANCIA_SEMIDIURNA",d["predominancia"] in ("SEMIDIURNA","MISTA_PREDOMINANTEMENTE_SEMIDIURNA")),
 ("M2_PRINCIPAL",d["constituinte_principal_por_amplitude"]=="M2"),
 ("SEM_ALTURA_2020_FABRICADA",d["mare_EH001_m"] is None),
 ("RETROVISAO_BLOQUEADA",d["retroprojecao_2020_liberada"] is False),
]
r={"versao":"#175-R4C-AUDIT","status":"APROVADO" if all(v for _,v in checks) else "FALHA",
   "checks":[{"codigo":k,"ok":v} for k,v in checks],
   "resumo":{"aprovados":sum(v for _,v in checks),"total":len(checks)}}
Path("auditoria_JIC_175_R4C.json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(r["resumo"]|{"status":r["status"]},ensure_ascii=False))
raise SystemExit(0 if r["status"]=="APROVADO" else 1)

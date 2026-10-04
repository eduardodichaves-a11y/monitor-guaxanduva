#!/usr/bin/env python3
from pathlib import Path
import json
d=json.loads(Path("mare_reconstruida_EH001_FINAL.json").read_text(encoding="utf-8"))
assert len(d["analogos"])==3
assert d["mare_observada_evento_m"] is None
assert d["altura_absoluta_evento_m"] is None
assert d["quadros"][0]["fase_estimativa"] in ("DESCENDO_APOS_PREAMAR","PROXIMA_PREAMAR_OU_INICIO_DESCIDA")
assert d["quadros"][-1]["fase_estimativa"]=="SUBINDO_APOS_BAIXA"
print("AUDITORIA FINAL DA FASE DE MARÉ: APROVADO 5/5")

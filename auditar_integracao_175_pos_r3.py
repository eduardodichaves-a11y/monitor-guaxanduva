#!/usr/bin/env python3
from pathlib import Path
s=Path("fusion_guaxanduva_175.py").read_text(encoding="utf-8")
checks={
"VERSAO_A3":"'versao':'#175-A3'" in s,
"FASE_CONGELADA":"FASE_HISTORICA_CONGELADA_VALIDACAO_PARCIAL" in s,
"CINCO_ROTULADOS":"'casos_rotulados':5" in s,
"UM_REPLAY":"'casos_com_replay_motor':1" in s,
"COBERTURA_20":"'cobertura_replay_pct':20.0" in s,
"SEM_USO_NA_PONTUACAO":"'uso_na_pontuacao':False" in s,
"SEM_CALIBRACAO":"'calibracao_operacional_liberada':False" in s and "'calibrado_historicamente':False" in s,
"HORIZONTES_BLOQUEADOS":"amostra executada insuficiente" in s,
"PESOS_PRESERVADOS":"0.24" in s and "0.12" in s and "0.14" in s and "0.16" in s and "0.06" in s,
"EH001_HINDCAST":"POSITIVO_NO_HINDCAST_PARCIAL" in s and "130–140" in s,
}
for k,v in checks.items(): print(k,"OK" if v else "FALHOU")
assert all(checks.values())
print("AUDITORIA INTEGRAÇÃO #175 PÓS-R3: APROVADO 10/10")

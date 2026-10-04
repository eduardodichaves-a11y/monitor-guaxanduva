#!/usr/bin/env python3
from pathlib import Path
import json
d=json.loads(Path("constantes_JIC_175_R4C.json").read_text(encoding="utf-8"))
c=d["fonte_constituintes"]["principais_publicados"]
F=(c["K1"]["amplitude_m"]+c["O1"]["amplitude_m"])/(c["M2"]["amplitude_m"]+c["S2"]["amplitude_m"])
semidi=c["M2"]["amplitude_m"]+c["S2"]["amplitude_m"]
diur=c["K1"]["amplitude_m"]+c["O1"]["amplitude_m"]
out={
 "versao":"#175-R4C-DIAGNOSTICO",
 "status":"CONSTANTES_LOCAIS_RECUPERADAS_RETROVISAO_2020_BLOQUEADA",
 "fator_forma_calculado":round(F,4),
 "soma_amplitudes_semidiurnas_m":round(semidi,4),
 "soma_amplitudes_diurnas_m":round(diur,4),
 "predominancia":"SEMIDIURNA" if F<0.25 else "MISTA_PREDOMINANTEMENTE_SEMIDIURNA" if F<1.5 else "OUTRA",
 "constituinte_principal_por_amplitude":max(c,key=lambda k:c[k]["amplitude_m"]),
 "mare_EH001_m":None,
 "retroprojecao_2020_liberada":False,
 "explicacao":"As constantes publicadas são evidência local forte e substituem amplitudes exploratórias do R4A como referência científica. Porém não autorizam, sozinhas, uma curva absoluta para 2020 sem convenção de fase/época e correções astronômicas reproduzíveis."
}
Path("diagnostico_JIC_175_R4C.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(out,ensure_ascii=False))

#!/usr/bin/env python3
"""#175-R3D — auditoria automatizada fail-closed do replay EH-001.

Valida R2 + R3C sem alterar o Monitor operacional.
Falha (exit 1) se detectar vazamento temporal, score de risco inventado,
mistura proibida das evidências independentes ou inconsistência matemática.
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
from datetime import datetime

R2_BASE=Path("eventos_historicos_guaxanduva.json")
R2_REPLAY=Path("replay_historico_175.py")
R2_OUT=Path("replay_EH001_175_R2.json")
R3_CFG=Path("restricoes_EH001_175_R3.json")
R3_ENGINE=Path("envelope_hidrometeorologico_175.py")
R3_OUT=Path("envelope_EH001_175_R3.json")
OUT=Path("auditoria_EH001_175_R3D.json")

def load(p): return json.loads(p.read_text(encoding="utf-8"))
def check(cond, code, detail, checks):
    checks.append({"codigo":code,"ok":bool(cond),"detalhe":detail})
    return bool(cond)

def main():
    required=[R2_BASE,R2_REPLAY,R3_CFG,R3_ENGINE]
    missing=[str(p) for p in required if not p.exists()]
    if missing:
        OUT.write_text(json.dumps({"versao":"#175-R3D","status":"FALHA","motivo":"ARQUIVOS_AUSENTES","arquivos":missing},ensure_ascii=False,indent=2),encoding="utf-8")
        print("FALHA: arquivos ausentes:", ", ".join(missing)); return 1

    # Regenerate outputs from the committed engines; never trust stale result files.
    subprocess.run([sys.executable,str(R2_REPLAY)],check=True)
    subprocess.run([sys.executable,str(R3_ENGINE)],check=True)
    base,r2,cfg,r3=map(load,[R2_BASE,R2_OUT,R3_CFG,R3_OUT])
    checks=[]

    ev=next(x for x in base["eventos"] if x["id"]=="EH-001")
    e006=next(x for x in ev["evidencias_entrada"] if x["id"]=="E006")
    available=datetime.fromisoformat(e006["disponivel_em"])

    # 1. No future leakage of the 139 mm/2h observation.
    before=[f for f in r2["frames"] if datetime.fromisoformat(f["t"]) < available]
    after=[f for f in r2["frames"] if datetime.fromisoformat(f["t"]) >= available]
    check(all("E006" not in f["evidencias_causais_disponiveis"] for f in before),
          "R2_SEM_VAZAMENTO_E006","E006 não pode ser causal antes de 01:42.",checks)
    check(all("E006" in f["evidencias_causais_disponiveis"] for f in after),
          "R2_E006_APOS_DISPONIBILIDADE","E006 entra apenas nos frames >= 01:42.",checks)

    # 2. R2 remains score-free.
    check(all(f["risco_min"] is None and f["risco_estimado"] is None and f["risco_max"] is None for f in r2["frames"]),
          "R2_SEM_SCORE_INVENTADO","Todos os limites de risco continuam N/D.",checks)

    # 3. R3C generator uses only C001=139 mm/2h.
    rg=cfg["restricao_geradora"]
    check(rg["id"]=="C001" and float(rg["valor_mm"])==139.0 and rg["inicio"].endswith("22:00:00-03:00") and rg["fim"].endswith("00:00:00-03:00"),
          "R3C_RESTRICAO_GERADORA_C001","Gerador usa somente 139 mm entre 22h e 00h.",checks)

    # 4. Independent evidence is explicitly not fused.
    independent=" ".join(r3.get("evidencias_independentes_nao_fundidas",[]))
    check("90 mm/1h" in independent and "120 mm/2h" in independent and "169 mm/6h" in independent,
          "R3C_FONTES_NAO_FUNDIDAS","90/1h, 120/2h e ~169/6h permanecem evidências independentes.",checks)

    # 5. No invented 21h–03h hard window for 169 mm.
    evidencias=cfg.get("evidencias_de_validacao_nao_impostas_ao_gerador",[])
    c003=next((x for x in evidencias if x.get("id")=="C003"),None)
    check(c003 is not None and "posição temporal exata" in c003.get("motivo","") and
          "inicio" not in c003 and "fim" not in c003,
          "R3C_SEM_JANELA_169_INVENTADA","C003 (~169 mm/6h) não recebe início/fim inventados.",checks)

    # 6. Mathematical bound and A1-equivalent saturation.
    m=r3["resultado_analitico"]["maximo_movel_1h_mm"]
    f=r3["resultado_analitico"]["fator_chuva_observada_equivalente_A1"]
    check(abs(float(m["limite_inferior"])-69.5)<1e-9 and abs(float(m["limite_superior"])-139.0)<1e-9,
          "R3C_LIMITES_ANALITICOS","P1h máximo admissível limitado a [69,5; 139] mm.",checks)
    check(float(f["limite_inferior"])==100.0 and float(f["limite_superior"])==100.0,
          "R3C_FATOR_CHUVA_A1_SATURADO","Equivalência retrospectiva do fator chuva A1 = 100/100.",checks)

    # 7. Full risk must stay unavailable.
    check(r3["causalidade"]["risco_total_175"]=="N/D",
          "R3C_RISCO_TOTAL_BLOQUEADO","Risco total #175 continua N/D.",checks)
    check(r3["status"]=="LABORATORIO_NAO_OPERACIONAL",
          "R3C_NAO_OPERACIONAL","R3C permanece laboratório não operacional.",checks)

    passed=all(c["ok"] for c in checks)
    report={
      "versao":"#175-R3D",
      "evento":"EH-001",
      "status":"APROVADO" if passed else "FALHA",
      "operacional":False,
      "altera_pesos_175":False,
      "altera_index":False,
      "checks":checks,
      "resumo":{"aprovados":sum(c["ok"] for c in checks),"total":len(checks)},
      "proximo_gate":"R4 somente após ampliar forçantes/eventos históricos; R3D não libera calibração."
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report["resumo"]|{"status":report["status"]},ensure_ascii=False))
    return 0 if passed else 1

if __name__=="__main__":
    raise SystemExit(main())

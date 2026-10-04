#!/usr/bin/env python3
"""#175-R1 — replay histórico cego/causal do Monitor Guaxanduva.

Princípios:
- nunca usa evidência publicada no futuro em um instante histórico t;
- gabaritos de impacto ficam isolados do cálculo;
- dado ausente permanece ausente;
- agregados retrospectivos não são artificialmente interpolados;
- esta versão R1 audita disponibilidade e vazamento temporal; não calibra pesos.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timedelta

SRC = Path("eventos_historicos_guaxanduva.json")
OUT = Path("replay_EH001_175_R1.json")


def dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def timeline(start: datetime, end: datetime, step_min: int):
    t = start
    while t <= end:
        yield t
        t += timedelta(minutes=step_min)


def main():
    base = json.loads(SRC.read_text(encoding="utf-8"))
    ev = next(e for e in base["eventos"] if e["id"] == "EH-001")
    start, end = dt(ev["replay"]["inicio"]), dt(ev["replay"]["fim"])
    step = int(ev["replay"]["passo_min"])
    entradas = ev.get("evidencias_entrada", [])

    frames = []
    for t in timeline(start, end, step):
        disponiveis = []
        bloqueadas_futuro = []
        for e in entradas:
            av = dt(e["disponivel_em"])
            if e.get("usar_no_replay_em_tempo_real") is True and av <= t:
                disponiveis.append(e["id"])
            else:
                bloqueadas_futuro.append(e["id"])

        # R1 não inventa score: sem séries causais recuperadas, o #175 histórico fica N/D.
        frames.append({
            "t": t.isoformat(),
            "evidencias_causais_disponiveis": disponiveis,
            "evidencias_bloqueadas_por_causalidade": bloqueadas_futuro,
            "indice_175": None,
            "classe": "N/D",
            "confianca": 0.0 if not disponiveis else None,
            "status": "DADOS_HISTORICOS_CAUSAIS_INSUFICIENTES" if not disponiveis else "PRONTO_PARA_MOTOR",
            "nota": "Nenhum agregado retrospectivo foi distribuído artificialmente no tempo."
        })

    out = {
        "versao": "#175-R1",
        "evento": ev["id"],
        "modo": "REPLAY_CEGO_CAUSAL",
        "operacional": False,
        "calibracao": False,
        "passo_min": step,
        "frames": frames,
        "gabarito": {
            "isolado_do_motor": True,
            "quantidade_impactos_documentados_na_base": len(ev.get("gabarito_impactos", [])),
            "impactos": ev.get("gabarito_impactos", [])
        },
        "diagnostico": {
            "frames_total": len(frames),
            "frames_com_score": sum(f["indice_175"] is not None for f in frames),
            "resultado": "REPLAY_ESTRUTURAL_VALIDO_MAS_SEM_SCORE",
            "motivo": "Ainda faltam séries históricas que estivessem disponíveis causalmente durante o evento. O R1 bloqueou corretamente dados retrospectivos publicados depois.",
            "proximo_gate": "Recuperar séries temporais históricas (chuva/maré/radar) com timestamp e regra de disponibilidade; só então executar o motor congelado #175-A1."
        }
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["diagnostico"], ensure_ascii=False))


if __name__ == "__main__":
    main()

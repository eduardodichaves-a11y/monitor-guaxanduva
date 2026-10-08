#!/usr/bin/env python3
"""#217 - Arquiva somente quadros RadarSC com ecos e RGB; sem inferir chuva."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

def processar(dados, historico, dias=31, max_quadros=500):
    radar = dados.get("radar") or {}
    geo = (radar.get("classificacao_qualitativa_local_130") or {}).get("geolocalizacao_ecos_211") or {}
    grupos = geo.get("agrupamentos") or []
    quadro = radar.get("horario_ultimo_quadro")
    agora = datetime.now(timezone.utc)
    anteriores = historico.get("quadros") or []
    validos = []
    for item in anteriores:
        try:
            t = datetime.fromisoformat(item["quadro_radar"].replace("Z", "+00:00"))
            if t.tzinfo and agora - timedelta(days=dias) <= t <= agora + timedelta(hours=2):
                validos.append(item)
        except (ValueError, TypeError, KeyError):
            continue
    novo = False
    if quadro and grupos:
        try:
            instante = datetime.fromisoformat(quadro.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            instante = None
        if instante is not None and instante.tzinfo and instante <= agora + timedelta(hours=2):
            if not any(item.get("quadro_radar") == quadro for item in validos):
                ecos = []
                for i, g in enumerate(grupos, 1):
                    centro = g.get("centroide") or {}
                    ecos.append({
                        "numero": i, "pixels": g.get("pixels"),
                        "latitude": centro.get("latitude"), "longitude": centro.get("longitude"),
                        "cores_rgb": g.get("cores_rgb") or [],
                        "familias_cromaticas": g.get("familias_cromaticas") or [],
                        "rgb_disponivel": bool(g.get("cores_rgb")),
                        "validacao_meteorologica": "NAO_REALIZADA",
                    })
                validos.append({"quadro_radar": quadro, "gerado_em_fonte": dados.get("gerado_em"),
                                "origem": "dados.json/radar/classificacao_qualitativa_local_130/geolocalizacao_ecos_211",
                                "ecos": ecos})
                novo = True
    validos.sort(key=lambda x: x["quadro_radar"])
    return {"versao": "#217", "politica": "Somente ecos presentes na fonte; RGB ausente nao e inventado; nao comprova chuva.",
            "retencao_dias": dias, "quadros": validos[-max_quadros:]}, novo

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dados", default="dados.json")
    parser.add_argument("--historico", default="historico_ecos_rgb_217.json")
    parser.add_argument("--dias", type=int, default=31)
    args = parser.parse_args()
    dados = json.loads(Path(args.dados).read_text(encoding="utf-8"))
    destino = Path(args.historico)
    antigo = json.loads(destino.read_text(encoding="utf-8")) if destino.exists() else {}
    resultado, novo = processar(dados, antigo, args.dias)
    conteudo = json.dumps(resultado, ensure_ascii=False, indent=2) + "\n"
    if not destino.exists() or destino.read_text(encoding="utf-8") != conteudo:
        destino.write_text(conteudo, encoding="utf-8")
    print("Quadro novo arquivado:", novo, "| total quadros:", len(resultado["quadros"]))

if __name__ == "__main__":
    main()

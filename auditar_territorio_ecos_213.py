#!/usr/bin/env python3
"""#213: identifica territorio provavel dos ecos; nao valida chuva nem altera dados.json."""
import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "MonitorGuaxanduva-AuditoriaGeografica/213 (GitHub eduardodichaves-a11y/monitor-guaxanduva)"

def consulta_osm(lat, lon, tentativas=2):
    parametros = urllib.parse.urlencode({
        "lat": lat, "lon": lon, "format": "jsonv2",
        "addressdetails": 1, "zoom": 12, "accept-language": "pt-BR"
    })
    url = "https://nominatim.openstreetmap.org/reverse?" + parametros
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for tentativa in range(tentativas):
        try:
            with urllib.request.urlopen(req, timeout=18) as resposta:
                dado = json.load(resposta)
            endereco = dado.get("address") or {}
            return {
                "fonte": "OpenStreetMap Nominatim (referencia cartografica, nao limite oficial IBGE)",
                "nome_local": dado.get("display_name"),
                "municipio_provavel": endereco.get("city") or endereco.get("town") or endereco.get("municipality") or endereco.get("village"),
                "estado": endereco.get("state"),
                "tipo_osm": dado.get("type"),
                "categoria_osm": dado.get("category"),
                "observacao": "Geocodificacao aproximada do centroide; costa, agua e ecos extensos exigem sobreposicao a poligonos oficiais."
            }
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as erro:
            if tentativa + 1 == tentativas:
                return {"fonte": "OpenStreetMap Nominatim", "erro": str(erro), "municipio_provavel": None}
            time.sleep(2)

def auditar(relatorio, consultar=True):
    saida = {
        "versao": "#213", "quadro_radar": relatorio.get("quadro_radar"),
        "aviso": "Territorio e estimativa cartografica, nao confirmacao de chuva. Estacoes existentes nao sao inventario regional completo.",
        "agrupamentos": []
    }
    for i, grupo in enumerate(relatorio.get("agrupamentos") or []):
        lat, lon = grupo.get("latitude"), grupo.get("longitude")
        item = {"numero": grupo.get("numero", i+1), "latitude": lat, "longitude": lon,
                "pixels": grupo.get("pixels"), "validacao_chuva": "NAO REALIZADA",
                "estacoes_proximas_cadastradas": grupo.get("estacoes_proximas_cadastradas", [])}
        if lat is None or lon is None:
            item["territorio"] = {"erro": "Centroide ausente"}
        elif consultar:
            item["territorio"] = consulta_osm(float(lat), float(lon))
            time.sleep(1.1)  # respeitar limite de consultas do serviço
        else:
            item["territorio"] = {"status": "Consulta desativada"}
        saida["agrupamentos"].append(item)
    return saida

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("relatorio", nargs="?", default="auditoria_geografica_212.json")
    ap.add_argument("--saida", default="auditoria_territorial_213.json")
    ap.add_argument("--sem-rede", action="store_true")
    args = ap.parse_args()
    entrada = json.loads(Path(args.relatorio).read_text(encoding="utf-8"))
    resultado = auditar(entrada, consultar=not args.sem_rede)
    Path(args.saida).write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Agrupamentos analisados:", len(resultado["agrupamentos"]))
    print("Relatorio:", args.saida)

if __name__ == "__main__":
    main()

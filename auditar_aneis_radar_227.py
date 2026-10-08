#!/usr/bin/env python3
"""#227: auditoria cromatica por aneis a partir de dados.json.
Nao infere trajetoria, ETA, chuva medida nem intensidade meteorologica.
Uso: python auditar_aneis_radar_227.py [dados.json] [saida.json]
"""
import json
import sys
from pathlib import Path

FAMILIAS = ('azul_ciano', 'verde', 'amarelo', 'laranja', 'vermelho')
RAIOS = (2, 5, 10, 25, 50)

def processar(dados):
    radar = dados.get('radar') or {}
    classificacao = radar.get('classificacao_qualitativa_local_130') or {}
    por_raio = classificacao.get('por_raio') or {}
    resultado = []
    anterior = {familia: 0 for familia in FAMILIAS}
    limite_anterior = 0
    for limite in RAIOS:
        entrada = por_raio.get(str(limite)) or por_raio.get(limite) or {}
        # Formatos do projeto: lista de familias com contagens ou dicionario.
        familias = entrada.get('familias_cor') or entrada.get('familias_cromaticas') or entrada.get('familias') or []
        if isinstance(familias, list):
            atual = {x.get('familia'): int(x.get('pixels', 0)) for x in familias if isinstance(x, dict)}
        elif isinstance(familias, dict):
            atual = {k: int(v.get('pixels', 0) if isinstance(v, dict) else v) for k, v in familias.items()}
        else:
            atual = {}
        if not atual and entrada:
            raise ValueError(f'Formato de familias desconhecido no raio {limite}: {list(entrada)}')
        anel = {}
        for familia in FAMILIAS:
            contagem = atual.get(familia, 0)
            diferenca = contagem - anterior[familia]
            if diferenca < 0:
                raise ValueError(f'Contagem cumulativa inconsistente: {familia} em {limite} km')
            anel[familia] = diferenca
            anterior[familia] = contagem
        resultado.append({'de_km': limite_anterior, 'ate_km': limite, 'pixels_por_familia': anel,
                          'total_pixels': sum(anel.values())})
        limite_anterior = limite
    return {'versao': '#227-aneis', 'quadro_radar': radar.get('horario_ultimo_quadro'),
            'status_radar': radar.get('status'), 'aneis': resultado,
            'interpretacao': 'Distribuicao cromatica espacial, nao classificacao validada de chuva.',
            'trajetoria_confirmada': False, 'eta_liberado': False,
            'limites': ['Sem direcao individual por pixel', 'Sem identidade temporal dos ecos',
                        'Nao usar centroide de componente que cobre 0-50 km como posicao da chuva']}

def main():
    entrada = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('dados.json')
    saida = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('auditoria_aneis_radar_227.json')
    resultado = processar(json.loads(entrada.read_text(encoding='utf-8')))
    saida.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Quadro:', resultado['quadro_radar'])
    for anel in resultado['aneis']:
        print(f"{anel['de_km']}-{anel['ate_km']} km: {anel['pixels_por_familia']}")
    print('Saida:', saida)

if __name__ == '__main__':
    main()

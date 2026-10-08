#!/usr/bin/env python3
"""Teste isolado #217: dados sinteticos nunca sao gravados no repositorio."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from registrar_ecos_rgb_217 import processar


def amostra(agora, agrupamentos):
    return {
        "gerado_em": agora.isoformat(),
        "radar": {
            "horario_ultimo_quadro": agora.isoformat(),
            "classificacao_qualitativa_local_130": {
                "geolocalizacao_ecos_211": {"agrupamentos": agrupamentos}
            },
        },
    }


class TestesHistorico217(unittest.TestCase):
    def setUp(self):
        self.agora = datetime.now(timezone.utc).replace(microsecond=0)
        self.eco = {
            "pixels": 3,
            "centroide": {"latitude": -26.215039, "longitude": -48.614186},
            "cores_rgb": [{"rgb": [0, 90, 255], "pixels": 2},
                          {"rgb": [55, 145, 255], "pixels": 1}],
            "familias_cromaticas": [{"familia": "azul", "pixels": 3}],
        }

    def test_rgb_e_metadados(self):
        dados = amostra(self.agora, [self.eco])
        with tempfile.TemporaryDirectory(prefix="teste_217_") as pasta:
            destino = Path(pasta) / "historico_sintetico.json"
            resultado, novo = processar(dados, {})
            destino.write_text(json.dumps(resultado), encoding="utf-8")
            salvo = json.loads(destino.read_text(encoding="utf-8"))
        self.assertTrue(novo)
        self.assertEqual(len(salvo["quadros"]), 1)
        quadro = salvo["quadros"][0]
        self.assertEqual(quadro["quadro_radar"], self.agora.isoformat())
        self.assertEqual(quadro["gerado_em_fonte"], self.agora.isoformat())
        eco = quadro["ecos"][0]
        self.assertEqual(eco["pixels"], 3)
        self.assertEqual(eco["latitude"], -26.215039)
        self.assertEqual(eco["longitude"], -48.614186)
        self.assertEqual(eco["cores_rgb"], self.eco["cores_rgb"])
        self.assertEqual(eco["familias_cromaticas"], self.eco["familias_cromaticas"])
        self.assertEqual(eco["validacao_meteorologica"], "NAO_REALIZADA")

    def test_nao_duplica_mesmo_quadro(self):
        dados = amostra(self.agora, [self.eco])
        primeiro, novo = processar(dados, {})
        segundo, duplicou = processar(dados, primeiro)
        self.assertTrue(novo)
        self.assertFalse(duplicou)
        self.assertEqual(len(segundo["quadros"]), 1)

    def test_sem_ecos_preserva_historico(self):
        primeiro, _ = processar(amostra(self.agora, [self.eco]), {})
        vazio, novo = processar(amostra(self.agora + timedelta(minutes=15), []), primeiro)
        self.assertFalse(novo)
        self.assertEqual(vazio["quadros"], primeiro["quadros"])

    def test_rgb_ausente_nao_e_inventado(self):
        eco = copy.deepcopy(self.eco)
        eco.pop("cores_rgb")
        resultado, novo = processar(amostra(self.agora, [eco]), {})
        self.assertTrue(novo)
        self.assertEqual(resultado["quadros"][0]["ecos"][0]["cores_rgb"], [])
        self.assertFalse(resultado["quadros"][0]["ecos"][0]["rgb_disponivel"])

    def test_quadro_antigo_fora_retencao(self):
        velho = (self.agora - timedelta(days=35)).isoformat()
        anterior = {"quadros": [{"quadro_radar": velho, "ecos": []}]}
        resultado, novo = processar(amostra(self.agora, []), anterior)
        self.assertFalse(novo)
        self.assertEqual(resultado["quadros"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

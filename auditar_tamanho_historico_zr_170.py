#!/usr/bin/env python3
"""Guard rail de tamanho para historico_zr_170.json.

Não trunca dados automaticamente. Se o arquivo ultrapassar o limite definido,
a publicação científica falha explicitamente para evitar crescimento silencioso.
"""
import json
from pathlib import Path

POLITICA = Path("politica_retencao_zr_170.json")

def main():
    cfg = json.loads(POLITICA.read_text(encoding="utf-8"))
    alvo = Path(cfg["arquivo_alvo"])
    limite = int(cfg["limite_bytes"])

    if not alvo.exists():
        raise SystemExit(f"ERRO: arquivo alvo ausente: {alvo}")

    tamanho = alvo.stat().st_size
    print(f"{alvo}: {tamanho} bytes; limite: {limite} bytes")

    if tamanho > limite:
        raise SystemExit(
            "BLOQUEADO: histórico Z-R excedeu o guard rail. "
            "Revisar retenção/compactação antes de publicar."
        )

    print("GUARD RAIL Z-R: APROVADO")

if __name__ == "__main__":
    main()

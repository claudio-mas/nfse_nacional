"""Catálogos extraídos dos anexos oficiais.

Cada módulo aqui é **gerado** por um script em `tools/` e carrega os dados
embutidos. Os anexos não vão na wheel, e a biblioteca não pode depender de ler
markdown em runtime.

`tools/gerar_catalogo_servicos.py --conferir` roda no CI e prova que o que está
versionado é exatamente o que sai do anexo versionado.
"""

from __future__ import annotations

from nfsenacional.catalogos.servicos import (
    SERVICOS,
    TOTAL_DE_SERVICOS,
    Servico,
    buscar_servico,
    por_codigo,
)

__all__ = ["SERVICOS", "TOTAL_DE_SERVICOS", "Servico", "buscar_servico", "por_codigo"]

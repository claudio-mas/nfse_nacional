"""Catálogos extraídos dos anexos oficiais.

Cada módulo aqui é **gerado** por um script em `tools/` e carrega os dados
embutidos. Os anexos não vão na wheel, e a biblioteca não pode depender de ler
markdown em runtime.

`tools/gerar_catalogo_servicos.py --conferir` roda no CI e prova que o que está
versionado é exatamente o que sai do anexo versionado.
"""

from __future__ import annotations

from nfse_sefin.catalogos.rejeicoes import (
    REJEICOES,
    TOTAL_DE_REJEICOES,
    Rejeicao,
    buscar_rejeicao,
)
from nfse_sefin.catalogos.rejeicoes import por_codigo as rejeicao_por_codigo
from nfse_sefin.catalogos.servicos import (
    SERVICOS,
    TOTAL_DE_SERVICOS,
    Servico,
    buscar_servico,
)
from nfse_sefin.catalogos.servicos import por_codigo as servico_por_codigo

# `por_codigo` de serviço fica com o nome curto por compatibilidade com o v0.1.0.
por_codigo = servico_por_codigo

__all__ = [
    "SERVICOS",
    "TOTAL_DE_SERVICOS",
    "Servico",
    "buscar_servico",
    "por_codigo",
    "servico_por_codigo",
    "REJEICOES",
    "TOTAL_DE_REJEICOES",
    "Rejeicao",
    "buscar_rejeicao",
    "rejeicao_por_codigo",
]

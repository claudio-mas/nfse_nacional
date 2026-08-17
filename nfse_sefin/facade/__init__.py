"""A fachada: dados puros, sem `nfelib`.

Nenhum módulo daqui importa `nfelib`. A tradução para os bindings gerados mora em
`adapters/nfelib.py`, que é o único autorizado a importá-la e o único que serializa.
A separação mantém a fachada testável sem a dependência e concentra num arquivo só a
quebra que um leiaute novo vai causar.
"""

from __future__ import annotations

from nfse_sefin.facade.dps import DPS, VERSAO_APLICACAO
from nfse_sefin.facade.enums import (
    OpcaoSimplesNacional,
    RegimeApuracaoSN,
    RegimeEspecial,
    RetencaoISSQN,
    TipoEmitente,
    TributacaoISSQN,
)
from nfse_sefin.facade.pessoa import Endereco, Prestador, Tomador
from nfse_sefin.facade.servico import Servico
from nfse_sefin.facade.tributos import TotalTributos

__all__ = [
    "DPS",
    "VERSAO_APLICACAO",
    "Endereco",
    "OpcaoSimplesNacional",
    "Prestador",
    "RegimeApuracaoSN",
    "RegimeEspecial",
    "RetencaoISSQN",
    "Servico",
    "TipoEmitente",
    "Tomador",
    "TotalTributos",
    "TributacaoISSQN",
]

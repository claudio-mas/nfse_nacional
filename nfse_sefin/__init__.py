"""Cliente Python para a API REST do Sistema Nacional NFS-e (SEFIN Nacional).

Esqueleto. Os módulos públicos entram na ordem definida em `DESIGN.md`,
seção "Ordem de release":

- v0.1.0 — `ambientes`, `cert`, `transport`, `errors`, `convenio`,
  `catalogos.servicos`, `doctor`. Diagnóstico; não emite nota.
- v0.2.0 — `perfis`, `signing`, `catalogos.rejeicoes`, `facade`, `adapters`,
  emissão, consulta e DANFSe.
"""

from __future__ import annotations

from nfse_sefin._version import __version__
from nfse_sefin.ambientes import BASES, Ambiente, Bases, bases_de
from nfse_sefin.catalogos.servicos import buscar_servico
from nfse_sefin.cert import Certificate
from nfse_sefin.facade import (
    DPS,
    Endereco,
    OpcaoSimplesNacional,
    Prestador,
    RegimeApuracaoSN,
    RegimeEspecial,
    RetencaoISSQN,
    Servico,
    TipoEmitente,
    Tomador,
    TotalTributos,
    TributacaoISSQN,
)

__all__ = [
    "BASES",
    "DPS",
    "Ambiente",
    "Bases",
    "Certificate",
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
    "bases_de",
    "buscar_servico",
    "__version__",
]

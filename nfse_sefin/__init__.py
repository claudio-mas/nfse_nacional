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
from nfse_sefin.client import NFSeClient, NotaFiscal
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
from nfse_sefin.perfis import PERFIL_100, PERFIL_101, Perfil, por_nome
from nfse_sefin.probe import ResultadoProbe, Veredito

__all__ = [
    "BASES",
    "DPS",
    "PERFIL_100",
    "PERFIL_101",
    "Ambiente",
    "Bases",
    "Certificate",
    "Endereco",
    "NFSeClient",
    "NotaFiscal",
    "OpcaoSimplesNacional",
    "Perfil",
    "Prestador",
    "RegimeApuracaoSN",
    "RegimeEspecial",
    "ResultadoProbe",
    "RetencaoISSQN",
    "Servico",
    "TipoEmitente",
    "Tomador",
    "TotalTributos",
    "TributacaoISSQN",
    "Veredito",
    "bases_de",
    "buscar_servico",
    "por_nome",
    "__version__",
]

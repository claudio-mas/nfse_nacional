"""Ambientes e URLs base do Sistema Nacional NFS-e.

O Sistema Nacional não é um servidor só. São **quatro** bases com papéis distintos,
e trocá-las entre si falha de um jeito ruim: `POST /nfse` no ADN não emite nota
nenhuma, e `GET /danfse/{chave}` no SEFIN não devolve PDF nenhum.

| Base | Papel |
|---|---|
| `sefin` | emitir, consultar NFS-e, `/dps/{id}`, eventos |
| `adn` | DANFSe — `GET /danfse/{chave}`, na **raiz**, sem prefixo de caminho |
| `adn_parametrizacao` | convênio municipal e alíquotas |
| `adn_contribuintes` | distribuição `GET /DFe/{NSU}`, eventos por chave |

O ADN é o Ambiente de Dados Nacional: compartilhamento e consulta. Quem gera NFS-e
é a SEFIN.

Este módulo só declara endereços. Montar rota, abrir conexão e falar mTLS é trabalho
do `transport.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

__all__ = ["Ambiente", "Bases", "BASES", "bases_de"]


class Ambiente(Enum):
    """Ambiente de recepção da SEFIN.

    `tp_amb` é o valor que vai no campo `infDPS/tpAmb` do leiaute. O cliente
    sobrescreve esse campo a partir do ambiente configurado, sempre: o leiaute
    rejeita quando o ambiente declarado diverge do ambiente que recebeu a
    requisição, e deixar isso na mão do chamador garante que todo mundo tome essa
    rejeição uma vez.
    """

    PRODUCAO = "producao"
    PRODUCAO_RESTRITA = "producao_restrita"

    @property
    def tp_amb(self) -> str:
        """Valor de `infDPS/tpAmb`: `"1"` em produção, `"2"` em produção restrita."""
        return "1" if self is Ambiente.PRODUCAO else "2"


@dataclass(frozen=True, slots=True)
class Bases:
    """As quatro URLs base de um ambiente, sem barra no fim."""

    sefin: str
    """Emissão e consulta. `POST /nfse`, `GET /nfse/{chave}`, `/dps/{id}`, eventos."""

    adn: str
    """Raiz do ADN. O DANFSe mora aqui: `GET {adn}/danfse/{chave}`.

    É a raiz mesmo, sem `/contribuintes` nem `/parametrizacao`. As duas
    implementações independentes que existem hoje concordam nisso.
    """

    adn_parametrizacao: str
    """Convênio municipal e alíquotas. `GET {adn_parametrizacao}/{codMun}/convenio`."""

    adn_contribuintes: str
    """Distribuição de DF-e. `GET {adn_contribuintes}/DFe/{NSU}`."""


BASES: Mapping[Ambiente, Bases] = MappingProxyType(
    {
        Ambiente.PRODUCAO: Bases(
            sefin="https://sefin.nfse.gov.br/SefinNacional",
            adn="https://adn.nfse.gov.br",
            adn_parametrizacao="https://adn.nfse.gov.br/parametrizacao",
            adn_contribuintes="https://adn.nfse.gov.br/contribuintes",
        ),
        Ambiente.PRODUCAO_RESTRITA: Bases(
            sefin="https://sefin.producaorestrita.nfse.gov.br/SefinNacional",
            adn="https://adn.producaorestrita.nfse.gov.br",
            adn_parametrizacao="https://adn.producaorestrita.nfse.gov.br/parametrizacao",
            adn_contribuintes="https://adn.producaorestrita.nfse.gov.br/contribuintes",
        ),
    }
)


def bases_de(ambiente: Ambiente) -> Bases:
    """Devolve as quatro bases do ambiente."""
    return BASES[ambiente]

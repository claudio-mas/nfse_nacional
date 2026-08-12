"""Consulta de convênio municipal — o passo zero de qualquer emissão.

Município que não aderiu ao Sistema Nacional não recebe DPS. Descobrir isso antes de
montar o XML economiza a rodada inteira de depuração que uma rejeição genérica
provoca.

## Duas rotas candidatas, nenhuma verificável de mesa

A documentação e a única implementação em produção discordam do caminho:

| Fonte | Caminho |
|---|---|
| Manual do Emissor Público v1.2 (out/2025) | `/parametros_municipais/{codMun}/convenio` |
| `pynfse-nacional` 0.9.5, 12 releases | `{ADN}/parametrizacao/{codMun}/convenio` |

Nada responde sem certificado cliente (OQ6), então não dá para decidir de mesa qual
está certo — nem o Swagger de produção restrita abre. Em vez de apostar num dos dois
e descobrir em campo, `consultar_convenio` tenta os dois e reporta qual respondeu.
É o mesmo princípio que o `doctor` usa para o par de assinatura: quando a
documentação e a prática discordam e não dá para testar, quem descobre é a
ferramenta, não o usuário.

## A forma da resposta é desconhecida, e isto é deliberado

O manual descreve o serviço mas não publica o schema, e a implementação concorrente
também não o conhece — ela infere adesão pelo status HTTP e guarda o corpo inteiro
sem tipar. Aqui é igual: `aderido` sai do status, e `dados` é o corpo cru.

Tipar campos que ninguém verificou seria inventar leiaute, que é exatamente o que
este projeto não faz. Quando houver certificado e uma resposta real (OQ12), os
campos entram com nome e tipo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nfse_sefin.ambientes import Bases
from nfse_sefin.errors import TransporteError
from nfse_sefin.transport import Transporte

__all__ = ["Convenio", "consultar_convenio", "CAMINHOS_CANDIDATOS", "valida_codigo_ibge"]

CAMINHOS_CANDIDATOS: tuple[str, ...] = (
    "{base}/{codigo}/convenio",
    "{base}/parametros_municipais/{codigo}/convenio",
)
"""Em ordem de tentativa: primeiro o que uma implementação em produção usa, depois o
que o manual documenta."""


def valida_codigo_ibge(codigo: str) -> bool:
    """Código IBGE de município: exatamente 7 dígitos.

    Decidível offline (P7), então não custa uma ida à rede para descobrir que o
    usuário digitou 6 dígitos.
    """
    return len(codigo) == 7 and codigo.isdigit()


@dataclass(frozen=True, slots=True)
class Convenio:
    """Resultado da consulta de convênio de um município."""

    codigo_municipio: str
    """Código IBGE de 7 dígitos, como consultado."""

    aderido: bool
    """O município respondeu como conveniado ao Sistema Nacional.

    Vem do status HTTP: 2xx é aderido, 404 não é. Ver a nota no topo do módulo sobre
    por que não sai de um campo do corpo.
    """

    caminho: str = ""
    """A rota que efetivamente respondeu. Vazia quando nenhuma respondeu.

    É o dado que decide qual das duas fontes está certa, e o `doctor` o imprime.
    """

    dados: dict[str, Any] = field(default_factory=dict)
    """Corpo da resposta, cru e sem tipar. Vazio quando não aderido."""


def consultar_convenio(
    transporte: Transporte,
    bases: Bases,
    codigo_municipio: str,
) -> Convenio:
    """Consulta o convênio de um município, tentando as duas rotas candidatas.

    Raises:
        ValueError: código IBGE fora do formato de 7 dígitos.
        TransporteError: se todas as rotas falharem por motivo que não seja 404.
            Um 404 é resposta legítima — significa "não conveniado" —, então ele não
            vira exceção, vira `aderido=False`.
    """
    if not valida_codigo_ibge(codigo_municipio):
        raise ValueError(
            f"Código IBGE de município deve ter 7 dígitos numéricos; recebido {codigo_municipio!r}."
        )

    ultima_falha: TransporteError | None = None

    for molde in CAMINHOS_CANDIDATOS:
        url = molde.format(base=bases.adn_parametrizacao, codigo=codigo_municipio)
        try:
            corpo = transporte.get_json(url)
        except TransporteError as exc:
            if exc.status_code == 404:
                # 404 pode significar "município não conveniado" ou "rota errada". A
                # única forma de separar os dois é tentar a outra rota; se as duas
                # derem 404, o município é que não aderiu.
                ultima_falha = exc
                continue
            raise

        return Convenio(
            codigo_municipio=codigo_municipio,
            aderido=True,
            caminho=url,
            dados=corpo if isinstance(corpo, dict) else {"resposta": corpo},
        )

    if ultima_falha is not None:
        return Convenio(codigo_municipio=codigo_municipio, aderido=False)

    raise TransporteError(  # pragma: no cover - inalcançável com a lista atual
        f"Nenhuma rota candidata de convênio foi tentada para {codigo_municipio}."
    )

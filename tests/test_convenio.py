"""Testes de `nfsenacional.convenio`.

O ponto delicado aqui é que **404 é ambíguo**: pode ser "município não conveniado" ou
"a rota está errada". Como o manual oficial e a única implementação em produção
discordam do caminho, e nada responde sem certificado, o módulo tenta as duas rotas
antes de concluir qualquer coisa. Estes testes travam esse comportamento.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock

from nfsenacional.ambientes import Ambiente, bases_de
from nfsenacional.convenio import (
    CAMINHOS_CANDIDATOS,
    Convenio,
    consultar_convenio,
    valida_codigo_ibge,
)
from nfsenacional.errors import TransporteError
from nfsenacional.transport import Transporte

BASES = bases_de(Ambiente.PRODUCAO_RESTRITA)
MUNICIPIO = "3304557"  # Rio de Janeiro

URL_IMPLEMENTACAO = f"{BASES.adn_parametrizacao}/{MUNICIPIO}/convenio"
URL_MANUAL = f"{BASES.adn_parametrizacao}/parametros_municipais/{MUNICIPIO}/convenio"


@pytest.fixture
def transporte() -> Any:
    return Transporte(
        certificate=None,  # type: ignore[arg-type]
        client=httpx.Client(),
        espera_base=0.01,
        dormir=lambda _: None,
    )


# ------------------------------------------------------------ código IBGE


@pytest.mark.parametrize("codigo", ["3304557", "1400159", "0000000"])
def test_codigo_ibge_valido(codigo: str) -> None:
    assert valida_codigo_ibge(codigo)


@pytest.mark.parametrize("codigo", ["330455", "33045578", "", "33045A7", "3304 557"])
def test_codigo_ibge_invalido(codigo: str) -> None:
    assert not valida_codigo_ibge(codigo)


def test_consulta_recusa_codigo_malformado(transporte: Any) -> None:
    """P7: decidível offline, então não custa uma ida à rede para descobrir."""
    with pytest.raises(ValueError, match="7 dígitos"):
        consultar_convenio(transporte, BASES, "330455")


# ---------------------------------------------------- as duas rotas candidatas


def test_primeira_rota_responde(transporte: Any, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=URL_IMPLEMENTACAO, json={"algo": "coisa"})

    convenio = consultar_convenio(transporte, BASES, MUNICIPIO)

    assert convenio.aderido
    assert convenio.caminho == URL_IMPLEMENTACAO
    assert convenio.dados == {"algo": "coisa"}
    assert len(httpx_mock.get_requests()) == 1, "não deveria tentar a segunda rota"


def test_cai_para_a_rota_do_manual(transporte: Any, httpx_mock: HTTPXMock) -> None:
    """404 na primeira não conclui nada: pode ser a rota, não o município."""
    httpx_mock.add_response(method="GET", url=URL_IMPLEMENTACAO, status_code=404)
    httpx_mock.add_response(method="GET", url=URL_MANUAL, json={"algo": "coisa"})

    convenio = consultar_convenio(transporte, BASES, MUNICIPIO)

    assert convenio.aderido
    assert convenio.caminho == URL_MANUAL


def test_404_nas_duas_rotas_significa_nao_aderido(transporte: Any, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=URL_IMPLEMENTACAO, status_code=404)
    httpx_mock.add_response(method="GET", url=URL_MANUAL, status_code=404)

    convenio = consultar_convenio(transporte, BASES, MUNICIPIO)

    assert not convenio.aderido
    assert convenio.caminho == ""
    assert convenio.dados == {}
    assert len(httpx_mock.get_requests()) == 2


def test_erro_que_nao_e_404_sobe_na_hora(transporte: Any, httpx_mock: HTTPXMock) -> None:
    """403 é o servidor recusando o certificado. Tentar a outra rota não ajuda."""
    httpx_mock.add_response(method="GET", url=URL_IMPLEMENTACAO, status_code=403)

    with pytest.raises(TransporteError) as capturado:
        consultar_convenio(transporte, BASES, MUNICIPIO)

    assert capturado.value.status_code == 403
    assert len(httpx_mock.get_requests()) == 1


def test_ordem_das_rotas_privilegia_a_implementacao_que_roda() -> None:
    """Primeiro o que uma lib em produção usa, depois o que o manual documenta.

    Se a ordem inverter sem motivo, o caminho mais provável passa a ser o segundo a
    ser tentado, e toda consulta paga um 404 antes de funcionar.
    """
    assert CAMINHOS_CANDIDATOS[0] == "{base}/{codigo}/convenio"
    assert "parametros_municipais" in CAMINHOS_CANDIDATOS[1]


def test_resposta_que_nao_e_objeto_e_embrulhada(transporte: Any, httpx_mock: HTTPXMock) -> None:
    """A forma do corpo é desconhecida; uma lista no topo não pode quebrar a consulta."""
    httpx_mock.add_response(method="GET", url=URL_IMPLEMENTACAO, json=[1, 2, 3])

    convenio = consultar_convenio(transporte, BASES, MUNICIPIO)

    assert convenio.aderido
    assert convenio.dados == {"resposta": [1, 2, 3]}


def test_convenio_e_imutavel() -> None:
    convenio = Convenio(codigo_municipio=MUNICIPIO, aderido=True)
    with pytest.raises(AttributeError):
        convenio.aderido = False  # type: ignore[misc]

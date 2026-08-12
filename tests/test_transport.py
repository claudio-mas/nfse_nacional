"""Testes de `nfse_sefin.transport`.

O teste que mais importa aqui é `test_post_nunca_repete`: repetir um `POST /nfse`
significa emitir a mesma nota fiscal duas vezes. É o tipo de defeito que passa em
revisão, passa em homologação, e aparece na contabilidade do cliente.
"""

from __future__ import annotations

import gzip
from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock

from nfse_sefin.errors import (
    MensagemSefin,
    NFSeError,
    RespostaInvalidaError,
    TransporteError,
)
from nfse_sefin.transport import (
    METODOS_COM_RETRY,
    Transporte,
    de_gzip_b64,
    gzip_b64,
    normalizar_mensagens,
)

URL = "https://sefin.producaorestrita.nfse.gov.br/SefinNacional/nfse"


@pytest.fixture
def transporte() -> Any:
    """Transporte sobre um `httpx.Client` injetado, sem TLS e sem espera real."""
    esperas: list[float] = []
    cliente = httpx.Client(headers={"Content-Type": "application/json"})
    transporte = Transporte(
        certificate=None,  # type: ignore[arg-type]
        client=cliente,
        espera_base=0.01,
        dormir=esperas.append,
    )
    transporte.esperas = esperas  # type: ignore[attr-defined]
    return transporte


# ---------------------------------------------------------------- gzip+b64


def test_gzip_b64_ida_e_volta() -> None:
    xml = b'<?xml version="1.0" encoding="UTF-8"?><DPS versao="1.00"/>'
    assert de_gzip_b64(gzip_b64(xml)) == xml


def test_gzip_b64_e_gzip_de_verdade() -> None:
    """Não é raw deflate nem zlib. Três implementações independentes usam gzip."""
    import base64

    bruto = base64.b64decode(gzip_b64(b"conteudo"))
    assert bruto[:2] == b"\x1f\x8b"  # magic do gzip
    assert gzip.decompress(bruto) == b"conteudo"


def test_gzip_b64_e_deterministico() -> None:
    """`mtime=0`: o mesmo XML produz sempre o mesmo payload."""
    assert gzip_b64(b"mesmo conteudo") == gzip_b64(b"mesmo conteudo")


def test_gzip_b64_aguenta_utf8() -> None:
    """E1229: o XML é UTF-8, com acento e cedilha de razão social brasileira."""
    xml = "<x>Serviço de manutenção — ação</x>".encode()
    assert de_gzip_b64(gzip_b64(xml)).decode("utf-8") == xml.decode("utf-8")


@pytest.mark.parametrize("lixo", ["nao e base64!!", "", "aGVsbG8="])
def test_de_gzip_b64_recusa_lixo(lixo: str) -> None:
    with pytest.raises(RespostaInvalidaError):
        de_gzip_b64(lixo)


# --------------------------------------------- normalização das 4 formas (P11)


def test_forma_1_erro_lista() -> None:
    corpo = {
        "erro": [{"codigo": "E0014", "descricao": "DPS duplicada", "complemento": "serie 900"}]
    }
    assert normalizar_mensagens(corpo) == (
        MensagemSefin(codigo="E0014", descricao="DPS duplicada", complemento="serie 900"),
    )


def test_forma_2_erros_lista() -> None:
    corpo = {"erros": [{"codigo": "E1228", "descricao": "Prefixo de namespace"}]}
    (mensagem,) = normalizar_mensagens(corpo)
    assert mensagem.codigo == "E1228"


def test_forma_3_lista_nua_no_topo() -> None:
    corpo = [
        {"codigo": "E0001", "descricao": "primeiro"},
        {"codigo": "E0002", "descricao": "segundo"},
    ]
    assert [m.codigo for m in normalizar_mensagens(corpo)] == ["E0001", "E0002"]


def test_forma_4_legado_codigo_mensagem() -> None:
    corpo = {"codigo": "500", "mensagem": "Erro interno"}
    (mensagem,) = normalizar_mensagens(corpo)
    assert mensagem.codigo == "500"
    assert mensagem.descricao == "Erro interno"


def test_capitalizacao_variavel() -> None:
    """A API mistura `codigo` e `Codigo` entre endpoints."""
    (mensagem,) = normalizar_mensagens({"Erro": [{"Codigo": "E0014", "Descricao": "dup"}]})
    assert mensagem.codigo == "E0014"
    assert mensagem.descricao == "dup"


def test_erro_como_objeto_unico_e_nao_lista() -> None:
    (mensagem,) = normalizar_mensagens({"erro": {"codigo": "E9", "descricao": "único"}})
    assert mensagem.codigo == "E9"


def test_lista_de_strings() -> None:
    (mensagem,) = normalizar_mensagens(["algo deu errado"])
    assert mensagem.descricao == "algo deu errado"
    assert mensagem.codigo == ""


@pytest.mark.parametrize("corpo", [None, "", 42, {}, [], {"outra": "coisa"}, [None, {}]])
def test_normalizar_nunca_levanta(corpo: object) -> None:
    """Quem chama já está tratando um erro; não pode receber outro por cima."""
    assert normalizar_mensagens(corpo) == ()


def test_mensagem_tem_str_legivel() -> None:
    mensagem = MensagemSefin(codigo="E0014", descricao="DPS duplicada", complemento="serie 900")
    assert str(mensagem) == "E0014 — DPS duplicada — serie 900"
    assert str(MensagemSefin(codigo="", descricao="")) == "(mensagem vazia)"


# ------------------------------------------------------- retry só em leitura


def test_post_nunca_repete(transporte: Any, httpx_mock: HTTPXMock) -> None:
    """P8, e é o teste mais importante deste arquivo.

    `POST /nfse` é escrita fiscal não idempotente. Um retry depois de o servidor ter
    processado emite a mesma nota duas vezes, e a segunda volta rejeitada por
    série+número+município+CNPJ repetidos. Uma tentativa, sempre.
    """
    httpx_mock.add_response(method="POST", url=URL, status_code=503)

    with pytest.raises(TransporteError) as capturado:
        transporte.post_json(URL, {"dpsXmlGZipB64": "..."})

    assert len(httpx_mock.get_requests()) == 1
    assert capturado.value.status_code == 503
    assert transporte.esperas == []


def test_post_nao_repete_nem_em_erro_de_rede(transporte: Any, httpx_mock: HTTPXMock) -> None:
    """Timeout é o caso perigoso: o servidor pode ter processado mesmo assim."""
    httpx_mock.add_exception(httpx.ReadTimeout("estourou"), method="POST", url=URL)

    with pytest.raises(TransporteError, match="1 tentativa"):
        transporte.post_json(URL, {"dpsXmlGZipB64": "..."})

    assert len(httpx_mock.get_requests()) == 1


def test_get_repete_em_5xx_e_desiste(transporte: Any, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=URL, status_code=502, is_reusable=True)

    with pytest.raises(TransporteError) as capturado:
        transporte.get_json(URL)

    assert len(httpx_mock.get_requests()) == 3
    assert capturado.value.status_code == 502
    assert len(transporte.esperas) == 2


def test_get_repete_e_tem_sucesso(transporte: Any, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=URL, status_code=503)
    httpx_mock.add_response(method="GET", url=URL, json={"chaveAcesso": "35..."})

    assert transporte.get_json(URL) == {"chaveAcesso": "35..."}
    assert len(httpx_mock.get_requests()) == 2


def test_get_nao_repete_em_4xx(transporte: Any, httpx_mock: HTTPXMock) -> None:
    """4xx é decisão do servidor sobre esta requisição. Repetir só atrasa."""
    httpx_mock.add_response(method="GET", url=URL, status_code=404)

    with pytest.raises(TransporteError):
        transporte.get_json(URL)

    assert len(httpx_mock.get_requests()) == 1


def test_espera_dobra_a_cada_tentativa(transporte: Any, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=URL, status_code=500, is_reusable=True)

    with pytest.raises(TransporteError):
        transporte.get_json(URL)

    assert transporte.esperas == [0.01, 0.02]


def test_metodos_com_retry_e_so_leitura() -> None:
    assert METODOS_COM_RETRY == {"GET", "HEAD"}
    assert "POST" not in METODOS_COM_RETRY


def test_tentativas_invalidas() -> None:
    with pytest.raises(ValueError, match="pelo menos 1"):
        Transporte(certificate=None, client=httpx.Client(), tentativas=0)  # type: ignore[arg-type]


# ------------------------------------------------------------------- verbos


def test_head_distingue_200_de_404(transporte: Any, httpx_mock: HTTPXMock) -> None:
    """`HEAD /dps/{id}` é o primeiro passo da recuperação de emissão ambígua."""
    httpx_mock.add_response(method="HEAD", url=URL, status_code=200)
    assert transporte.head(URL) is True

    httpx_mock.reset()
    httpx_mock.add_response(method="HEAD", url=URL, status_code=404)
    assert transporte.head(URL) is False


def test_head_nao_engole_500(transporte: Any, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="HEAD", url=URL, status_code=500, is_reusable=True)
    with pytest.raises(TransporteError):
        transporte.head(URL)


def test_get_bytes_devolve_binario(transporte: Any, httpx_mock: HTTPXMock) -> None:
    """DANFSe volta como PDF, não como JSON."""
    httpx_mock.add_response(method="GET", url=URL, content=b"%PDF-1.4 conteudo")
    assert transporte.get_bytes(URL).startswith(b"%PDF")


def test_post_manda_o_envelope_json(transporte: Any, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=URL, json={"chaveAcesso": "35..."})

    transporte.post_json(URL, {"dpsXmlGZipB64": gzip_b64(b"<DPS/>")})

    requisicao = httpx_mock.get_requests()[0]
    import json as _json

    enviado = _json.loads(requisicao.content)
    assert set(enviado) == {"dpsXmlGZipB64"}
    assert de_gzip_b64(enviado["dpsXmlGZipB64"]) == b"<DPS/>"
    assert requisicao.headers["content-type"] == "application/json"


def test_corpo_vazio_vira_dicionario_vazio(transporte: Any, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=URL, content=b"")
    assert transporte.get_json(URL) == {}


def test_2xx_que_nao_e_json(transporte: Any, httpx_mock: HTTPXMock) -> None:
    """Conversa funcionou, contrato mudou. Erro diferente de queda de rede."""
    httpx_mock.add_response(method="GET", url=URL, content=b"<html>manutencao</html>")

    with pytest.raises(RespostaInvalidaError, match="não é JSON"):
        transporte.get_json(URL)


# -------------------------------------------------------------- erro rico


def test_erro_carrega_codigos_normalizados(transporte: Any, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=URL,
        status_code=400,
        json={"erro": [{"codigo": "E0014", "descricao": "DPS duplicada"}]},
    )

    with pytest.raises(TransporteError) as capturado:
        transporte.post_json(URL, {"dpsXmlGZipB64": "..."})

    erro = capturado.value
    assert erro.status_code == 400
    assert erro.codigos == ("E0014",)
    assert "E0014" in str(erro)
    assert "DPS duplicada" in str(erro)
    assert erro.metodo == "POST"
    assert erro.url == URL


def test_erro_com_corpo_nao_json_ainda_e_util(transporte: Any, httpx_mock: HTTPXMock) -> None:
    """Proxy no meio devolve HTML. O status e o corpo ainda ajudam a diagnosticar."""
    httpx_mock.add_response(
        method="POST", url=URL, status_code=502, content=b"<html>Bad Gateway</html>"
    )

    with pytest.raises(TransporteError) as capturado:
        transporte.post_json(URL, {})

    assert capturado.value.codigos == ()
    assert "Bad Gateway" in capturado.value.corpo


def test_corpo_gigante_e_truncado_no_erro(transporte: Any, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=URL, status_code=500, content=b"x" * 50_000)

    with pytest.raises(TransporteError) as capturado:
        transporte.post_json(URL, {})

    assert len(capturado.value.corpo) <= 2000


def test_erros_descendem_de_nfse_error(transporte: Any, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=URL, status_code=400)
    with pytest.raises(NFSeError):
        transporte.post_json(URL, {})


# --------------------------------------------------------- ciclo de vida


def test_nao_fecha_cliente_injetado(httpx_mock: HTTPXMock) -> None:
    """Quem passou o cliente é dono dele; fechar por baixo seria surpresa."""
    cliente = httpx.Client()
    with Transporte(certificate=None, client=cliente) as transporte:  # type: ignore[arg-type]
        assert transporte is not None
    assert not cliente.is_closed


def test_contexto_fecha_cliente_proprio(pfx_valido: Any) -> None:
    """Sem cliente injetado, o transporte monta o dele — e o fecha."""
    from nfse_sefin.cert import Certificate

    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)
    with Transporte(cert) as transporte:
        cliente = transporte._client
    assert cliente.is_closed

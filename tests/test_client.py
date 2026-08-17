"""Testes de `NFSeClient` — as quatro operações de v0.2.0.

O que se prova aqui, além do caminho feliz:

- **`tpAmb` é do cliente.** Uma DPS montada para produção restrita e enviada por um
  cliente de produção sai com `tpAmb=1`, com aviso no log. O contrário — confiar no
  valor que veio — significa emitir nota real marcada como teste.
- **Rejeição não é erro de transporte.** `E0014` no corpo vira `RejeicaoNFSe` com o
  texto do anexo, não `TransporteError` com um número HTTP.
- **P8: emissão não repete.** Um único `POST`, sempre. E, na falha ambígua, a exceção
  aponta o caminho de recuperação em vez de sugerir reenvio.
- **Cada operação vai para a base certa.** `POST /nfse` na SEFIN, DANFSe na raiz do
  ADN. Trocar as duas falha de um jeito que o servidor não explica.
"""

from __future__ import annotations

import gzip
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock

from nfse_sefin.ambientes import Ambiente, bases_de
from nfse_sefin.cert import Certificate
from nfse_sefin.client import CAMPO_DPS, CAMPO_NFSE, NFSeClient, NotaFiscal, normalizar_chave
from nfse_sefin.errors import (
    DadosInvalidosError,
    RejeicaoNFSe,
    RespostaInvalidaError,
    TransporteError,
)
from nfse_sefin.facade import DPS, OpcaoSimplesNacional, Prestador, Servico
from nfse_sefin.transport import Transporte, de_gzip_b64, gzip_b64

FUSO_BR = timezone(timedelta(hours=-3))

BASES_RESTRITA = bases_de(Ambiente.PRODUCAO_RESTRITA)
BASES_PRODUCAO = bases_de(Ambiente.PRODUCAO)

CNPJ = "01761135000132"
MUNICIPIO = "1400159"
ID_DPS = "DPS140015920176113500013200900000000000000006"
CHAVE = "1" * 50

URL_EMITIR = f"{BASES_RESTRITA.sefin}/nfse"
URL_CONSULTA = f"{BASES_RESTRITA.sefin}/nfse/{CHAVE}"
URL_DPS = f"{BASES_RESTRITA.sefin}/dps/{ID_DPS}"
URL_DANFSE = f"{BASES_RESTRITA.adn}/danfse/{CHAVE}"


# --------------------------------------------------------------------- fixtures


@pytest.fixture
def dps() -> DPS:
    return DPS(
        prestador=Prestador(cnpj=CNPJ, simples_nacional=OpcaoSimplesNacional.MEI),
        servico=Servico(
            codigo="010101",
            descricao="Banho e tosa",
            valor=Decimal("150.00"),
            municipio_prestacao=MUNICIPIO,
        ),
        serie="900",
        numero="6",
        competencia=date(2022, 9, 28),
        municipio_emissor=MUNICIPIO,
        emitido_em=datetime(2022, 9, 28, 13, 50, 29, tzinfo=FUSO_BR),
    )


@pytest.fixture
def certificado(pfx_valido: Any) -> Certificate:
    return Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)


def _cliente(certificado: Certificate, **kwargs: Any) -> NFSeClient:
    transporte = Transporte(
        certificate=certificado,
        client=httpx.Client(),
        espera_base=0.01,
        dormir=lambda _: None,
    )
    return NFSeClient(certificado, transporte=transporte, **kwargs)


@pytest.fixture
def cliente(certificado: Certificate) -> NFSeClient:
    return _cliente(certificado)


NFSE_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?><NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"/>'
)


def _resposta_ok(**extra: Any) -> dict[str, Any]:
    corpo: dict[str, Any] = {
        "chaveAcesso": CHAVE,
        "idDps": ID_DPS,
        "tipoAmbiente": "2",
        "versaoAplicativo": "SefinNacional_1.0",
        "dataHoraProcessamento": "2022-09-28T13:50:31-03:00",
        CAMPO_NFSE: gzip_b64(NFSE_XML),
    }
    corpo.update(extra)
    return corpo


# ------------------------------------------------------------ chave de acesso


def test_chave_de_50_digitos() -> None:
    assert normalizar_chave(CHAVE) == CHAVE


def test_chave_com_o_literal_nfs() -> None:
    """O `Id` da NFS-e tem 53 posições porque leva `NFS` na frente.

    Quem copia do XML da nota cola 53 caracteres; quem copia de relatório cola 50.
    """
    assert normalizar_chave(f"NFS{CHAVE}") == CHAVE


def test_chave_com_espaco_e_pontuacao() -> None:
    assert normalizar_chave(f"  {CHAVE[:25]} {CHAVE[25:]}  ") == CHAVE


@pytest.mark.parametrize("entrada", ["", "123", "1" * 49, "1" * 51, "A" * 50])
def test_chave_invalida(entrada: str) -> None:
    with pytest.raises(DadosInvalidosError, match="50 dígitos"):
        normalizar_chave(entrada)


# -------------------------------------------------------------------- emitir


def test_emitir_envia_o_xml_assinado_no_envelope(
    cliente: NFSeClient, dps: DPS, httpx_mock: HTTPXMock
) -> None:
    """O payload é o XML assinado, gzip, base64, num campo de JSON."""
    httpx_mock.add_response(url=URL_EMITIR, method="POST", json=_resposta_ok())

    nota = cliente.emitir(dps)

    (requisicao,) = httpx_mock.get_requests()
    enviado = requisicao.read()
    assert requisicao.method == "POST"

    import json

    envelope = json.loads(enviado)
    assert set(envelope) == {CAMPO_DPS}

    xml = de_gzip_b64(envelope[CAMPO_DPS])
    # E1229: UTF-8 declarado. A declaração vem do `lxml` (aspas simples, com
    # `standalone`), não do `xsdata`, porque quem serializa por último é a assinatura.
    assert xml.startswith(b"<?xml ") and b"UTF-8" in xml[:60]
    assert b"<Signature" in xml
    assert ID_DPS.encode() in xml

    assert nota.chave_acesso == CHAVE
    assert nota.xml == NFSE_XML
    assert nota.id_dps == ID_DPS


def test_emitir_assina_com_o_perfil_do_cliente(
    certificado: Certificate, dps: DPS, httpx_mock: HTTPXMock
) -> None:
    """O eixo de perfil chega até o byte enviado, não para em `signing`."""
    from nfse_sefin.perfis import PERFIL_101

    httpx_mock.add_response(url=URL_EMITIR, method="POST", json=_resposta_ok())
    _cliente(certificado, perfil=PERFIL_101).emitir(dps)

    import json

    (requisicao,) = httpx_mock.get_requests()
    xml = de_gzip_b64(json.loads(requisicao.read())[CAMPO_DPS])

    assert b'versao="1.01"' in xml
    assert b"xmldsig-more#rsa-sha256" in xml


def test_emitir_vai_para_a_sefin_e_nao_para_o_adn(
    cliente: NFSeClient, dps: DPS, httpx_mock: HTTPXMock
) -> None:
    """`POST /nfse` no ADN não emite nota nenhuma."""
    httpx_mock.add_response(url=URL_EMITIR, method="POST", json=_resposta_ok())
    cliente.emitir(dps)

    (requisicao,) = httpx_mock.get_requests()
    assert str(requisicao.url).startswith(BASES_RESTRITA.sefin)


def test_emitir_nao_repete(cliente: NFSeClient, dps: DPS, httpx_mock: HTTPXMock) -> None:
    """P8: escrita fiscal não idempotente. Um POST, sempre.

    Repetir depois de o servidor ter processado é tentar emitir a mesma nota duas
    vezes, e a segunda volta com E0014.
    """
    httpx_mock.add_response(url=URL_EMITIR, method="POST", status_code=503, json={})

    with pytest.raises(TransporteError):
        cliente.emitir(dps)

    assert len(httpx_mock.get_requests()) == 1


def test_emitir_traduz_rejeicao(cliente: NFSeClient, dps: DPS, httpx_mock: HTTPXMock) -> None:
    """`E0014` vira o texto do anexo e o caminho XML, não um número HTTP."""
    httpx_mock.add_response(
        url=URL_EMITIR,
        method="POST",
        status_code=400,
        json={"erro": [{"codigo": "E0014", "descricao": "DPS duplicada"}]},
    )

    with pytest.raises(RejeicaoNFSe) as capturado:
        cliente.emitir(dps)

    erro = capturado.value
    assert erro.codigos == ("E0014",)
    assert "já existe em uma NFS-e" in str(erro)
    assert erro.caminhos_xml == ("NFSe/infNFSe/DPS/infDPS/serie",)
    assert erro.status_code == 400


def test_erro_sem_codigo_do_anexo_continua_transporte(
    cliente: NFSeClient, dps: DPS, httpx_mock: HTTPXMock
) -> None:
    """502 de proxy não é decisão de negócio, e chamá-la de rejeição enganaria.

    A diferença importa: transporte às vezes passa na próxima; rejeição devolve o
    mesmo erro para o mesmo XML, sempre.
    """
    httpx_mock.add_response(
        url=URL_EMITIR, method="POST", status_code=502, text="<html>Bad Gateway</html>"
    )

    with pytest.raises(TransporteError) as capturado:
        cliente.emitir(dps)
    assert not isinstance(capturado.value, RejeicaoNFSe)


def test_falha_ambigua_aponta_a_recuperacao(
    cliente: NFSeClient, dps: DPS, httpx_mock: HTTPXMock
) -> None:
    """Conexão perdida sem status: a nota pode ter sido gerada.

    A exceção carrega o identificador e o caminho documentado. Não reenviar é o
    ponto — reenviar apagaria a informação de que a primeira funcionou.
    """
    httpx_mock.add_exception(httpx.ConnectError("conexão perdida"), url=URL_EMITIR, method="POST")

    with pytest.raises(TransporteError) as capturado:
        cliente.emitir(dps)

    mensagem = str(capturado.value)
    assert "NÃO reenvie" in mensagem
    assert "dps_foi_processada" in mensagem
    assert "chave_por_dps" in mensagem
    assert ID_DPS in mensagem


def test_resposta_sem_chave_e_contrato_quebrado(
    cliente: NFSeClient, dps: DPS, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(url=URL_EMITIR, method="POST", json={"algo": "inesperado"})

    with pytest.raises(RespostaInvalidaError, match="sem chave de acesso"):
        cliente.emitir(dps)


def test_resposta_sem_xml_da_nota(cliente: NFSeClient, dps: DPS, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=URL_EMITIR, method="POST", json={"chaveAcesso": CHAVE})

    with pytest.raises(RespostaInvalidaError, match=CAMPO_NFSE):
        cliente.emitir(dps)


def test_alertas_acompanham_a_emissao(cliente: NFSeClient, dps: DPS, httpx_mock: HTTPXMock) -> None:
    """Aviso numa resposta de sucesso não é rejeição, e não pode virar exceção."""
    httpx_mock.add_response(
        url=URL_EMITIR,
        method="POST",
        json=_resposta_ok(alertas=[{"codigo": "A001", "descricao": "Alíquota parametrizada"}]),
    )

    nota = cliente.emitir(dps)

    assert nota.chave_acesso == CHAVE
    assert [a.codigo for a in nota.alertas] == ["A001"]


def test_emissao_sem_alerta_nao_inventa_um(
    cliente: NFSeClient, dps: DPS, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(url=URL_EMITIR, method="POST", json=_resposta_ok())
    assert cliente.emitir(dps).alertas == ()


def test_campo_de_texto_no_sucesso_nao_vira_alerta(
    cliente: NFSeClient, dps: DPS, httpx_mock: HTTPXMock
) -> None:
    """A razão de `alertas` não sair de `normalizar_mensagens(corpo)`.

    Aquela função, sem lista de erro, cai no formato legado e lê a raiz como se
    fosse uma mensagem. Um `motivo` no topo de uma resposta bem-sucedida viraria
    alerta em toda emissão — e com o contrato instável de P11 esse campo aparece
    quando o servidor quiser, sem release nosso.
    """
    from nfse_sefin.transport import normalizar_mensagens

    corpo = _resposta_ok(motivo="Processado com sucesso")

    # O caminho ingênuo produz o alerta espúrio; o nosso, não.
    assert normalizar_mensagens(corpo) != ()

    httpx_mock.add_response(url=URL_EMITIR, method="POST", json=corpo)
    assert cliente.emitir(dps).alertas == ()


def test_alerta_como_objeto_unico(cliente: NFSeClient, dps: DPS, httpx_mock: HTTPXMock) -> None:
    """A API já mandou `erro` como objeto em vez de lista; `alertas` pode repetir."""
    httpx_mock.add_response(
        url=URL_EMITIR,
        method="POST",
        json=_resposta_ok(alertas={"codigo": "A002", "descricao": "Sozinho"}),
    )

    assert [a.codigo for a in cliente.emitir(dps).alertas] == ["A002"]


# ------------------------------------------------------------------- tpAmb


def test_tpamb_e_sobrescrito_pelo_ambiente_do_cliente(
    certificado: Certificate, dps: DPS, httpx_mock: HTTPXMock, caplog: pytest.LogCaptureFixture
) -> None:
    """A DPS foi montada para restrita; o cliente é de produção. Vale o cliente.

    O contrário — confiar no valor que veio — significa emitir nota real marcada
    como teste, ou tomar rejeição por divergência de ambiente.
    """
    url = f"{BASES_PRODUCAO.sefin}/nfse"
    httpx_mock.add_response(url=url, method="POST", json=_resposta_ok())

    assert dps.ambiente is Ambiente.PRODUCAO_RESTRITA

    with caplog.at_level(logging.WARNING, logger="nfse_sefin"):
        _cliente(certificado, ambiente=Ambiente.PRODUCAO).emitir(dps)

    import json

    (requisicao,) = httpx_mock.get_requests()
    xml = de_gzip_b64(json.loads(requisicao.read())[CAMPO_DPS])
    assert b"<tpAmb>1</tpAmb>" in xml

    assert "tpAmb sobrescrito" in caplog.text
    assert ID_DPS in caplog.text


def test_ambiente_coincidente_nao_avisa(
    cliente: NFSeClient, dps: DPS, httpx_mock: HTTPXMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Aviso em toda emissão treinaria o usuário a ignorá-lo."""
    httpx_mock.add_response(url=URL_EMITIR, method="POST", json=_resposta_ok())

    with caplog.at_level(logging.WARNING, logger="nfse_sefin"):
        cliente.emitir(dps)

    assert "tpAmb sobrescrito" not in caplog.text


def test_dps_original_nao_e_modificada(
    certificado: Certificate, dps: DPS, httpx_mock: HTTPXMock
) -> None:
    """A DPS do chamador é dele. Sobrescrever `tpAmb` produz uma cópia."""
    httpx_mock.add_response(url=f"{BASES_PRODUCAO.sefin}/nfse", method="POST", json=_resposta_ok())

    _cliente(certificado, ambiente=Ambiente.PRODUCAO).emitir(dps)

    assert dps.ambiente is Ambiente.PRODUCAO_RESTRITA


# ------------------------------------------------------------------ consultar


def test_consultar_por_chave(cliente: NFSeClient, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=URL_CONSULTA, method="GET", json=_resposta_ok())

    nota = cliente.consultar(CHAVE)

    assert nota.chave_acesso == CHAVE
    assert nota.xml == NFSE_XML


def test_consultar_aceita_a_chave_com_nfs(cliente: NFSeClient, httpx_mock: HTTPXMock) -> None:
    """A URL leva os 50 dígitos, mesmo quando o chamador passou as 53 posições."""
    httpx_mock.add_response(url=URL_CONSULTA, method="GET", json=_resposta_ok())

    cliente.consultar(f"NFS{CHAVE}")

    (requisicao,) = httpx_mock.get_requests()
    assert str(requisicao.url) == URL_CONSULTA


def test_consultar_recusa_chave_malformada_sem_ir_a_rede(
    cliente: NFSeClient, httpx_mock: HTTPXMock
) -> None:
    """P7: 50 dígitos é decidível offline, e a rodada custa mTLS."""
    with pytest.raises(DadosInvalidosError):
        cliente.consultar("123")
    assert not httpx_mock.get_requests()


def test_consultar_usa_a_chave_da_url_quando_o_corpo_omite(
    cliente: NFSeClient, httpx_mock: HTTPXMock
) -> None:
    """Consulta por chave sabe qual chave pediu; exigir que o corpo repita seria rigor
    inútil contra um contrato que já provou não ser estável."""
    httpx_mock.add_response(url=URL_CONSULTA, method="GET", json={CAMPO_NFSE: gzip_b64(NFSE_XML)})

    assert cliente.consultar(CHAVE).chave_acesso == CHAVE


# --------------------------------------------------------- recuperação por DPS


def test_head_dps_processada(cliente: NFSeClient, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=URL_DPS, method="HEAD", status_code=200)
    assert cliente.dps_foi_processada(ID_DPS) is True


def test_head_dps_nao_processada(cliente: NFSeClient, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=URL_DPS, method="HEAD", status_code=404)
    assert cliente.dps_foi_processada(ID_DPS) is False


def test_chave_por_dps(cliente: NFSeClient, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=URL_DPS, method="GET", json={"chaveAcesso": CHAVE})
    assert cliente.chave_por_dps(ID_DPS) == CHAVE


def test_chave_por_dps_sem_nota(cliente: NFSeClient, httpx_mock: HTTPXMock) -> None:
    """404 aqui é resposta legítima: a DPS não gerou nota."""
    httpx_mock.add_response(url=URL_DPS, method="GET", status_code=404, json={})
    assert cliente.chave_por_dps(ID_DPS) is None


def test_chave_por_dps_com_erro_que_nao_e_404(cliente: NFSeClient, httpx_mock: HTTPXMock) -> None:
    """500 sobe. `is_reusable` porque GET repete em 5xx — a recuperação é leitura."""
    httpx_mock.add_response(url=URL_DPS, method="GET", status_code=500, json={}, is_reusable=True)
    with pytest.raises(TransporteError):
        cliente.chave_por_dps(ID_DPS)


def test_chave_por_dps_sem_chave_no_corpo(cliente: NFSeClient, httpx_mock: HTTPXMock) -> None:
    """Sigilo fiscal omitiria a chave, mas com 404, não com 200 vazio."""
    httpx_mock.add_response(url=URL_DPS, method="GET", json={"algo": "outro"})
    with pytest.raises(RespostaInvalidaError, match="sem chave de acesso"):
        cliente.chave_por_dps(ID_DPS)


@pytest.mark.parametrize("entrada", ["", "DPS123", "1" * 45, f"XPS{'1' * 42}"])
def test_identificador_de_dps_malformado(
    cliente: NFSeClient, entrada: str, httpx_mock: HTTPXMock
) -> None:
    with pytest.raises(DadosInvalidosError, match="45 posições"):
        cliente.dps_foi_processada(entrada)
    assert not httpx_mock.get_requests()


def test_recuperacao_completa(cliente: NFSeClient, httpx_mock: HTTPXMock) -> None:
    """A sequência que a exceção de falha ambígua manda seguir, ponta a ponta."""
    httpx_mock.add_response(url=URL_DPS, method="HEAD", status_code=200)
    httpx_mock.add_response(url=URL_DPS, method="GET", json={"chaveAcesso": CHAVE})

    assert cliente.dps_foi_processada(ID_DPS)
    assert cliente.chave_por_dps(ID_DPS) == CHAVE


# --------------------------------------------------------------------- DANFSe


def test_danfse_vem_da_raiz_do_adn(cliente: NFSeClient, httpx_mock: HTTPXMock) -> None:
    """Não é na SEFIN, não é sob `/contribuintes`. É a raiz do ADN."""
    httpx_mock.add_response(url=URL_DANFSE, method="GET", content=b"%PDF-1.4 conteudo")

    pdf = cliente.baixar_danfse(CHAVE)

    assert pdf.startswith(b"%PDF")
    (requisicao,) = httpx_mock.get_requests()
    assert str(requisicao.url) == f"{BASES_RESTRITA.adn}/danfse/{CHAVE}"
    assert BASES_RESTRITA.sefin not in str(requisicao.url)
    assert "/contribuintes/" not in str(requisicao.url)


def test_danfse_recusa_chave_malformada(cliente: NFSeClient, httpx_mock: HTTPXMock) -> None:
    with pytest.raises(DadosInvalidosError):
        cliente.baixar_danfse("nao-e-chave")
    assert not httpx_mock.get_requests()


# -------------------------------------------------------------------- convênio


def test_convenio_pelo_cliente(cliente: NFSeClient, httpx_mock: HTTPXMock) -> None:
    """O passo zero continua acessível pelo mesmo objeto e pela base certa."""
    url = f"{BASES_RESTRITA.adn_parametrizacao}/{MUNICIPIO}/convenio"
    httpx_mock.add_response(url=url, method="GET", json={"aderente": True})

    convenio = cliente.consultar_convenio(MUNICIPIO)

    assert convenio.aderido
    assert convenio.caminho == url


# ---------------------------------------------------------------- ciclo de vida


def test_context_manager_fecha_o_transporte_proprio(certificado: Certificate) -> None:
    with NFSeClient(certificado) as cliente:
        transporte = cliente._transporte
    assert transporte._client.is_closed


def test_transporte_injetado_nao_e_fechado(certificado: Certificate) -> None:
    """Quem passou o transporte é dono dele — fechá-lo derrubaria outros clientes."""
    transporte = Transporte(certificate=certificado, client=httpx.Client())
    with NFSeClient(certificado, transporte=transporte):
        pass
    assert not transporte._client.is_closed
    transporte.close()


def test_bases_seguem_o_ambiente(certificado: Certificate) -> None:
    assert _cliente(certificado, ambiente=Ambiente.PRODUCAO).bases == BASES_PRODUCAO
    assert _cliente(certificado).bases == BASES_RESTRITA


# ---------------------------------------------------------------- NotaFiscal


def test_nota_e_imutavel() -> None:
    with pytest.raises(AttributeError):
        NotaFiscal(chave_acesso=CHAVE, xml=b"").chave_acesso = "x"  # type: ignore[misc]


def test_nota_guarda_o_corpo_cru(cliente: NFSeClient, httpx_mock: HTTPXMock) -> None:
    """P11: o contrato não é estável. Campo novo do servidor não pode exigir release."""
    httpx_mock.add_response(url=URL_CONSULTA, method="GET", json=_resposta_ok(campoNovo="valor"))

    assert cliente.consultar(CHAVE).dados["campoNovo"] == "valor"


def test_xml_da_nota_e_descomprimido(cliente: NFSeClient, httpx_mock: HTTPXMock) -> None:
    """Quem arquiva quer o XML, não o base64 de um gzip."""
    httpx_mock.add_response(url=URL_CONSULTA, method="GET", json=_resposta_ok())

    xml = cliente.consultar(CHAVE).xml

    assert xml == NFSE_XML
    assert not xml.startswith(gzip.compress(b"")[:2])

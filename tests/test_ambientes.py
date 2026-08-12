"""Trava as quatro URLs base.

Duas revisões deste design mandaram `POST /nfse` para o ADN, o que não emite nota
nenhuma, e uma delas colocou o DANFSe no SEFIN, que não devolve PDF nenhum. Nos dois
casos a falha é silenciosa em teste unitário: o código monta a URL, a chamada sai, e
só o servidor sabe que está errado.

Este arquivo é a rede. Ele não testa comportamento — ele fixa endereços e cruza os
papéis, para que trocar duas bases de lugar quebre aqui e não em produção.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from nfse_sefin.ambientes import BASES, Ambiente, Bases, bases_de

# As oito URLs, escritas à mão a partir do DESIGN.md. Duplicação deliberada: se o
# teste importasse a mesma constante que testa, não testaria nada.
ESPERADO = {
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


@pytest.mark.parametrize("ambiente", list(Ambiente))
def test_urls_base_sao_exatamente_estas(ambiente: Ambiente) -> None:
    assert bases_de(ambiente) == ESPERADO[ambiente]


def test_os_dois_ambientes_estao_declarados() -> None:
    assert set(BASES) == set(Ambiente) == {Ambiente.PRODUCAO, Ambiente.PRODUCAO_RESTRITA}


@pytest.mark.parametrize("ambiente", list(Ambiente))
def test_emissao_nunca_aponta_para_o_adn(ambiente: Ambiente) -> None:
    """O erro que a revisão 3 pegou: `POST /nfse` no ADN não emite nada."""
    host = urlparse(bases_de(ambiente).sefin).hostname
    assert host is not None
    assert host.startswith("sefin."), f"emissão saiu de sefin.*: {host}"
    assert not host.startswith("adn."), "emissão apontada para o ADN"


@pytest.mark.parametrize("ambiente", list(Ambiente))
def test_danfse_nunca_aponta_para_o_sefin(ambiente: Ambiente) -> None:
    """O erro que a revisão 3.1 pegou: o DANFSe fica na raiz do ADN."""
    host = urlparse(bases_de(ambiente).adn).hostname
    assert host is not None
    assert host.startswith("adn."), f"DANFSe saiu de adn.*: {host}"
    assert not host.startswith("sefin."), "DANFSe apontado para o SEFIN"


@pytest.mark.parametrize("ambiente", list(Ambiente))
def test_base_do_danfse_e_a_raiz_sem_prefixo(ambiente: Ambiente) -> None:
    """`GET {adn}/danfse/{chave}` — nem `/contribuintes`, nem `/parametrizacao`.

    Concatenar sobre a base errada devolve 404, e o dev vai procurar o erro na chave
    de acesso antes de desconfiar da URL.
    """
    assert urlparse(bases_de(ambiente).adn).path == ""


@pytest.mark.parametrize("ambiente", list(Ambiente))
def test_bases_do_adn_carregam_o_proprio_prefixo(ambiente: Ambiente) -> None:
    bases = bases_de(ambiente)
    assert urlparse(bases.adn_parametrizacao).path == "/parametrizacao"
    assert urlparse(bases.adn_contribuintes).path == "/contribuintes"
    assert urlparse(bases.sefin).path == "/SefinNacional"


@pytest.mark.parametrize("ambiente", list(Ambiente))
def test_as_quatro_bases_sao_distintas(ambiente: Ambiente) -> None:
    bases = bases_de(ambiente)
    urls = [bases.sefin, bases.adn, bases.adn_parametrizacao, bases.adn_contribuintes]
    assert len(set(urls)) == 4


@pytest.mark.parametrize("ambiente", list(Ambiente))
def test_tudo_https_e_sem_barra_no_fim(ambiente: Ambiente) -> None:
    """Barra no fim vira `//` na concatenação de rota, e nem todo servidor perdoa."""
    bases = bases_de(ambiente)
    for url in (bases.sefin, bases.adn, bases.adn_parametrizacao, bases.adn_contribuintes):
        assert url.startswith("https://"), url
        assert not url.endswith("/"), url


def test_producao_restrita_nao_encosta_em_producao() -> None:
    """Um teste de integração mal configurado não pode emitir nota de verdade."""
    restrita = bases_de(Ambiente.PRODUCAO_RESTRITA)
    for url in (
        restrita.sefin,
        restrita.adn,
        restrita.adn_parametrizacao,
        restrita.adn_contribuintes,
    ):
        host = urlparse(url).hostname
        assert host is not None
        assert "producaorestrita" in host, url

    producao = bases_de(Ambiente.PRODUCAO)
    for url in (
        producao.sefin,
        producao.adn,
        producao.adn_parametrizacao,
        producao.adn_contribuintes,
    ):
        assert "producaorestrita" not in url, url


def test_tp_amb_do_leiaute() -> None:
    """`infDPS/tpAmb`: 1 é produção, 2 é produção restrita."""
    assert Ambiente.PRODUCAO.tp_amb == "1"
    assert Ambiente.PRODUCAO_RESTRITA.tp_amb == "2"


def test_bases_sao_imutaveis() -> None:
    """Ninguém reaponta uma base em runtime — nem por engano, nem por conveniência."""
    with pytest.raises(AttributeError):
        bases_de(Ambiente.PRODUCAO).sefin = "https://exemplo.invalido"  # type: ignore[misc]

    with pytest.raises(TypeError):
        BASES[Ambiente.PRODUCAO] = ESPERADO[Ambiente.PRODUCAO]  # type: ignore[index]

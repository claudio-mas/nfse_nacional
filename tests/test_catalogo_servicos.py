"""Testes do catálogo da lista nacional de serviços.

O catálogo é gerado, e o gerador já falha o build quando o anexo sai da forma
esperada. O que estes testes cobrem é o que o gerador não pode cobrir sozinho: que o
arquivo versionado continua em sincronia com o anexo versionado, e que a API de
busca se comporta como o dev que não conhece o leiaute espera.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from nfse_sefin.catalogos import (
    SERVICOS,
    TOTAL_DE_SERVICOS,
    Servico,
    buscar_servico,
    por_codigo,
)

RAIZ = Path(__file__).resolve().parent.parent
ANEXO = RAIZ / "anexo_i-sefin_adn-dps_nfse-snnfse-v1-01-20260209.md"
GERADOR = RAIZ / "tools" / "gerar_catalogo_servicos.py"

# Contagem medida no anexo v1-01-20260209 por varredura exaustiva das linhas de
# tabela. O DESIGN.md dizia 341, herdado do plano original; o anexo tem 337.
TOTAL_ESPERADO = 337
COM_ZERO_A_ESQUERDA = 118


# ------------------------------------------------------------------ conteúdo


def test_total_de_servicos() -> None:
    assert TOTAL_DE_SERVICOS == TOTAL_ESPERADO
    assert len(SERVICOS) == TOTAL_ESPERADO


def test_todo_codigo_tem_seis_digitos() -> None:
    """O XSD fixa `[0-9]{6}` para `TSCodTribNac`. Sem exceção."""
    fora = [s.codigo for s in SERVICOS if not re.fullmatch(r"[0-9]{6}", s.codigo)]
    assert fora == []


def test_um_terco_da_lista_precisou_de_zfill() -> None:
    """OQ5: o Excel comeu o zero à esquerda de 118 dos 337 códigos.

    Se este número mudar, ou o anexo foi republicado ou o gerador parou de aplicar o
    `zfill`. As duas merecem investigação.
    """
    com_zero = [s.codigo for s in SERVICOS if s.codigo.startswith("0")]
    assert len(com_zero) == COM_ZERO_A_ESQUERDA


def test_nao_ha_codigo_duplicado() -> None:
    assert len({s.codigo for s in SERVICOS}) == TOTAL_DE_SERVICOS


def test_toda_descricao_tem_conteudo() -> None:
    assert all(s.descricao.strip() for s in SERVICOS)


def test_grupo_obrigatorio_so_tem_valores_conhecidos() -> None:
    assert {s.grupo_obrigatorio for s in SERVICOS} == {None, "obra", "atvEvento"}


def test_contagem_dos_grupos() -> None:
    assert sum(1 for s in SERVICOS if s.grupo_obrigatorio == "obra") == 13
    assert sum(1 for s in SERVICOS if s.grupo_obrigatorio == "atvEvento") == 19


@pytest.mark.parametrize(
    ("codigo", "trecho", "grupo"),
    [
        ("010101", "Análise e desenvolvimento de sistemas", None),
        ("070201", "obras de construção civil", "obra"),
        ("120101", "Espetáculos teatrais", "atvEvento"),
        ("990101", "sem a incidência de ISSQN e ICMS", None),
    ],
)
def test_entradas_conferidas_contra_o_anexo(codigo: str, trecho: str, grupo: str | None) -> None:
    servico = por_codigo(codigo)
    assert servico is not None
    assert trecho in servico.descricao
    assert servico.grupo_obrigatorio == grupo


# ------------------------------------------------------------- decomposição


def test_decomposicao_item_subitem_desdobro() -> None:
    """Regra de formação do XSD: 2 dígitos de item, 2 de subitem, 2 de desdobro."""
    servico = por_codigo("010101")
    assert servico is not None
    assert (servico.item, servico.subitem, servico.desdobro) == ("01", "01", "01")
    assert servico.rotulo_lc116 == "01.01.01"


def test_decomposicao_recompoe_o_codigo() -> None:
    for servico in SERVICOS:
        assert servico.item + servico.subitem + servico.desdobro == servico.codigo


# ------------------------------------------------------------- busca exata


def test_as_tres_notacoes_do_mesmo_servico() -> None:
    """O anexo usa três grafias para o mesmo código, e todas chegam ao dev.

    `010101` é a do leiaute, `10101` é a que saiu do Excel, e `01.01.01` é a que
    aparece em texto corrido no próprio anexo.
    """
    canonico = por_codigo("010101")
    assert canonico is not None
    assert por_codigo("10101") is canonico
    assert por_codigo("01.01.01") is canonico


def test_por_codigo_de_inexistente() -> None:
    assert por_codigo("000000") is None
    assert por_codigo("999999") is None


@pytest.mark.parametrize("entrada", ["", "   ", "abc", "..."])
def test_por_codigo_com_entrada_sem_digito(entrada: str) -> None:
    assert por_codigo(entrada) is None


# ------------------------------------------------------------- busca textual


def test_busca_por_texto() -> None:
    """O caso de uso real: o dev sabe o serviço, não o código."""
    resultados = buscar_servico("banho")
    assert [s.codigo for s in resultados] == ["060301"]


def test_busca_ignora_acento() -> None:
    """Ninguém digita `construção` com cedilha na hora de procurar."""
    com = buscar_servico("construção civil")
    sem = buscar_servico("construcao civil")
    assert com == sem
    assert len(sem) > 1


def test_busca_ignora_caixa() -> None:
    assert buscar_servico("VETERINÁRIA") == buscar_servico("veterinaria")


def test_busca_com_codigo_cai_na_exata() -> None:
    """Texto que parece código não deve varrer 337 descrições."""
    assert [s.codigo for s in buscar_servico("010101")] == ["010101"]
    assert [s.codigo for s in buscar_servico("01.01.01")] == ["010101"]


@pytest.mark.parametrize("entrada", ["", "   "])
def test_busca_vazia_devolve_vazio(entrada: str) -> None:
    assert buscar_servico(entrada) == ()


def test_busca_sem_resultado() -> None:
    assert buscar_servico("colonizacao de marte") == ()


def test_busca_devolve_tupla_imutavel() -> None:
    assert isinstance(buscar_servico("banho"), tuple)


# ------------------------------------------------------------------ contrato


def test_servico_e_imutavel() -> None:
    servico = SERVICOS[0]
    with pytest.raises(AttributeError):
        servico.codigo = "999999"  # type: ignore[misc]


def test_servicos_e_tupla() -> None:
    assert isinstance(SERVICOS, tuple)
    assert all(isinstance(s, Servico) for s in SERVICOS)


# ---------------------------------------------------- sincronia com o anexo


@pytest.mark.skipif(
    not ANEXO.exists() or not GERADOR.exists(),
    reason="anexo e gerador não vão no sdist; este teste só roda no repositório",
)
def test_catalogo_versionado_esta_em_sincronia_com_o_anexo() -> None:
    """Impede que alguém edite o catálogo à mão.

    Uma correção manual no arquivo gerado sumiria na próxima geração, em silêncio.
    Correção tem de entrar no gerador ou no anexo.
    """
    resultado = subprocess.run(
        [sys.executable, str(GERADOR), "--conferir"],
        capture_output=True,
        text=True,
        cwd=RAIZ,
    )
    assert resultado.returncode == 0, resultado.stderr or resultado.stdout

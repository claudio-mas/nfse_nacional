"""Testes do catálogo de rejeições e de `RejeicaoNFSe`.

Este catálogo é a terceira das três coisas que o `DESIGN.md` chama de razão de o
projeto existir: transformar `E0014` no texto oficial da regra e no caminho do campo
culpado, em vez de mandar o dev caçar num anexo de 373 KB exportado de Excel.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from nfse_sefin.catalogos.rejeicoes import (
    REJEICOES,
    TOTAL_DE_REJEICOES,
    Rejeicao,
    buscar_rejeicao,
    por_codigo,
)
from nfse_sefin.errors import MensagemSefin, NFSeError, RejeicaoNFSe

RAIZ = Path(__file__).resolve().parent.parent
ANEXO = RAIZ / "anexo_i-sefin_adn-dps_nfse-snnfse-v1-01-20260209.md"
GERADOR = RAIZ / "tools" / "gerar_catalogo_rejeicoes.py"

# Medidos por varredura exaustiva do anexo v1-01-20260209.
TOTAL_ESPERADO = 442
DA_DPS = 429
DE_RECEPCAO = 13
CODIGOS_DISTINTOS = 441


# ------------------------------------------------------------------ conteúdo


def test_total_de_rejeicoes() -> None:
    assert TOTAL_DE_REJEICOES == TOTAL_ESPERADO == len(REJEICOES)


def test_origem_das_duas_secoes() -> None:
    """656 linhas na tabela da DPS, mas só 429 carregam código."""
    assert sum(1 for r in REJEICOES if r.origem == "RN DPS_NFS-e") == DA_DPS
    assert sum(1 for r in REJEICOES if r.origem == "RN_RECEPCAO_DPS") == DE_RECEPCAO


def test_todo_codigo_tem_a_forma_do_anexo() -> None:
    assert all(re.fullmatch(r"E\d{4}", r.codigo) for r in REJEICOES)


def test_toda_rejeicao_tem_mensagem() -> None:
    """Sem mensagem o catálogo não serve para nada — é o texto que o dev lê."""
    assert all(r.mensagem.strip() for r in REJEICOES)


def test_forward_fill_cobriu_todas_as_regras_da_dps() -> None:
    """228 das 429 vinham com a célula de caminho vazia.

    O anexo só repete o caminho na primeira linha de cada grupo. Sem forward-fill,
    mais da metade do catálogo perderia a informação mais útil que ele tem.
    """
    da_dps = [r for r in REJEICOES if r.origem == "RN DPS_NFS-e"]
    assert all(r.caminho_xml for r in da_dps)


def test_regras_de_recepcao_nao_tem_caminho() -> None:
    """A tabela de recepção não tem essa coluna: ela rejeita antes de olhar conteúdo."""
    de_recepcao = [r for r in REJEICOES if r.origem == "RN_RECEPCAO_DPS"]
    assert de_recepcao
    assert all(r.caminho_xml is None and r.campo is None for r in de_recepcao)


def test_niveis_declarados_pelo_anexo() -> None:
    """1 leiaute, 2 regras gerais do SN, 3 legislação municipal."""
    niveis = {r.nivel for r in REJEICOES if r.origem == "RN DPS_NFS-e"}
    assert niveis <= {"1", "2", "3", None}


# ------------------------------------------------------------- busca por código


def test_e0014_e_o_caso_de_manchete() -> None:
    """O exemplo que o `DESIGN.md` usa: série+número+município+CNPJ repetidos."""
    (regra,) = por_codigo("E0014")

    assert "já existe em uma NFS-e" in regra.mensagem
    assert regra.caminho_xml == "NFSe/infNFSe/DPS/infDPS/"
    assert regra.campo == "serie"


def test_codigo_repetido_devolve_as_duas_regras() -> None:
    """`E1570` cobre duas regras diferentes, e é por isso que a API devolve tupla.

    O governo reusou o código: uma regra é sobre diferimento do IBS municipal, a
    outra sobre a CBS. Devolver só a primeira daria a explicação errada em metade
    dos casos.
    """
    regras = por_codigo("E1570")

    assert len(regras) == 2
    assert {r.campo for r in regras} == {"vDifMun", "vDifCBS"}
    assert len({r.mensagem for r in regras}) == 2


def test_um_unico_codigo_e_repetido() -> None:
    """Se aparecer outro, o anexo mudou e vale investigar antes de aceitar."""
    contagem: dict[str, int] = {}
    for rejeicao in REJEICOES:
        contagem[rejeicao.codigo] = contagem.get(rejeicao.codigo, 0) + 1

    assert len(contagem) == CODIGOS_DISTINTOS
    assert sorted(c for c, n in contagem.items() if n > 1) == ["E1570"]


@pytest.mark.parametrize("entrada", ["E1260", "1260", " e1260 ", "e1260"])
def test_por_codigo_tolera_a_forma_da_entrada(entrada: str) -> None:
    """O código chega da API, de log, ou digitado — todas as formas resolvem."""
    (regra,) = por_codigo(entrada)
    assert regra.codigo == "E1260"


def test_regra_de_recepcao_tambem_esta_no_catalogo() -> None:
    """As duas tabelas viram um catálogo só: quem recebe E1203 não sabe de tabelas."""
    (regra,) = por_codigo("E1203")
    assert regra.origem == "RN_RECEPCAO_DPS"
    assert "expirado" in regra.mensagem


@pytest.mark.parametrize("entrada", ["", "   ", "E9999", "nao-e-codigo"])
def test_codigo_desconhecido_devolve_vazio(entrada: str) -> None:
    assert por_codigo(entrada) == ()


# ------------------------------------------------------------- busca textual


def test_busca_por_trecho_da_mensagem() -> None:
    """Para quando a resposta vem sem campo de código, num dos formatos legados."""
    achadas = buscar_rejeicao("certificado de transmissão expirado")
    assert any(r.codigo == "E1203" for r in achadas)


def test_busca_ignora_acento_e_caixa() -> None:
    assert buscar_rejeicao("TRANSMISSÃO EXPIRADO") == buscar_rejeicao("transmissao expirado")


def test_busca_com_codigo_cai_na_exata() -> None:
    assert [r.codigo for r in buscar_rejeicao("E0014")] == ["E0014"]


@pytest.mark.parametrize("entrada", ["", "   "])
def test_busca_vazia(entrada: str) -> None:
    assert buscar_rejeicao(entrada) == ()


def test_rejeicao_e_imutavel() -> None:
    with pytest.raises(AttributeError):
        REJEICOES[0].codigo = "E0000"  # type: ignore[misc]


def test_str_mostra_codigo_mensagem_e_campo() -> None:
    (regra,) = por_codigo("E0014")
    texto = str(regra)
    assert texto.startswith("E0014: ")
    assert "serie" in texto


# ------------------------------------------------------------ RejeicaoNFSe


def test_excecao_traduz_o_codigo() -> None:
    """O ponto do catálogo inteiro: o dev lê a regra, não o código."""
    erro = RejeicaoNFSe([MensagemSefin("E0014", "duplicada")], status_code=400)

    assert "já existe em uma NFS-e" in str(erro)
    assert erro.codigos == ("E0014",)
    assert erro.caminhos_xml == ("NFSe/infNFSe/DPS/infDPS/serie",)
    assert erro.status_code == 400


def test_excecao_com_codigo_desconhecido_repete_o_servidor() -> None:
    """Anexo não conhece o código: melhor repetir o servidor que inventar sentido."""
    erro = RejeicaoNFSe([MensagemSefin("E9999", "algo novo")])

    assert erro.regras == ()
    assert "algo novo" in str(erro)


def test_excecao_com_varias_mensagens() -> None:
    erro = RejeicaoNFSe([MensagemSefin("E0014", ""), MensagemSefin("E1203", "")])

    assert erro.codigos == ("E0014", "E1203")
    assert len(erro.regras) == 2
    assert "|" in str(erro)


def test_excecao_sem_mensagem_nenhuma() -> None:
    erro = RejeicaoNFSe([])
    assert "sem informar código" in str(erro)


def test_excecao_expande_codigo_repetido() -> None:
    erro = RejeicaoNFSe([MensagemSefin("E1570", "")])
    assert len(erro.regras) == 2


def test_excecao_desce_de_nfse_error() -> None:
    with pytest.raises(NFSeError):
        raise RejeicaoNFSe([MensagemSefin("E0014", "")])


# ---------------------------------------------------- sincronia com o anexo


@pytest.mark.skipif(
    not ANEXO.exists() or not GERADOR.exists(),
    reason="anexo e gerador não vão no sdist; este teste só roda no repositório",
)
def test_catalogo_versionado_esta_em_sincronia_com_o_anexo() -> None:
    resultado = subprocess.run(
        [sys.executable, str(GERADOR), "--conferir"],
        capture_output=True,
        text=True,
        cwd=RAIZ,
    )
    assert resultado.returncode == 0, resultado.stderr or resultado.stdout


def test_tipo_exportado() -> None:
    assert all(isinstance(r, Rejeicao) for r in REJEICOES[:5])

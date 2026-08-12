#!/usr/bin/env python3
"""Gera `nfse_sefin/catalogos/rejeicoes.py` a partir do Anexo I.

Ferramenta de build, fora do pacote publicado. Uso igual ao gerador de serviços:

    python tools/gerar_catalogo_rejeicoes.py
    python tools/gerar_catalogo_rejeicoes.py --conferir

## As duas tabelas, e por que viram um catálogo só

O anexo separa as regras em duas seções com formatos diferentes:

- **`RN_RECEPCAO_DPS`** — 19 linhas, 13 com código. Valida certificado e envelope, antes
  de olhar o conteúdo. **Não tem coluna de caminho XML nenhuma**, e é por isso que
  `caminho_xml` é opcional.
- **`RN DPS_NFS-e`** — 656 linhas, 429 com código. Valida o conteúdo da DPS, campo a
  campo.

Quem recebe `E1203` não quer saber em qual tabela do anexo a regra mora. As duas viram
um catálogo, com `origem` registrando de onde cada uma veio.

## Três armadilhas na extração

**Só 429 das 656 linhas carregam código.** As outras são cabeçalho de grupo, com `-` nas
colunas de erro. Usar as 656 produziria ~227 entradas vazias.

**228 das 429 têm a célula de caminho vazia**, porque o anexo só repete o caminho na
primeira linha de cada grupo. Sem forward-fill, mais da metade do catálogo perde a
informação mais útil que ele tem. O mesmo vale para a coluna de campo, com 229 vazias.

**Um código aparece duas vezes.** `E1570` cobre duas regras distintas — diferimento do
IBS municipal (regra 108) e da CBS (regra 116), com campos e mensagens diferentes. É
reuso do governo, não erro de conversão, e é a razão de `por_codigo` devolver tupla em
vez de um item só.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ANEXO = RAIZ / "anexo_i-sefin_adn-dps_nfse-snnfse-v1-01-20260209.md"
DESTINO = RAIZ / "nfse_sefin" / "catalogos" / "rejeicoes.py"

CODIGO = re.compile(r"E\d{4}")


@dataclass(frozen=True)
class Linha:
    codigo: str
    mensagem: str
    regra: str
    caminho_xml: str | None
    campo: str | None
    nivel: str | None
    origem: str


def _celulas(linha: str) -> list[str]:
    return [c.strip() for c in linha.strip().strip("|").split("|")]


def _limpar(valor: str) -> str:
    """Colapsa espaço e trata o traço do anexo como ausência."""
    texto = " ".join(valor.split())
    return "" if texto == "-" else texto


def _secao(linhas: list[str], titulo: str) -> list[list[str]]:
    inicio = next(i for i, linha in enumerate(linhas) if linha.startswith(f"## {titulo}"))
    fim = next(
        (i for i, linha in enumerate(linhas[inicio + 1 :], inicio + 1) if linha.startswith("## ")),
        len(linhas),
    )
    return [_celulas(linha) for linha in linhas[inicio:fim] if linha.startswith("|")]


def extrair_recepcao(linhas: list[str]) -> list[Linha]:
    """`RN_RECEPCAO_DPS`: 8 colunas, sem caminho XML."""
    achadas: list[Linha] = []
    for celulas in _secao(linhas, "RN_RECEPCAO_DPS"):
        if len(celulas) != 8 or not CODIGO.fullmatch(celulas[5]):
            continue
        achadas.append(
            Linha(
                codigo=celulas[5],
                mensagem=_limpar(celulas[6]),
                regra=_limpar(celulas[1]),
                caminho_xml=None,  # a tabela não tem essa coluna
                campo=None,
                nivel=None,
                origem="RN_RECEPCAO_DPS",
            )
        )
    return achadas


def extrair_dps(linhas: list[str]) -> list[Linha]:
    """`RN DPS_NFS-e`: 15 colunas, com forward-fill de caminho e campo."""
    achadas: list[Linha] = []
    caminho_corrente = ""
    campo_corrente = ""

    for celulas in _secao(linhas, "RN DPS_NFS-e"):
        if len(celulas) != 15:
            continue

        # O forward-fill acompanha **todas** as linhas, não só as que têm código: o
        # cabeçalho de grupo é justamente quem carrega o caminho que as seguintes herdam.
        if _limpar(celulas[1]):
            caminho_corrente = _limpar(celulas[1])
        if _limpar(celulas[2]):
            campo_corrente = _limpar(celulas[2])

        if not CODIGO.fullmatch(celulas[7]):
            continue

        achadas.append(
            Linha(
                codigo=celulas[7],
                mensagem=_limpar(celulas[8]),
                regra=_limpar(celulas[3]),
                caminho_xml=caminho_corrente or None,
                campo=campo_corrente or None,
                nivel=_limpar(celulas[9]) or None,
                origem="RN DPS_NFS-e",
            )
        )
    return achadas


def validar(linhas: list[Linha]) -> None:
    if not linhas:
        raise SystemExit("Nenhuma regra extraída: o anexo mudou de forma.")

    sem_codigo = [linha for linha in linhas if not CODIGO.fullmatch(linha.codigo)]
    if sem_codigo:
        raise SystemExit(f"Código fora do padrão E####: {[x.codigo for x in sem_codigo][:5]}")

    sem_mensagem = [linha.codigo for linha in linhas if not linha.mensagem]
    if sem_mensagem:
        raise SystemExit(f"Regras sem mensagem de erro: {sem_mensagem[:10]}")

    da_dps = [linha for linha in linhas if linha.origem == "RN DPS_NFS-e"]
    sem_caminho = [linha.codigo for linha in da_dps if not linha.caminho_xml]
    if sem_caminho:
        raise SystemExit(
            f"{len(sem_caminho)} regras da DPS sem caminho após forward-fill: {sem_caminho[:5]}"
        )


def gerar(linhas: list[Linha]) -> str:
    corpo = "\n".join(
        "    _R("
        f"{linha.codigo!r}, {linha.mensagem!r}, {linha.regra!r}, "
        f"{linha.caminho_xml!r}, {linha.campo!r}, {linha.nivel!r}, {linha.origem!r}),"
        for linha in linhas
    )
    contagem = Counter(linha.codigo for linha in linhas)
    distintos = len(contagem)
    duplicados = sorted(codigo for codigo, n in contagem.items() if n > 1)
    return _MOLDE.format(
        total=len(linhas),
        distintos=distintos,
        distintos_menos_um=distintos - 1,
        duplicados=", ".join(duplicados) or "nenhum",
        corpo=corpo,
        anexo=ANEXO.name,
    )


_MOLDE = '''"""Catálogo de rejeições da SEFIN: código `E####` → o que o anexo diz.

ARQUIVO GERADO. Não edite à mão — rode `python tools/gerar_catalogo_rejeicoes.py`.
Fonte: seções `RN_RECEPCAO_DPS` e `RN DPS_NFS-e` de `{anexo}`.

São {total} regras, {distintos} códigos distintos. Sem este catálogo, a SEFIN devolve
`E0014` e o dev vai caçar o significado num anexo de 373 KB exportado de Excel.

Código repetido no anexo: {duplicados}. É reuso do próprio governo — a mesma sigla
cobre regras diferentes, com campos e mensagens diferentes — e é por isso que
`por_codigo` devolve **tupla**, não um item.

`caminho_xml` e `campo` são `None` só para as regras de `RN_RECEPCAO_DPS`, cuja tabela
não tem essas colunas: elas validam certificado e envelope antes de o conteúdo ser
olhado. Para as regras da DPS, o caminho vem preenchido por forward-fill, porque o anexo
só o repete na primeira linha de cada grupo.

`efeito` não é capturado: 8 das 429 linhas trazem ruído nessa coluna no anexo original
(três dizem `Obrig.` onde deveriam dizer `Rej.`, cinco estão vazias), e um campo em que
não se pode confiar é pior que nenhum.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = [
    "Rejeicao",
    "REJEICOES",
    "TOTAL_DE_REJEICOES",
    "por_codigo",
    "buscar_rejeicao",
]


@dataclass(frozen=True, slots=True)
class Rejeicao:
    """Uma regra de negócio da SEFIN, com o código que ela devolve."""

    codigo: str
    """`E####`, como vem na resposta da API."""

    mensagem: str
    """Texto oficial da mensagem de erro, literal do anexo."""

    regra: str
    """A regra de negócio por extenso. Explica o **porquê**, não só o quê."""

    caminho_xml: str | None
    """Caminho do campo culpado no XML, quando o anexo fornece.

    `None` para as regras de recepção, que rejeitam antes de olhar o conteúdo.
    """

    campo: str | None
    """Nome do campo no leiaute, quando aplicável."""

    nivel: str | None
    """`1` leiaute, `2` regras gerais do Sistema Nacional, `3` legislação municipal."""

    origem: str
    """Seção do anexo de onde a regra veio."""

    def __str__(self) -> str:
        onde = f" ({{self.caminho_xml}}{{self.campo or ''}})" if self.caminho_xml else ""
        return f"{{self.codigo}}: {{self.mensagem}}{{onde}}"


_R = Rejeicao

REJEICOES: tuple[Rejeicao, ...] = (
{corpo}
)

TOTAL_DE_REJEICOES = len(REJEICOES)

# Asserção de build, não de teste.
assert TOTAL_DE_REJEICOES == {total}, f"catálogo com {{TOTAL_DE_REJEICOES}}, esperado {total}"
assert all(re.fullmatch(r"E\\d{{4}}", r.codigo) for r in REJEICOES), "código fora de E####"
assert all(r.mensagem for r in REJEICOES), "rejeição sem mensagem"


def _indexar() -> dict[str, tuple[Rejeicao, ...]]:
    indice: dict[str, list[Rejeicao]] = {{}}
    for rejeicao in REJEICOES:
        indice.setdefault(rejeicao.codigo, []).append(rejeicao)
    return {{codigo: tuple(itens) for codigo, itens in indice.items()}}


_POR_CODIGO = _indexar()


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


_BUSCAVEL: tuple[tuple[str, Rejeicao], ...] = tuple(
    (_normalizar(f"{{r.mensagem}} {{r.regra}}"), r) for r in REJEICOES
)


def por_codigo(codigo: str) -> tuple[Rejeicao, ...]:
    """Todas as regras que a SEFIN identifica com este código.

    Devolve tupla porque o anexo reusa pelo menos um código para duas regras
    distintas. Para {distintos_menos_um} dos {distintos} códigos é uma tupla de um
    elemento; ignorar o caso restante daria a explicação errada ao usuário.

    Aceita `E1260` e `1260`, com ou sem espaço em volta.
    """
    limpo = codigo.strip().upper()
    if limpo and not limpo.startswith("E") and limpo.isdigit():
        limpo = f"E{{limpo}}"
    return _POR_CODIGO.get(limpo, ())


def buscar_rejeicao(texto: str) -> tuple[Rejeicao, ...]:
    """Procura por trecho da mensagem ou da regra, ignorando acento e caixa.

    Para quem tem o texto do erro mas não o código — que é o que aparece quando a
    resposta vem num dos formatos legados, sem campo de código.
    """
    if not texto or not texto.strip():
        return ()
    if re.fullmatch(r"[Ee]?\\d{{1,4}}", texto.strip()):
        return por_codigo(texto)
    alvo = _normalizar(texto)
    return tuple(rejeicao for conteudo, rejeicao in _BUSCAVEL if alvo in conteudo)
'''


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--conferir", action="store_true", help="não escreve; 1 se divergir")
    argumentos = analisador.parse_args()

    linhas = ANEXO.read_text(encoding="utf-8").split("\n")
    regras = extrair_recepcao(linhas) + extrair_dps(linhas)
    validar(regras)

    distintos = len({regra.codigo for regra in regras})
    conteudo = gerar(regras)

    if argumentos.conferir:
        atual = DESTINO.read_text(encoding="utf-8") if DESTINO.exists() else ""
        if atual != conteudo:
            print(
                f"{DESTINO.relative_to(RAIZ)} está fora de sincronia com {ANEXO.name}.\n"
                "Rode: python tools/gerar_catalogo_rejeicoes.py",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {len(regras)} rejeições, catálogo em sincronia.")
        return 0

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(conteudo, encoding="utf-8")
    da_dps = sum(1 for r in regras if r.origem == "RN DPS_NFS-e")
    print(
        f"{DESTINO.relative_to(RAIZ)}: {len(regras)} rejeições "
        f"({da_dps} da DPS, {len(regras) - da_dps} de recepção), {distintos} códigos distintos."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Gera `nfse_sefin/catalogos/servicos.py` a partir do Anexo I.

Este script é ferramenta de build, não faz parte do pacote publicado. O módulo que
ele gera carrega os dados embutidos, porque o Anexo I não vai na wheel e a
biblioteca não pode depender de ler um markdown de 373 KB em runtime.

Uso:
    python tools/gerar_catalogo_servicos.py
    python tools/gerar_catalogo_servicos.py --conferir   # não escreve; falha se divergir

O `--conferir` existe para o CI: ele prova que o módulo versionado é exatamente o
que este gerador produz a partir do anexo versionado, o que impede alguém editar o
catálogo à mão e a edição sumir na próxima geração.

## A pegadinha dos zeros à esquerda (OQ5)

A tabela `MUN.INCID_INFO.SERV.` foi exportada de Excel, que trata a primeira coluna
como número e come o zero da frente. O anexo diz `10101`; o `cTribNac` real é
`010101`. São 118 dos 337 códigos — mais de um terço. O XSD é a autoridade:

    <xs:simpleType name="TSCodTribNac">
      <xs:pattern value="[0-9]{6}"/>

com regra de formação de 2 dígitos para item, 2 para subitem e 2 para desdobro
nacional. Daí o `zfill(6)`, e daí a asserção de que nenhum código sobrevive com
comprimento diferente de 6.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ANEXO = RAIZ / "anexo_i-sefin_adn-dps_nfse-snnfse-v1-01-20260209.md"
DESTINO = RAIZ / "nfse_sefin" / "catalogos" / "servicos.py"

SECAO = "MUN.INCID_INFO.SERV."

COLUNA_CODIGO = 0
COLUNA_DESCRICAO = 1
COLUNA_GRUPO = 6

GRUPOS_CONHECIDOS = {"obra", "atvEvento"}


@dataclass(frozen=True)
class Linha:
    codigo: str
    descricao: str
    grupo: str | None


def extrair(markdown: str) -> list[Linha]:
    """Lê as linhas de dado da seção da lista nacional de serviços.

    Uma linha é dado quando a primeira célula é só dígitos. As seis linhas de
    cabeçalho do anexo têm célula de texto ou vazia, então essa regra sozinha já
    separa cabeçalho de conteúdo sem precisar contar linhas.
    """
    linhas = markdown.split("\n")
    inicio = next(i for i, linha in enumerate(linhas) if linha.startswith(f"## {SECAO}"))
    fim = next(
        (i for i, linha in enumerate(linhas[inicio + 1 :], inicio + 1) if linha.startswith("## ")),
        len(linhas),
    )

    achadas: list[Linha] = []
    for linha in linhas[inicio:fim]:
        if not linha.startswith("|"):
            continue
        celulas = [c.strip() for c in linha.strip().strip("|").split("|")]
        if len(celulas) <= COLUNA_GRUPO:
            continue
        if not re.fullmatch(r"\d+", celulas[COLUNA_CODIGO]):
            continue

        grupo = celulas[COLUNA_GRUPO]
        achadas.append(
            Linha(
                codigo=celulas[COLUNA_CODIGO].zfill(6),
                descricao=" ".join(celulas[COLUNA_DESCRICAO].split()),
                grupo=grupo if grupo in GRUPOS_CONHECIDOS else None,
            )
        )
    return achadas


def validar(linhas: list[Linha]) -> None:
    """Falha o build, não o teste, quando o anexo sai da forma esperada."""
    if not linhas:
        raise SystemExit("Nenhuma linha extraída: a seção mudou de forma.")

    fora_do_padrao = [linha.codigo for linha in linhas if not re.fullmatch(r"\d{6}", linha.codigo)]
    if fora_do_padrao:
        raise SystemExit(f"Códigos fora de [0-9]{{6}} após zfill: {fora_do_padrao[:10]}")

    vistos: dict[str, int] = {}
    for linha in linhas:
        vistos[linha.codigo] = vistos.get(linha.codigo, 0) + 1
    duplicados = sorted(codigo for codigo, n in vistos.items() if n > 1)
    if duplicados:
        raise SystemExit(f"Códigos duplicados após zfill: {duplicados}")

    sem_descricao = [linha.codigo for linha in linhas if not linha.descricao]
    if sem_descricao:
        raise SystemExit(f"Serviços sem descrição: {sem_descricao}")


def gerar(linhas: list[Linha]) -> str:
    corpo = "\n".join(
        f"    _S({linha.codigo!r}, {linha.descricao!r}, {linha.grupo!r})," for linha in linhas
    )
    total = len(linhas)
    com_zfill = sum(1 for linha in linhas if linha.codigo.startswith("0"))
    return _MOLDE.format(total=total, com_zfill=com_zfill, corpo=corpo, anexo=ANEXO.name)


_MOLDE = '''"""Lista nacional de serviços da LC 116/2003, com o código de tributação nacional.

ARQUIVO GERADO. Não edite à mão — rode `python tools/gerar_catalogo_servicos.py`.
Fonte: seção `MUN.INCID_INFO.SERV.` de `{anexo}`.

São {total} subitens. **{com_zfill} deles precisaram de `zfill(6)`**: a tabela do anexo
saiu de um Excel que tratou a coluna de código como número e comeu o zero à esquerda,
então o anexo diz `10101` onde o `cTribNac` real é `010101`. O XSD é a autoridade e fixa
`[0-9]{{6}}`, com 2 dígitos de item, 2 de subitem e 2 de desdobro nacional.

Colunas de localidade de incidência (EP/LP/ET/EDEmit) não são capturadas: o significado
delas depende de notas de rodapé do anexo que este gerador não interpreta, e um mapeamento
errado seria pior que a ausência. A coluna de grupo obrigatório é capturada porque é
inequívoca — `obra` ou `atvEvento`, e nada mais.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = ["Servico", "SERVICOS", "por_codigo", "buscar_servico", "TOTAL_DE_SERVICOS"]


@dataclass(frozen=True, slots=True)
class Servico:
    """Um subitem da lista nacional."""

    codigo: str
    """`cTribNac`: exatamente 6 dígitos."""

    descricao: str
    """Texto do desdobro nacional, como no anexo."""

    grupo_obrigatorio: str | None
    """Grupo que a DPS precisa trazer para este serviço: `obra`, `atvEvento`, ou nada."""

    @property
    def item(self) -> str:
        """Item da LC 116/2003 — os 2 primeiros dígitos."""
        return self.codigo[:2]

    @property
    def subitem(self) -> str:
        """Subitem da LC 116/2003 — dígitos 3 e 4."""
        return self.codigo[2:4]

    @property
    def desdobro(self) -> str:
        """Desdobro nacional — dígitos 5 e 6."""
        return self.codigo[4:]

    @property
    def rotulo_lc116(self) -> str:
        """A notação que aparece em texto corrido: `01.01.01`."""
        return f"{{self.item}}.{{self.subitem}}.{{self.desdobro}}"


_S = Servico

SERVICOS: tuple[Servico, ...] = (
{corpo}
)

TOTAL_DE_SERVICOS = len(SERVICOS)

# Asserção de build, não de teste. Roda no import: um catálogo gerado torto derruba
# a biblioteca na hora em vez de deixar um `cTribNac` de 5 dígitos chegar à SEFIN e
# voltar rejeitado.
assert (
    TOTAL_DE_SERVICOS == {total}
), f"catálogo com {{TOTAL_DE_SERVICOS}} entradas, esperado {total}"
assert all(re.fullmatch(r"[0-9]{{6}}", s.codigo) for s in SERVICOS), "código fora de [0-9]{{6}}"
assert len({{s.codigo for s in SERVICOS}}) == TOTAL_DE_SERVICOS, "código duplicado no catálogo"

_POR_CODIGO: dict[str, Servico] = {{s.codigo: s for s in SERVICOS}}


def _normalizar(texto: str) -> str:
    """Minúsculas, sem acento, espaços colapsados — para busca tolerante."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


_BUSCAVEL: tuple[tuple[str, Servico], ...] = tuple(
    (_normalizar(s.descricao), s) for s in SERVICOS
)


def por_codigo(codigo: str) -> Servico | None:
    """Busca exata por `cTribNac`.

    Aceita as três notações que o anexo usa para a mesma coisa: `010101`, `10101`
    (sem o zero à esquerda, como saiu do Excel) e `01.01.01` (texto corrido).
    """
    limpo = re.sub(r"\\D", "", codigo)
    if not limpo:
        return None
    return _POR_CODIGO.get(limpo.zfill(6))


# Palavras curtas demais ou vazias de sentido para pesar numa busca. Sem isto,
# "banho e tosa" casaria com toda descrição que contenha "e".
_IRRELEVANTES = frozenset(
    {{"de", "da", "do", "das", "dos", "e", "ou", "em", "no", "na", "com", "por", "para"}}
)


def _termos(texto: str) -> list[str]:
    return [p for p in _normalizar(texto).split() if len(p) >= 3 and p not in _IRRELEVANTES]


def buscar_servico(texto: str) -> tuple[Servico, ...]:
    """Procura serviços por descrição, ignorando acento e caixa.

    Existe para o dev que sabe que vende "banho e tosa" e não faz ideia de que a
    lista nacional chama isso de `060301`. Um texto que pareça código cai na busca
    exata por `cTribNac`.

    A procura tem três degraus, do mais específico ao mais tolerante, e para no
    primeiro que devolver alguma coisa:

    1. a frase inteira como substring da descrição;
    2. descrições que contenham **todos** os termos, em qualquer ordem;
    3. descrições que contenham **algum** termo, ordenadas por quantos casaram.

    O degrau 3 é o que faz "banho e tosa" encontrar `060301`: a lista nacional não
    tem a palavra "tosa" em lugar nenhum, e uma busca só por substring devolveria
    vazio para a consulta mais óbvia que este catálogo deveria atender.
    """
    if not texto or not texto.strip():
        return ()

    exato = por_codigo(texto) if re.fullmatch(r"[\\d.]+", texto.strip()) else None
    if exato is not None:
        return (exato,)

    alvo = _normalizar(texto)
    frase = tuple(servico for descricao, servico in _BUSCAVEL if alvo in descricao)
    if frase:
        return frase

    termos = _termos(texto)
    if not termos:
        return ()

    todos = tuple(
        servico
        for descricao, servico in _BUSCAVEL
        if all(termo in descricao for termo in termos)
    )
    if todos:
        return todos

    algum = [
        (sum(termo in descricao for termo in termos), servico)
        for descricao, servico in _BUSCAVEL
        if any(termo in descricao for termo in termos)
    ]
    algum.sort(key=lambda par: (-par[0], par[1].codigo))
    return tuple(servico for _, servico in algum)
'''


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument(
        "--conferir",
        action="store_true",
        help="não escreve; sai com 1 se o arquivo versionado divergir",
    )
    argumentos = analisador.parse_args()

    linhas = extrair(ANEXO.read_text(encoding="utf-8"))
    validar(linhas)
    conteudo = gerar(linhas)

    if argumentos.conferir:
        atual = DESTINO.read_text(encoding="utf-8") if DESTINO.exists() else ""
        if atual != conteudo:
            print(
                f"{DESTINO.relative_to(RAIZ)} está fora de sincronia com {ANEXO.name}.\n"
                "Rode: python tools/gerar_catalogo_servicos.py",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {len(linhas)} serviços, catálogo em sincronia.")
        return 0

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(conteudo, encoding="utf-8")
    com_zfill = sum(1 for linha in linhas if linha.codigo.startswith("0"))
    print(f"{DESTINO.relative_to(RAIZ)}: {len(linhas)} serviços, {com_zfill} com zfill(6).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

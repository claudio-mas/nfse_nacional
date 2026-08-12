"""O eixo de compatibilidade: versão de leiaute e algoritmo de assinatura.

Este módulo existe porque **ninguém sabe qual combinação a SEFIN aceita hoje**, e a
documentação não decide.

As duas bibliotecas que existem para esta API escolheram combinações **opostas**, e as
duas afirmam funcionar em produção:

| | `brans-nfe` 0.2.0 | `pynfse-nacional` 0.9.5 |
|---|---|---|
| `DPS versao=` | 1.00 | 1.01 |
| assinatura | rsa-sha1 / sha1 | rsa-sha256 / sha256 |
| `pedRegEvento versao=` | 1.01 | 1.00 |

Cruzadas nos dois eixos. Só há três leituras: o servidor aceita ambos, uma das duas está
quebrada e ninguém notou, ou a aceitação mudou no tempo. Nenhuma é decidível de mesa —
nada responde sem certificado cliente, nem o Swagger de produção restrita.

A resposta deste projeto é não apostar. O perfil é um parâmetro, `signing.py` varia só o
hash, e o `doctor` descobre empiricamente qual passa.

## Por que a forma da assinatura é sempre a estrita

O `xmldsig-core-schema.xsd` **difere entre as duas versões** do ZIP oficial. A 1.00 traz
uma variante restrita do governo que fixa `rsa-sha1`, `sha1`, C14N
`REC-xml-c14n-20010315`, exatamente dois transforms e `KeyInfo` obrigatório. A 1.01 volta
ao W3C genérico, sem restrição nenhuma.

Daí a regra: **construir sempre na forma estrita da 1.00 valida sob os dois schemas.** Só
o par de hash é irreconciliável, e é por isso que ele — e só ele — é parametrizado.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

__all__ = [
    "Perfil",
    "PERFIL_100",
    "PERFIL_101",
    "PERFIS",
    "PERFIL_PADRAO",
    "por_nome",
    "NS_XMLDSIG",
    "ALG_C14N",
    "ALG_ENVELOPED",
]

NS_XMLDSIG = "http://www.w3.org/2000/09/xmldsig#"

ALG_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
"""Canonicalização. A 1.00 fixa exatamente esta; a 1.01 aceita."""

ALG_ENVELOPED = f"{NS_XMLDSIG}enveloped-signature"
"""Primeiro dos dois transforms. A 1.00 exige `minOccurs=2 maxOccurs=2`."""

_ALG_RSA_SHA1 = f"{NS_XMLDSIG}rsa-sha1"
_ALG_SHA1 = f"{NS_XMLDSIG}sha1"
_ALG_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
_ALG_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"


@dataclass(frozen=True, slots=True)
class Perfil:
    """Uma combinação de versão de leiaute e par de algoritmos.

    O que varia entre perfis é **só** isto. Namespace, canonicalização, número de
    transforms e presença de `KeyInfo` são iguais nos dois, porque a forma estrita
    da 1.00 é aceita pelos dois schemas.
    """

    nome: str
    """Rótulo curto para log e para a saída do `doctor`: `1.00+SHA1`."""

    versao: str
    """Valor do atributo `versao` da DPS: `"1.00"` ou `"1.01"`."""

    algoritmo_assinatura: str
    """URI do `SignatureMethod`."""

    algoritmo_digest: str
    """URI do `DigestMethod`."""

    hash_hashlib: str
    """Nome do algoritmo em `hashlib` e em `cryptography`: `sha1` ou `sha256`."""

    def __str__(self) -> str:
        return self.nome


PERFIL_100 = Perfil(
    nome="1.00+SHA1",
    versao="1.00",
    algoritmo_assinatura=_ALG_RSA_SHA1,
    algoritmo_digest=_ALG_SHA1,
    hash_hashlib="sha1",
)
"""Leiaute 1.00 com SHA-1, que é o que o XSD 1.00 fixa.

SHA-1 numa biblioteca nova em 2026 é escolha difícil de defender por si. A defesa é que
o schema oficial da 1.00 **fixa** `rsa-sha1` com `fixed=`, então emitir outra coisa sob
`versao="1.00"` é inválido pelo próprio documento do governo. Quem quiser SHA-256 usa o
`PERFIL_101`.
"""

PERFIL_101 = Perfil(
    nome="1.01+SHA256",
    versao="1.01",
    algoritmo_assinatura=_ALG_RSA_SHA256,
    algoritmo_digest=_ALG_SHA256,
    hash_hashlib="sha256",
)
"""Leiaute 1.01 com SHA-256, permitido pelo schema genérico da 1.01."""

PERFIS: tuple[Perfil, ...] = (PERFIL_100, PERFIL_101)

PERFIL_PADRAO = PERFIL_100
"""Enquanto o probe não roda contra um certificado real, o padrão é o par que uma
implementação MIT usa em produção hoje (`brans-nfe`).

Não é uma afirmação de que o outro não funciona — é a escolha com evidência mais
próxima. `nfse-doctor --probe-assinatura` existe para substituir isto por um fato.
"""

_POR_NOME: Mapping[str, Perfil] = MappingProxyType({p.nome: p for p in PERFIS})


def por_nome(nome: str) -> Perfil:
    """Perfil pelo rótulo (`1.00+SHA1`) ou pela versão nua (`1.00`)."""
    if nome in _POR_NOME:
        return _POR_NOME[nome]
    for perfil in PERFIS:
        if perfil.versao == nome:
            return perfil
    conhecidos = ", ".join(p.nome for p in PERFIS)
    raise ValueError(f"Perfil desconhecido: {nome!r}. Conhecidos: {conhecidos}.")

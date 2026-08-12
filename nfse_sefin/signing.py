"""Assinatura XMLDSIG enveloped da DPS, montada à mão.

Sem `signxml`, e a razão é concreta: sob o esquema 1.00 o XSD **fixa** `rsa-sha1`, e o
`signxml` atual recusa RSA-SHA1 por padrão nos dois sentidos, exigindo opt-in explícito.
Como esta biblioteca precisa emitir os dois perfis, montar `SignedInfo` com `lxml` +
`cryptography` cobre ambos com um caminho de código só e sem brigar com o default de uma
dependência.

## A forma é sempre a estrita

Exatamente dois transforms, `KeyInfo` presente, C14N `REC-xml-c14n-20010315`. É o que o
XSD 1.00 exige com `fixed=` e `minOccurs=2 maxOccurs=2`, e é aceito pelo XSD 1.01, que é
o W3C genérico. Só o par de hash varia, e vem do perfil.

## O byte assinado é o byte enviado

`assinar` devolve os bytes finais. Nada re-serializa a árvore depois de assinada: qualquer
reserialização pode reordenar declaração de namespace ou mudar espaço em branco, o digest
deixa de bater, e a SEFIN rejeita com uma mensagem que não diz que o problema foi esse.

## Sem prefixo de namespace

`RN_RECEPCAO_DPS` #14 rejeita com **E1228** qualquer prefixo na área de dados. A
`Signature` mora no namespace do XMLDSIG, que é diferente do namespace da DPS, então ela
declara o próprio como **default** em vez de usar `ds:`.
"""

from __future__ import annotations

import base64
import hashlib

from lxml import etree

from nfse_sefin.cert import Certificate
from nfse_sefin.errors import NFSeError
from nfse_sefin.perfis import (
    ALG_C14N,
    ALG_ENVELOPED,
    NS_XMLDSIG,
    PERFIL_PADRAO,
    Perfil,
)

__all__ = ["assinar", "verificar", "AssinaturaError", "NS_NFSE", "ELEMENTOS_ASSINAVEIS"]

NS_NFSE = "http://www.sped.fazenda.gov.br/nfse"

ELEMENTOS_ASSINAVEIS = ("infDPS", "infPedReg", "infEvento")
"""O que se assina em cada documento desta API, na ordem em que se procura.

`infDPS` na DPS, `infPedReg` no pedido de registro de evento, `infEvento` no evento.
"""


class AssinaturaError(NFSeError):
    """O XML não pôde ser assinado, ou a assinatura não confere."""


def _canonicalizar(elemento: etree._Element) -> bytes:
    """C14N 1.0 inclusiva, que é o que `ALG_C14N` nomeia."""
    return etree.tostring(elemento, method="c14n", exclusive=False, with_comments=False)


def _localizar_assinavel(raiz: etree._Element) -> etree._Element:
    for nome in ELEMENTOS_ASSINAVEIS:
        achado = raiz.find(f"{{{NS_NFSE}}}{nome}")
        if achado is None:
            achado = raiz.find(nome)
        if achado is not None:
            return achado
    esperados = ", ".join(ELEMENTOS_ASSINAVEIS)
    raise AssinaturaError(
        f"Nenhum elemento assinável encontrado em <{etree.QName(raiz).localname}>. "
        f"Esperado um de: {esperados}."
    )


def _montar_signed_info(
    pai: etree._Element, uri: str, digest_b64: str, perfil: Perfil
) -> etree._Element:
    """Monta o `SignedInfo` **já dentro** de `pai`.

    Montar solto e anexar depois parece equivalente e não é: mover subárvore entre
    árvores faz o `lxml` reescrever declarações de namespace, e o `SignedInfo`
    canonicalizado antes do `append` deixa de bater com o que sai na serialização
    final. O digest passa, a assinatura não, e o erro que a SEFIN devolve não diz
    que a causa foi essa.

    Construindo no lugar, os bytes assinados são por construção os bytes enviados.
    """
    signed_info = etree.SubElement(pai, f"{{{NS_XMLDSIG}}}SignedInfo")
    etree.SubElement(signed_info, f"{{{NS_XMLDSIG}}}CanonicalizationMethod", Algorithm=ALG_C14N)
    etree.SubElement(
        signed_info, f"{{{NS_XMLDSIG}}}SignatureMethod", Algorithm=perfil.algoritmo_assinatura
    )

    referencia = etree.SubElement(signed_info, f"{{{NS_XMLDSIG}}}Reference", URI=uri)
    transforms = etree.SubElement(referencia, f"{{{NS_XMLDSIG}}}Transforms")
    # Exatamente dois, nesta ordem. O XSD 1.00 fixa minOccurs=2 maxOccurs=2.
    etree.SubElement(transforms, f"{{{NS_XMLDSIG}}}Transform", Algorithm=ALG_ENVELOPED)
    etree.SubElement(transforms, f"{{{NS_XMLDSIG}}}Transform", Algorithm=ALG_C14N)
    etree.SubElement(referencia, f"{{{NS_XMLDSIG}}}DigestMethod", Algorithm=perfil.algoritmo_digest)
    etree.SubElement(referencia, f"{{{NS_XMLDSIG}}}DigestValue").text = digest_b64
    return signed_info


def assinar(
    xml: bytes,
    certificado: Certificate,
    perfil: Perfil = PERFIL_PADRAO,
) -> bytes:
    """Assina o XML e devolve os **bytes finais**, prontos para gzip+base64.

    O elemento assinado é `infDPS` (ou `infPedReg`/`infEvento`), referenciado pelo seu
    `Id`. A `Signature` entra como último filho da raiz, irmã do elemento assinado.

    Args:
        xml: o documento serializado, ainda sem assinatura.
        certificado: quem assina. A chave privada não sai de `cert.py`.
        perfil: decide `SignatureMethod` e `DigestMethod`. O resto é igual nos dois.

    Raises:
        AssinaturaError: XML malformado, sem elemento assinável, ou sem `Id`.
    """
    try:
        raiz = etree.fromstring(xml)
    except etree.XMLSyntaxError as exc:
        raise AssinaturaError(f"XML inválido para assinatura: {exc}") from exc

    assinavel = _localizar_assinavel(raiz)
    identificador = assinavel.get("Id")
    if not identificador:
        raise AssinaturaError(
            f"<{etree.QName(assinavel).localname}> não tem atributo `Id`, e a "
            "referência da assinatura é montada a partir dele."
        )

    # O digest é sobre o elemento assinável canonicalizado. O transform enveloped não
    # muda nada aqui porque a Signature é irmã, não ancestral, do elemento assinado.
    digest = hashlib.new(perfil.hash_hashlib, _canonicalizar(assinavel)).digest()

    # `nsmap={None: ...}` declara o namespace como **default**, que é o que evita o
    # prefixo `ds:` e portanto o E1228. O `lxml-stubs` tipa `nsmap` como
    # `dict[str, str]` e não admite a chave `None`, embora seja a API documentada do
    # `lxml` para namespace default.
    nsmap: dict[str, str] = {None: NS_XMLDSIG}  # type: ignore[dict-item]
    elemento = etree.SubElement(raiz, f"{{{NS_XMLDSIG}}}Signature", nsmap=nsmap)
    signed_info = _montar_signed_info(
        elemento, f"#{identificador}", base64.b64encode(digest).decode("ascii"), perfil
    )

    assinatura_bruta = certificado.assinar(_canonicalizar(signed_info), perfil.hash_hashlib)
    etree.SubElement(elemento, f"{{{NS_XMLDSIG}}}SignatureValue").text = base64.b64encode(
        assinatura_bruta
    ).decode("ascii")
    # `KeyInfo` é obrigatório no XSD 1.00 e opcional no 1.01. Emitir sempre vale para
    # os dois, e é o que permite ao servidor conferir sem consultar nada.
    key_info = etree.SubElement(elemento, f"{{{NS_XMLDSIG}}}KeyInfo")
    x509_data = etree.SubElement(key_info, f"{{{NS_XMLDSIG}}}X509Data")
    etree.SubElement(
        x509_data, f"{{{NS_XMLDSIG}}}X509Certificate"
    ).text = certificado.certificado_der_b64

    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8", standalone=True)


def verificar(xml: bytes, perfil: Perfil = PERFIL_PADRAO) -> bool:
    """Confere digest e assinatura usando o certificado embutido no próprio XML.

    Não valida cadeia nem confiança — não é isso que serve aqui. Serve para provar que
    o que saiu daqui sobrevive ao caminho de ida (assinar → gzip → base64 → decodificar
    → descomprimir) sem que nada tenha mexido num byte.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.x509 import load_der_x509_certificate

    raiz = etree.fromstring(xml)
    assinatura = raiz.find(f"{{{NS_XMLDSIG}}}Signature")
    if assinatura is None:
        return False

    signed_info = assinatura.find(f"{{{NS_XMLDSIG}}}SignedInfo")
    valor = assinatura.findtext(f"{{{NS_XMLDSIG}}}SignatureValue")
    certificado_b64 = assinatura.findtext(
        f"{{{NS_XMLDSIG}}}KeyInfo/{{{NS_XMLDSIG}}}X509Data/{{{NS_XMLDSIG}}}X509Certificate"
    )
    if signed_info is None or not valor or not certificado_b64:
        return False

    # O digest tem de bater com o elemento assinável como ele está agora.
    assinavel = _localizar_assinavel(raiz)
    esperado = signed_info.findtext(f"{{{NS_XMLDSIG}}}Reference/{{{NS_XMLDSIG}}}DigestValue")
    calculado = base64.b64encode(
        hashlib.new(perfil.hash_hashlib, _canonicalizar(assinavel)).digest()
    ).decode("ascii")
    if esperado != calculado:
        return False

    publica = load_der_x509_certificate(base64.b64decode(certificado_b64)).public_key()
    if not isinstance(publica, rsa.RSAPublicKey):
        return False
    algoritmo = _hashes.SHA1() if perfil.hash_hashlib == "sha1" else _hashes.SHA256()
    try:
        publica.verify(
            base64.b64decode(valor),
            _canonicalizar(signed_info),
            padding.PKCS1v15(),
            algoritmo,
        )
    except InvalidSignature:
        return False
    return True

"""Certificado ICP-Brasil A1 (`.pfx`) e o `ssl.SSLContext` para mTLS.

Toda a API do Sistema Nacional exige certificado cliente. Sem ele o SEFIN devolve
403 e o ADN derruba a conexão no handshake — inclusive no Swagger de produção
restrita. Este módulo é a porta de entrada.

Certificado A3 (token, smartcard) é não-objetivo declarado do v1.

## O incômodo do arquivo em disco

`ssl.SSLContext.load_cert_chain` só aceita **caminho de arquivo**. Não existe
sobrecarga que receba bytes. Então material de chave privada ICP-Brasil precisa
tocar o disco, em claro, para o mTLS acontecer.

`ssl_context()` reduz a janela ao mínimo: cria o arquivo com 0600 antes de escrever,
fecha, carrega, e apaga num `finally`. Nessa ordem — apagar antes de carregar
falharia no Windows, onde não se remove arquivo aberto. O `SSLContext` retém o
material carregado, então apagar depois não quebra nada.
"""

from __future__ import annotations

import os
import ssl
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    NoEncryption,
    PrivateFormat,
    pkcs12,
)
from cryptography.hazmat.primitives.serialization.pkcs12 import PKCS12PrivateKeyTypes
from cryptography.x509.oid import NameOID

from nfsenacional.errors import CertificadoIlegivelError, CertificadoVencidoError

__all__ = ["Certificate", "DIAS_AVISO_VENCIMENTO"]

DIAS_AVISO_VENCIMENTO = 30
"""Abaixo disto, `precisa_renovar` fica verdadeiro."""

# OIDs de PBE do PKCS#12 clássico, na codificação DER em que aparecem no arquivo.
# Procurar a sequência de bytes crus evita ter que escrever um parser ASN.1 só para
# emitir uma mensagem de erro melhor.
_OIDS_LEGADOS: dict[str, bytes] = {
    "pbeWithSHAAnd3-KeyTripleDES-CBC": bytes.fromhex("060a2a864886f70d010c0103"),
    "pbeWithSHAAnd40BitRC2-CBC": bytes.fromhex("060a2a864886f70d010c0106"),
}


def _tem_cifras_legadas(blob: bytes) -> bool:
    return any(oid in blob for oid in _OIDS_LEGADOS.values())


# `load_key_and_certificates` devolve uma união mais larga do que o PKCS#12 sabe
# reserializar — inclui DH e ML-DSA, que não passam por
# `serialize_key_and_certificates`. Estreitar aqui troca um `TypeError` obscuro lá
# na frente por uma mensagem que diz o que o arquivo tem de errado.
_TIPOS_DE_CHAVE_SUPORTADOS = (
    rsa.RSAPrivateKey,
    dsa.DSAPrivateKey,
    ec.EllipticCurvePrivateKey,
    ed25519.Ed25519PrivateKey,
    ed448.Ed448PrivateKey,
)


@dataclass(frozen=True, slots=True)
class Certificate:
    """Um certificado A1 carregado, com a chave privada em memória.

    A chave e o certificado ficam fora do `repr` de propósito. Um `print(cert)` num
    log de produção não pode vazar material de chave privada, e o `repr` que o
    dataclass gera sozinho vazaria.
    """

    cn: str
    """Common Name do titular.

    Num e-CNPJ ICP-Brasil vem no formato `RAZAO SOCIAL:CNPJ`.
    """

    nao_antes: datetime
    """Início da validade, em UTC."""

    nao_depois: datetime
    """Fim da validade, em UTC. É o que `validade` reporta."""

    usa_cifras_legadas: bool
    """O `.pfx` de origem usa PBE clássico (3DES/RC2-40) em vez de PBES2.

    Não é problema por si: as builds atuais de `cryptography` embarcam um OpenSSL que
    lê esses arquivos sem reclamar. Vira problema em build ligada a um OpenSSL 3.x de
    sistema sem o legacy provider, e é informação que o `doctor` reporta.
    """

    _chave: PKCS12PrivateKeyTypes = field(repr=False)
    _certificado: x509.Certificate = field(repr=False)
    _cadeia: tuple[x509.Certificate, ...] = field(repr=False, default=())

    # ------------------------------------------------------------------ carga

    @classmethod
    def from_pfx(cls, caminho: str | os.PathLike[str], password: str | bytes) -> Certificate:
        """Carrega um `.pfx` / `.p12` do disco."""
        return cls.from_bytes(Path(caminho).read_bytes(), password)

    @classmethod
    def from_bytes(cls, blob: bytes, password: str | bytes) -> Certificate:
        """Carrega um PKCS#12 já em memória."""
        senha = password.encode("utf-8") if isinstance(password, str) else password
        legado = _tem_cifras_legadas(blob)

        try:
            chave, certificado, extras = pkcs12.load_key_and_certificates(blob, senha)
        except (ValueError, TypeError) as exc:
            raise CertificadoIlegivelError(
                cls._explicar_falha(legado), usa_cifras_legadas=legado
            ) from exc

        if chave is None or certificado is None:
            raise CertificadoIlegivelError(
                "O arquivo abriu mas não contém par de chave privada e certificado. "
                "Um `.pfx` de certificado A1 tem os dois; confira se o arquivo não é "
                "só a cadeia pública.",
                usa_cifras_legadas=legado,
            )

        if not isinstance(chave, _TIPOS_DE_CHAVE_SUPORTADOS):
            raise CertificadoIlegivelError(
                f"O arquivo traz uma chave privada do tipo {type(chave).__name__}, que "
                "não é utilizável em mTLS por esta biblioteca. Certificado A1 "
                "ICP-Brasil usa RSA.",
                usa_cifras_legadas=legado,
            )

        return cls(
            cn=cls._extrair_cn(certificado),
            nao_antes=certificado.not_valid_before_utc,
            nao_depois=certificado.not_valid_after_utc,
            usa_cifras_legadas=legado,
            _chave=chave,
            _certificado=certificado,
            _cadeia=tuple(extras),
        )

    @staticmethod
    def _explicar_falha(legado: bool) -> str:
        """A mensagem que separa as duas causas indistinguíveis lá embaixo.

        O `cryptography` levanta `Invalid password or PKCS12 data` tanto para senha
        errada quanto para algoritmo recusado, e essa ambiguidade é a razão de este
        ser o ticket de suporte mais comum do gênero. A mensagem não adivinha: ela
        diz qual dos dois é plausível *para este arquivo* e como confirmar.
        """
        if not legado:
            return (
                "Não foi possível abrir o certificado. Este arquivo usa PKCS#12 "
                "moderno (PBES2), então a causa provável é senha incorreta. "
                "Confirme com: openssl pkcs12 -in arquivo.pfx -noout"
            )
        return (
            "Não foi possível abrir o certificado. Atenção: este arquivo usa cifras "
            "PKCS#12 legadas (3DES/RC2-40), comuns em certificados A1 ICP-Brasil. "
            "A senha pode estar correta e ainda assim falhar, se o OpenSSL desta "
            "instalação for 3.x de sistema sem o legacy provider habilitado. "
            "Para distinguir, rode: openssl pkcs12 -in arquivo.pfx -legacy -noout — "
            "se isso funcionar e aqui não, o problema é a build, não a senha, e "
            "instalar o wheel oficial do cryptography (que embarca o próprio "
            "OpenSSL) resolve."
        )

    @staticmethod
    def _extrair_cn(certificado: x509.Certificate) -> str:
        atributos = certificado.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if not atributos:
            return ""
        valor = atributos[0].value
        return valor if isinstance(valor, str) else valor.decode("utf-8", errors="replace")

    # ----------------------------------------------------------- diagnóstico

    @property
    def validade(self) -> datetime:
        """Quando o certificado vence, em UTC."""
        return self.nao_depois

    @property
    def dias_para_vencer(self) -> int:
        """Dias até vencer. Negativo se já venceu."""
        return (self.nao_depois - datetime.now(timezone.utc)).days

    @property
    def vencido(self) -> bool:
        agora = datetime.now(timezone.utc)
        return not (self.nao_antes <= agora <= self.nao_depois)

    @property
    def precisa_renovar(self) -> bool:
        """Vence em menos de 30 dias, ou já venceu.

        O `doctor` transforma isto num aviso. Emitir com certificado vencido falha no
        handshake, e o erro que volta não diz que o problema é a data.
        """
        return self.dias_para_vencer < DIAS_AVISO_VENCIMENTO

    def exigir_valido(self) -> None:
        """Levanta `CertificadoVencidoError` se estiver fora do período de validade."""
        if not self.vencido:
            return
        agora = datetime.now(timezone.utc)
        if agora < self.nao_antes:
            raise CertificadoVencidoError(
                f"Certificado de {self.cn!r} só passa a valer em "
                f"{self.nao_antes:%Y-%m-%d %H:%M} UTC."
            )
        raise CertificadoVencidoError(
            f"Certificado de {self.cn!r} venceu em {self.nao_depois:%Y-%m-%d %H:%M} UTC, "
            f"há {-self.dias_para_vencer} dias."
        )

    # ------------------------------------------------------------------ mTLS

    def ssl_context(self) -> ssl.SSLContext:
        """Monta o `SSLContext` para autenticação mútua.

        O material privado toca o disco pelo tempo mínimo: arquivo criado com 0600,
        escrito, fechado, carregado, e removido num `finally` — mesmo se
        `load_cert_chain` levantar.
        """
        contexto = ssl.create_default_context()
        descritor, caminho = tempfile.mkstemp(prefix="nfsenacional-", suffix=".pem")
        try:
            os.fchmod(descritor, 0o600)
            with os.fdopen(descritor, "wb") as arquivo:
                arquivo.write(self._pem_para_load_cert_chain())
            # O arquivo está fechado aqui. Carregar antes de fechar lê conteúdo
            # truncado; apagar antes de carregar quebra no Windows.
            contexto.load_cert_chain(caminho)
        finally:
            os.unlink(caminho)
        return contexto

    def _pem_para_load_cert_chain(self) -> bytes:
        """Chave privada sem cifra, certificado, e a cadeia — nesta ordem.

        `NoEncryption` é inevitável: `load_cert_chain` sem `password` exige chave em
        claro, e passar senha só moveria o segredo para a memória do processo, que é
        exatamente onde ele já está.
        """
        partes = [
            self._chave.private_bytes(
                encoding=Encoding.PEM,
                format=PrivateFormat.PKCS8,
                encryption_algorithm=NoEncryption(),
            ),
            self._certificado.public_bytes(Encoding.PEM),
        ]
        partes.extend(intermediario.public_bytes(Encoding.PEM) for intermediario in self._cadeia)
        return b"".join(partes)

    def exportar_pfx(self, password: str | bytes) -> bytes:
        """Reexporta como PKCS#12 cifrado. Útil para fixture de teste, não para uso normal."""
        senha = password.encode("utf-8") if isinstance(password, str) else password
        return pkcs12.serialize_key_and_certificates(
            name=self.cn.encode("utf-8"),
            key=self._chave,
            cert=self._certificado,
            cas=self._cadeia or None,
            encryption_algorithm=BestAvailableEncryption(senha),
        )

"""Testes de `nfse_sefin.cert`.

Três coisas aqui não são cobertura de rotina e merecem existir por si:

- que o `repr` **não** vaza chave privada;
- que `ssl_context()` não deixa arquivo de chave para trás, nem quando falha;
- que a mensagem de erro de `.pfx` ilegível distingue as duas causas que o
  `cryptography` funde numa exceção só.
"""

from __future__ import annotations

import os
import ssl
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

from nfse_sefin.cert import DIAS_AVISO_VENCIMENTO, Certificate
from nfse_sefin.errors import (
    CertificadoError,
    CertificadoIlegivelError,
    CertificadoVencidoError,
    NFSeError,
)
from tests.conftest import PfxGerado

# --------------------------------------------------------------------- carga


def test_carrega_de_bytes(pfx_valido: PfxGerado) -> None:
    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)
    assert cert.cn == pfx_valido.cn


def test_carrega_de_arquivo(pfx_valido: PfxGerado, tmp_path: Path) -> None:
    caminho = tmp_path / "empresa.pfx"
    caminho.write_bytes(pfx_valido.blob)

    cert = Certificate.from_pfx(caminho, pfx_valido.senha)

    assert cert.cn == pfx_valido.cn


def test_senha_aceita_str_e_bytes(pfx_valido: PfxGerado) -> None:
    por_str = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)
    por_bytes = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha.encode("utf-8"))
    assert por_str.cn == por_bytes.cn


def test_cn_tem_a_forma_de_e_cnpj(pfx_valido: PfxGerado) -> None:
    """Num e-CNPJ ICP-Brasil o CN é `RAZÃO SOCIAL:CNPJ`."""
    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)
    razao, _, cnpj = cert.cn.partition(":")
    assert razao
    assert cnpj.isdigit() and len(cnpj) == 14


def test_validade_bate_com_o_certificado(pfx_valido: PfxGerado) -> None:
    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)
    # O X.509 guarda segundos inteiros; a fixture tem microssegundos.
    assert abs((cert.validade - pfx_valido.nao_depois).total_seconds()) < 1
    assert cert.validade == cert.nao_depois


# ------------------------------------------------------------------- falhas


def test_senha_errada_levanta_certificado_ilegivel(pfx_valido: PfxGerado) -> None:
    with pytest.raises(CertificadoIlegivelError) as capturado:
        Certificate.from_bytes(pfx_valido.blob, "senha-errada")

    assert not capturado.value.usa_cifras_legadas
    assert "senha incorreta" in str(capturado.value)


def test_mensagem_de_erro_aponta_o_comando_que_confirma(pfx_valido: PfxGerado) -> None:
    """Erro de suporte só serve se disser o que fazer em seguida."""
    with pytest.raises(CertificadoIlegivelError) as capturado:
        Certificate.from_bytes(pfx_valido.blob, "senha-errada")

    assert "openssl pkcs12" in str(capturado.value)


def test_arquivo_que_nao_e_pkcs12(pfx_valido: PfxGerado) -> None:
    with pytest.raises(CertificadoIlegivelError):
        Certificate.from_bytes(b"isto nao e um pkcs12", pfx_valido.senha)


def test_mensagem_muda_quando_o_arquivo_usa_cifras_legadas() -> None:
    """A ambiguidade que este projeto existe para desfazer.

    O `cryptography` levanta `Invalid password or PKCS12 data` tanto para senha
    errada quanto para algoritmo recusado. O blob aqui carrega os OIDs de PBE
    clássico, então a mensagem tem de mencionar a build de OpenSSL, e não afirmar
    que a senha está errada.
    """
    oid_3des = bytes.fromhex("060a2a864886f70d010c0103")
    blob = b"\x30\x82" + oid_3des + b"lixo que nao abre"

    with pytest.raises(CertificadoIlegivelError) as capturado:
        Certificate.from_bytes(blob, "qualquer")

    assert capturado.value.usa_cifras_legadas
    texto = str(capturado.value)
    assert "legadas" in texto
    assert "legacy provider" in texto
    assert "-legacy" in texto


def test_hierarquia_de_excecoes(pfx_valido: PfxGerado) -> None:
    """Quem integra captura `NFSeError` e pega tudo que é nosso."""
    with pytest.raises(NFSeError):
        Certificate.from_bytes(pfx_valido.blob, "senha-errada")
    with pytest.raises(CertificadoError):
        Certificate.from_bytes(pfx_valido.blob, "senha-errada")


# --------------------------------------------------------------- vencimento


def test_certificado_valido_nao_pede_renovacao(pfx_valido: PfxGerado) -> None:
    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)
    assert not cert.vencido
    assert not cert.precisa_renovar
    assert cert.dias_para_vencer > DIAS_AVISO_VENCIMENTO
    cert.exigir_valido()


def test_aviso_dispara_abaixo_de_trinta_dias(pfx_vencendo: PfxGerado) -> None:
    cert = Certificate.from_bytes(pfx_vencendo.blob, pfx_vencendo.senha)
    assert not cert.vencido
    assert cert.precisa_renovar
    assert 0 <= cert.dias_para_vencer < DIAS_AVISO_VENCIMENTO
    cert.exigir_valido()  # avisar não é impedir


def test_certificado_vencido_carrega_mas_se_declara(pfx_vencido: PfxGerado) -> None:
    """Carregar vencido é permitido de propósito.

    O `doctor` precisa abrir o arquivo para conseguir dizer "venceu há 12 dias".
    Estourar na carga deixaria o usuário sem diagnóstico nenhum.
    """
    cert = Certificate.from_bytes(pfx_vencido.blob, pfx_vencido.senha)

    assert cert.vencido
    assert cert.precisa_renovar
    assert cert.dias_para_vencer < 0

    with pytest.raises(CertificadoVencidoError, match="venceu em"):
        cert.exigir_valido()


def test_certificado_ainda_nao_valido(pfx_futuro: PfxGerado) -> None:
    cert = Certificate.from_bytes(pfx_futuro.blob, pfx_futuro.senha)

    assert cert.vencido  # "fora do período de validade", nos dois sentidos
    with pytest.raises(CertificadoVencidoError, match="só passa a valer"):
        cert.exigir_valido()


# ------------------------------------------------------------------- sigilo


def test_repr_nao_vaza_chave_privada(pfx_valido: PfxGerado) -> None:
    """Um `print(cert)` num log de produção não pode despejar a chave.

    O `repr` que o dataclass gera sozinho incluiria os campos de chave e
    certificado. Este teste é o que segura o `field(repr=False)` no lugar.
    """
    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)

    texto = repr(cert)

    assert "PRIVATE KEY" not in texto
    assert "_chave" not in texto
    assert "_certificado" not in texto
    assert "_cadeia" not in texto
    assert cert.cn in texto  # o que é seguro mostrar, continua aparecendo


def test_pem_interno_tem_chave_e_certificado(pfx_valido: PfxGerado) -> None:
    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)

    pem = cert._pem_para_load_cert_chain()

    assert b"-----BEGIN PRIVATE KEY-----" in pem
    assert b"-----BEGIN CERTIFICATE-----" in pem
    assert pem.index(b"BEGIN PRIVATE KEY") < pem.index(b"BEGIN CERTIFICATE")


# --------------------------------------------------------------------- mTLS


def test_ssl_context_carrega_a_cadeia(pfx_valido: PfxGerado) -> None:
    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)

    contexto = cert.ssl_context()

    assert isinstance(contexto, ssl.SSLContext)
    assert contexto.verify_mode is ssl.CERT_REQUIRED
    assert contexto.check_hostname is True
    # Uma cadeia carregada aparece aqui; um contexto vazio devolve lista vazia.
    assert contexto.get_ca_certs() is not None
    assert len(contexto.get_ciphers()) > 0


def test_ssl_context_nao_deixa_arquivo_para_tras(pfx_valido: PfxGerado) -> None:
    """P4: a chave privada toca o disco, e tem de sair de lá.

    Compara o conteúdo do diretório temporário antes e depois. Qualquer resíduo
    `nfse-sefin-*.pem` é chave privada ICP-Brasil esquecida em claro.
    """
    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)
    temporarios = Path(tempfile.gettempdir())

    antes = set(temporarios.glob("nfse-sefin-*.pem"))
    cert.ssl_context()
    depois = set(temporarios.glob("nfse-sefin-*.pem"))

    assert depois == antes


def test_ssl_context_apaga_o_arquivo_mesmo_quando_falha(
    pfx_valido: PfxGerado, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O `finally` é o que importa: falha no meio não pode deixar chave em disco."""
    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)
    temporarios = Path(tempfile.gettempdir())

    def explode(self: ssl.SSLContext, *args: object, **kwargs: object) -> None:
        raise ssl.SSLError("falha simulada ao carregar a cadeia")

    monkeypatch.setattr(ssl.SSLContext, "load_cert_chain", explode)

    antes = set(temporarios.glob("nfse-sefin-*.pem"))
    with pytest.raises(ssl.SSLError):
        cert.ssl_context()

    assert set(temporarios.glob("nfse-sefin-*.pem")) == antes


def test_arquivo_temporario_nasce_com_0600(
    pfx_valido: PfxGerado, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A permissão tem de estar certa **antes** de o conteúdo ser escrito.

    Espiona no momento do `load_cert_chain`, que é o único instante em que o arquivo
    existe com a chave dentro.
    """
    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)
    observado: dict[str, int] = {}
    original = ssl.SSLContext.load_cert_chain

    def espiao(self: ssl.SSLContext, certfile: str, *args: object, **kwargs: object) -> None:
        observado["modo"] = os.stat(certfile).st_mode & 0o777
        observado["tamanho"] = os.stat(certfile).st_size
        original(self, certfile, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ssl.SSLContext, "load_cert_chain", espiao)
    cert.ssl_context()

    assert observado["modo"] == 0o600, f"modo {observado['modo']:o}, esperado 600"
    assert observado["tamanho"] > 0, "arquivo carregado antes de ser fechado"


def test_reexportar_pfx_faz_round_trip(pfx_valido: PfxGerado) -> None:
    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)

    reexportado = Certificate.from_bytes(cert.exportar_pfx("outra-senha"), "outra-senha")

    assert reexportado.cn == cert.cn
    assert reexportado.nao_depois == cert.nao_depois
    assert not reexportado.usa_cifras_legadas


def test_pfx_moderno_nao_e_marcado_como_legado(pfx_valido: PfxGerado) -> None:
    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)
    assert not cert.usa_cifras_legadas


def test_certificate_e_imutavel(pfx_valido: PfxGerado) -> None:
    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)
    with pytest.raises(AttributeError):
        cert.cn = "OUTRA EMPRESA"  # type: ignore[misc]


def test_dias_para_vencer_acompanha_a_validade(pfx_vencendo: PfxGerado) -> None:
    cert = Certificate.from_bytes(pfx_vencendo.blob, pfx_vencendo.senha)
    esperado = (pfx_vencendo.nao_depois - pfx_vencendo.nao_antes) - timedelta(days=-1)
    assert 0 <= cert.dias_para_vencer <= esperado.days


# ------------------------------------------------- de onde sai o CNPJ

# Um e-CNPJ ICP-Brasil pode trazer o CNPJ em três lugares, e eles nem sempre concordam.
# O que decide é onde a SEFIN procura — E1209 nomeia o `otherName`, OID 2.16.76.1.3.3.


def test_cnpj_do_othername(pfx_cnpj_no_othername: PfxGerado) -> None:
    """O lugar normativo, mesmo quando o CN não repete o número."""
    cert = Certificate.from_bytes(pfx_cnpj_no_othername.blob, pfx_cnpj_no_othername.senha)

    assert cert.cnpj == "12345678000195"
    assert not cert.e_pessoa_fisica


def test_cnpj_do_organization_identifier(pfx_cnpj_so_no_org_id: PfxGerado) -> None:
    """`2.5.4.97`, como `CNPJ:...` — o formato que ferramenta moderna gera."""
    cert = Certificate.from_bytes(pfx_cnpj_so_no_org_id.blob, pfx_cnpj_so_no_org_id.senha)

    assert cert.cnpj == "12345678000195"


def test_cnpj_do_common_name(pfx_valido: PfxGerado) -> None:
    """A convenção `RAZÃO SOCIAL:CNPJ`, que é o último recurso."""
    cert = Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)

    assert cert.cnpj == "12345678000195"


def test_othername_vence_org_id_e_cn(pfx_cnpjs_discordantes: PfxGerado) -> None:
    """A guarda que trava a **ordem**, não só a leitura.

    Os três lugares trazem CNPJs diferentes e válidos. Vence o `otherName`, porque é onde
    a SEFIN procura — ler qualquer um dos outros faria a DPS declarar um emitente que não
    é o dono da assinatura, que é E0718.
    """
    cert = Certificate.from_bytes(pfx_cnpjs_discordantes.blob, pfx_cnpjs_discordantes.senha)

    assert cert.cnpj == "12345678000195"
    assert "11222333000181" in cert.cn, "o CN discordante continua lá, e perdeu"


def test_e_cpf_nao_tem_cnpj(pfx_e_cpf: PfxGerado) -> None:
    """e-CPF: o bloco do OID .1 tem 55 dígitos e não pode virar CNPJ por recorte."""
    cert = Certificate.from_bytes(pfx_e_cpf.blob, pfx_e_cpf.senha)

    assert cert.cnpj is None
    assert cert.e_pessoa_fisica


def test_sem_identificacao_devolve_none(pfx_sem_identificacao: PfxGerado) -> None:
    """Carregar nunca valida: ausência de CNPJ é `None`, não exceção."""
    cert = Certificate.from_bytes(pfx_sem_identificacao.blob, pfx_sem_identificacao.senha)

    assert cert.cnpj is None
    assert not cert.e_pessoa_fisica


def test_org_id_vence_o_common_name(pfx_org_id_discorda_do_cn: PfxGerado) -> None:
    """Sem `otherName`, `2.5.4.97` ainda vence o `CN`.

    O `CN` é convenção de exibição e é o mais fácil de vir com número velho depois de uma
    mudança societária; `2.5.4.97` é campo estruturado, feito para carregar identificador.
    """
    cert = Certificate.from_bytes(pfx_org_id_discorda_do_cn.blob, pfx_org_id_discorda_do_cn.senha)

    assert cert.cnpj == "12345678000195"


def test_bloco_de_55_digitos_do_e_cpf_nao_vira_cnpj() -> None:
    """A corrida tem de ter **exatamente** 14 dígitos.

    O `otherName` do e-CPF (OID .1) é um bloco de 55 dígitos colados. Aceitar prefixo de
    uma corrida maior recortaria os 14 primeiros e devolveria um número com cara de CNPJ
    que não é CNPJ de ninguém.
    """
    from nfse_sefin.cert import _catorze_digitos

    assert _catorze_digitos("1" * 55) == ""
    assert _catorze_digitos("1" * 15) == ""
    assert _catorze_digitos("1" * 13) == ""
    assert _catorze_digitos("1" * 14) == "1" * 14
    assert _catorze_digitos("CNPJ:12345678000195") == "12345678000195"
    assert _catorze_digitos("RAZAO 123:12345678000195 sobra 999") == "12345678000195"
